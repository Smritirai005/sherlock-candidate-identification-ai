"""
models.py
---------
Plain data structures shared across the system. Keeping these dependency-free
(dataclasses only) makes them easy to serialize over the WebSocket and easy
to unit test in isolation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Role(str, Enum):
    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    INTERVIEWER = "interviewer"
    OBSERVER = "observer"


@dataclass
class CalendarInvite:
    """External metadata Sherlock is told is available: the ground-truth
    schedule for the interview, independent of what happens inside the call."""
    candidate_name: str
    candidate_email: Optional[str]
    interviewer_names: list[str]
    scheduled_start: datetime


@dataclass
class Participant:
    """A single meeting participant, as seen by the video-conferencing
    platform. Nothing here is trusted at face value — display_name in
    particular is adversarial-prone (nicknames, device names, typos)."""
    participant_id: str
    display_name: str
    email: Optional[str] = None
    joined_at: Optional[datetime] = None
    left_at: Optional[datetime] = None
    webcam_on: bool = False
    is_screen_sharing: bool = False
    speaking_seconds: float = 0.0
    utterance_count: int = 0
    utterances: list[str] = field(default_factory=list)  # rolling transcript for this speaker


@dataclass
class SignalResult:
    """Output of one signal detector for one participant at one point in time.
    Every signal must justify itself in plain English — that justification is
    what powers the 'why did you pick this person' explanation."""
    signal_name: str
    participant_id: str
    score: float          # 0.0 (strong evidence against) .. 1.0 (strong evidence for)
    weight: float          # how much this signal counts right now (can change over time)
    confidence_in_signal: float  # 0..1, how much evidence the signal itself has seen
    reason: str


@dataclass
class ParticipantScore:
    """Aggregated, current-best-guess state for one participant."""
    participant_id: str
    display_name: str
    role_guess: Role
    confidence: float                      # 0..1, normalized across participants
    raw_score: float                       # pre-normalization weighted sum
    signals: list[SignalResult] = field(default_factory=list)
    explanation: str = ""


@dataclass
class MeetingState:
    """The full current picture of the meeting, as broadcast to the UI."""
    meeting_id: str
    invite: CalendarInvite
    participants: dict[str, Participant]
    scores: dict[str, ParticipantScore]
    selected_candidate_id: Optional[str]
    is_ambiguous: bool
    transcript_lines_seen: int
    last_updated: datetime
    event_log: list[str] = field(default_factory=list)