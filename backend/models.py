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
    candidate_name: str
    candidate_email: Optional[str]
    interviewer_names: list[str]
    scheduled_start: datetime


@dataclass
class Participant:
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
    signal_name: str
    participant_id: str
    score: float          
    weight: float          
    confidence_in_signal: float  
    reason: str


@dataclass
class ParticipantScore:
    """Aggregated, current-best-guess state for one participant."""
    participant_id: str
    display_name: str
    role_guess: Role
    confidence: float                      # 0..1, normalized across participants
    raw_score: float                       
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