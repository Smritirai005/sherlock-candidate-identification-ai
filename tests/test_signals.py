
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from datetime import datetime
from models import Participant, CalendarInvite
from signals import name_match_signal, interviewer_elimination_signal, email_match_signal
from confidence_engine import ConfidenceEngine


def make_invite(**overrides):
    base = dict(
        candidate_name="Alexander Johnson",
        candidate_email="alex.johnson@gmail.com",
        interviewer_names=["Priya Singh", "Raj Mehta"],
        scheduled_start=datetime.utcnow(),
    )
    base.update(overrides)
    return CalendarInvite(**base)


def test_name_match_rewards_close_names():
    invite = make_invite()
    p = Participant("p1", "Alex Johnson")
    result = name_match_signal(p, invite)
    assert result.score > 0.7


def test_name_match_is_neutral_for_device_names():
    invite = make_invite()
    p = Participant("p1", "MacBook Pro")
    result = name_match_signal(p, invite)
    assert 0.4 <= result.score <= 0.6


def test_name_match_punishes_real_but_wrong_name():
    invite = make_invite()
    p = Participant("p1", "Someone Else Entirely")
    result = name_match_signal(p, invite)
    assert result.score < 0.4


def test_interviewer_elimination_catches_known_interviewers():
    invite = make_invite()
    p = Participant("p1", "Priya Singh")
    result = interviewer_elimination_signal(p, invite)
    assert result.score < 0.1
    assert result.confidence_in_signal > 0.5


def test_email_match_is_strong_when_present():
    invite = make_invite()
    p = Participant("p1", "MacBook Pro", email="alex.johnson@gmail.com")
    result = email_match_signal(p, invite)
    assert result.score > 0.9


def test_email_match_neutral_when_absent():
    invite = make_invite()
    p = Participant("p1", "MacBook Pro", email=None)
    result = email_match_signal(p, invite)
    assert result.confidence_in_signal == 0.0  


def test_end_to_end_identifies_candidate_despite_wrong_invite_name_and_device_display_name():
    invite = make_invite(candidate_name="Alexander Johnson")  
    participants = {
        "p1": Participant("p1", "Priya Singh", email="priya@sherlock.sh"),
        "p2": Participant("p2", "Raj Mehta", email="raj@sherlock.sh"),
        "p3": Participant("p3", "MacBook Pro"),  
        "p4": Participant("p4", "guest_9981"),   
    }
    
    answers = [
        "I'm a backend engineer with five years of experience in distributed systems.",
        "I led the payments infrastructure team for the last two years.",
        "I built a reproduction harness and traced the bug to a missing lock.",
        "I try not to over-engineer early, but I plan data partitioning up front.",
    ]
    participants["p3"].utterances = answers
    participants["p3"].utterance_count = len(answers)
    participants["p3"].speaking_seconds = 40.0

    participants["p1"].speaking_seconds = 12.0
    participants["p1"].utterance_count = 2
    participants["p2"].speaking_seconds = 9.0
    participants["p2"].utterance_count = 2

    engine = ConfidenceEngine(invite)
    # run a few ticks to let the EMA smoothing converge
    for _ in range(3):
        scores = engine.compute(participants, [f"MacBook Pro: {a}" for a in answers])
    selected, ambiguous = engine.select_candidate(scores)

    assert selected == "p3", f"expected the device-named participant to be selected, got {selected}"
    assert scores["p1"].confidence < scores["p3"].confidence
    assert scores["p2"].confidence < scores["p3"].confidence


def test_no_selection_when_evidence_is_too_thin():
    invite = make_invite(candidate_email=None)
    participants = {
        "p1": Participant("p1", "guest_1"),
        "p2": Participant("p2", "guest_2"),
    }
    engine = ConfidenceEngine(invite)
    scores = engine.compute(participants, [])
    selected, ambiguous = engine.select_candidate(scores)
    assert ambiguous is True