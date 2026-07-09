from models import Participant, ParticipantScore, SignalResult, Role, CalendarInvite
from signals import (
    name_match_signal, email_match_signal, interviewer_elimination_signal,
    speaking_ratio_signal, llm_role_signal,
)
from groq_client import generate_explanation

EMA_ALPHA = 0.35          
AMBIGUITY_MARGIN = 0.12    
MIN_CONFIDENCE_TO_SELECT = 0.30


class ConfidenceEngine:
    def __init__(self, invite: CalendarInvite):
        self.invite = invite
        self._smoothed_raw: dict[str, float] = {}   # participant_id -> EMA of raw weighted score

    def _combine_signals(self, results: list[SignalResult]) -> tuple[float, float]:
        numerator = 0.0
        denominator = 0.0
        for r in results:
            effective_weight = r.weight * max(r.confidence_in_signal, 0.05)
            numerator += r.score * effective_weight
            denominator += effective_weight
        if denominator == 0:
            return 0.5, 0.0
        return numerator / denominator, denominator

    def compute(self, participants: dict[str, Participant], recent_transcript: list[str]) -> dict[str, ParticipantScore]:
        all_p = list(participants.values())
        raw_per_participant: dict[str, float] = {}
        signals_per_participant: dict[str, list[SignalResult]] = {}

        for pid, p in participants.items():
            results = [
                name_match_signal(p, self.invite),
                email_match_signal(p, self.invite),
                interviewer_elimination_signal(p, self.invite),
                speaking_ratio_signal(p, all_p),
                llm_role_signal(p, recent_transcript),
            ]
            combined, _ = self._combine_signals(results)

            # exponential smoothing across ticks to avoid flicker
            prev = self._smoothed_raw.get(pid, combined)
            smoothed = EMA_ALPHA * combined + (1 - EMA_ALPHA) * prev
            self._smoothed_raw[pid] = smoothed

            raw_per_participant[pid] = smoothed
            signals_per_participant[pid] = results

        total = sum(raw_per_participant.values()) or 1.0
        normalized = {pid: v / total for pid, v in raw_per_participant.items()}

        scores: dict[str, ParticipantScore] = {}
        for pid, p in participants.items():
            role_guess = self._infer_role(pid, signals_per_participant[pid])
            scores[pid] = ParticipantScore(
                participant_id=pid,
                display_name=p.display_name,
                role_guess=role_guess,
                confidence=normalized[pid],
                raw_score=raw_per_participant[pid],
                signals=signals_per_participant[pid],
            )
        return scores

    @staticmethod
    def _infer_role(pid: str, results: list[SignalResult]) -> Role:
        elimination = next((r for r in results if r.signal_name == "interviewer_elimination"), None)
        if elimination and elimination.score < 0.1 and elimination.confidence_in_signal > 0.5:
            return Role.INTERVIEWER
        return Role.UNKNOWN  # resolved to CANDIDATE at selection time for the top pick only

    def select_candidate(self, scores: dict[str, ParticipantScore]) -> tuple[str | None, bool]:
        """Returns (selected_participant_id_or_None, is_ambiguous)."""
        ranked = sorted(scores.values(), key=lambda s: s.confidence, reverse=True)
        if not ranked:
            return None, False

        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None

        if top.confidence < MIN_CONFIDENCE_TO_SELECT:
            return None, True  # not enough evidence yet — refuse to guess

        if second and (top.confidence - second.confidence) < AMBIGUITY_MARGIN:
            return top.participant_id, True  # lean towards top, but flag uncertainty

        return top.participant_id, False

    def explain(self, score: ParticipantScore) -> str:
        summaries = [f"{r.signal_name}: {r.reason} (score {r.score:.2f})"
                     for r in score.signals if r.confidence_in_signal > 0.05]
        return generate_explanation(score.display_name, summaries, score.confidence)