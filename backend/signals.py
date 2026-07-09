from difflib import SequenceMatcher

from models import Participant, SignalResult, CalendarInvite
from groq_client import classify_utterance_role


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()



def name_match_signal(participant: Participant, invite: CalendarInvite) -> SignalResult:
    if not participant.display_name:
        return SignalResult("name_match", participant.participant_id, 0.5, 0.20, 0.1,
                             "no display name available")

    sim = _similarity(participant.display_name, invite.candidate_name)


    device_like = any(tok in participant.display_name.lower()
                       for tok in ["macbook", "iphone", "ipad", "pc-", "room", "conference", "android", "windows"])

    if sim > 0.75:
        return SignalResult("name_match", participant.participant_id, min(1.0, 0.5 + sim / 2), 0.25, 0.8,
                             f"display name '{participant.display_name}' closely matches "
                             f"invite name '{invite.candidate_name}'")
    if device_like:
        return SignalResult("name_match", participant.participant_id, 0.5, 0.10, 0.3,
                             f"display name '{participant.display_name}' looks like a device name, "
                             f"not informative either way")
    return SignalResult("name_match", participant.participant_id, max(0.15, 0.5 - sim), 0.25, 0.6,
                         f"display name '{participant.display_name}' does not resemble "
                         f"invite name '{invite.candidate_name}'")


def email_match_signal(participant: Participant, invite: CalendarInvite) -> SignalResult:
    if not participant.email or not invite.candidate_email:
        return SignalResult("email_match", participant.participant_id, 0.5, 0.0, 0.0,
                             "no verified email available for this participant")
    if participant.email.strip().lower() == invite.candidate_email.strip().lower():
        return SignalResult("email_match", participant.participant_id, 0.98, 0.35, 0.95,
                             f"account email exactly matches candidate email on the invite")
    return SignalResult("email_match", participant.participant_id, 0.05, 0.35, 0.9,
                         f"account email does not match invite candidate email")


def interviewer_elimination_signal(participant: Participant, invite: CalendarInvite) -> SignalResult:
    best = max((_similarity(participant.display_name, name) for name in invite.interviewer_names), default=0.0)
    if best > 0.75:
        matched = max(invite.interviewer_names, key=lambda n: _similarity(participant.display_name, n))
        return SignalResult("interviewer_elimination", participant.participant_id, 0.02, 0.30, 0.85,
                             f"display name matches known interviewer '{matched}' from the invite")
    return SignalResult("interviewer_elimination", participant.participant_id, 0.5, 0.0, 0.0,
                         "does not match any known interviewer name")


def speaking_ratio_signal(participant: Participant, all_participants: list[Participant]) -> SignalResult:
    total = sum(p.speaking_seconds for p in all_participants) or 1.0
    ratio = participant.speaking_seconds / total
    n = len([p for p in all_participants if p.speaking_seconds > 0]) or 1
    fair_share = 1.0 / n

    # confidence in this signal grows with how much total speech we've observed
    evidence = min(1.0, total / 120.0)  

    if ratio > fair_share * 1.3:
        return SignalResult("speaking_ratio", participant.participant_id, 0.7, 0.15, evidence,
                             f"has spoken {ratio:.0%} of total floor time, above their fair share "
                             f"({fair_share:.0%}) — consistent with answering at length")
    if ratio < fair_share * 0.5 and total > 20:
        return SignalResult("speaking_ratio", participant.participant_id, 0.3, 0.15, evidence,
                             f"has spoken only {ratio:.0%} of total floor time — unusually quiet for a candidate")
    return SignalResult("speaking_ratio", participant.participant_id, 0.5, 0.10, evidence,
                         f"speaking share ({ratio:.0%}) is unremarkable so far")


def llm_role_signal(participant: Participant, recent_context: list[str]) -> SignalResult:
    if not participant.utterances:
        return SignalResult("llm_role", participant.participant_id, 0.5, 0.0, 0.0,
                             "has not spoken yet")

    votes_candidate = 0
    votes_interviewer = 0
    sample_reasons = []

    for utt in participant.utterances[-5:]:
        result = classify_utterance_role(utt, recent_context)
        if result["role"] == "candidate":
            votes_candidate += result["confidence"]
        elif result["role"] == "interviewer":
            votes_interviewer += result["confidence"]
        if len(sample_reasons) < 2 and result["role"] != "unclear":
            sample_reasons.append(f"\"{utt[:50]}...\" read as {result['role']} ({result['reason']})")

    total_votes = votes_candidate + votes_interviewer
    evidence = min(1.0, len(participant.utterances) / 8.0)  # more utterances -> trust this signal more

    if total_votes == 0:
        score = 0.5
        reason = "recent utterances were linguistically ambiguous"
    else:
        score = votes_candidate / total_votes
        reason = "; ".join(sample_reasons) if sample_reasons else \
            f"language pattern leans {'candidate' if score > 0.5 else 'interviewer'}-like"

    return SignalResult("llm_role", participant.participant_id, score, 0.30, evidence, reason)