
import asyncio
from datetime import datetime, timedelta
from models import Participant, CalendarInvite

SCRIPT_EVENTS = [
    # (delay_seconds, event_type, payload)
    (0.0, "join", {"id": "p1", "name": "Priya Singh", "email": "priya.singh@sherlock.sh"}),
    (0.5, "join", {"id": "p2", "name": "Raj Mehta", "email": "raj.mehta@sherlock.sh"}),
    (1.0, "join", {"id": "p3", "name": "MacBook Pro", "email": None}),  # <- the candidate, joined as a device name
    (1.5, "join", {"id": "p4", "name": "guest_88213", "email": None}),  # <- silent observer

    (2.0, "speak", {"id": "p1", "text": "Thanks for joining today. Can you start by walking me through your background?"}),
    (4.0, "speak", {"id": "p3", "text": "Sure, I'm a backend engineer with about five years of experience, mostly in distributed systems."}),
    (6.0, "speak", {"id": "p3", "text": "I spent the last two years leading the payments infrastructure team at my current company."}),
    (8.0, "speak", {"id": "p2", "text": "Nice. Can you tell me about a time you had to debug a really hard production issue?"}),
    (10.0, "speak", {"id": "p3", "text": "Yeah, we had a race condition in our settlement pipeline that only showed up under load."}),
    (12.0, "speak", {"id": "p3", "text": "I built a reproduction harness, traced it to a missing lock, and shipped a fix with a regression test."}),
    (14.0, "rename", {"id": "p3", "old": "MacBook Pro", "new": "Alex J."}),  # display name changes mid-call
    (14.5, "speak", {"id": "p1", "text": "How do you approach designing for scale from day one?"}),
    (16.0, "speak", {"id": "p3", "text": "I try not to over-engineer early, but I do think hard about data partitioning up front."}),
    (18.0, "speak", {"id": "p2", "text": "What's a project you're most proud of?"}),
    (20.0, "speak", {"id": "p3", "text": "Probably rebuilding our idempotency layer — it cut duplicate charges to nearly zero."}),
    (22.0, "speak", {"id": "p1", "text": "Great, I think that covers it from our side."}),
    (23.0, "speak", {"id": "p3", "text": "Thanks, I really enjoyed this conversation."}),
]


def build_invite() -> CalendarInvite:
    """Note the deliberate trap: the interviewer typed the wrong candidate
    name into the scheduling tool ('Alexander Johnson' instead of the
    candidate's actual preferred name), which is exactly the kind of
    real-world noise Sherlock has to be robust to."""
    return CalendarInvite(
        candidate_name="Alexander Johnson",
        candidate_email="alex.johnson@gmail.com",
        interviewer_names=["Priya Singh", "Raj Mehta"],
        scheduled_start=datetime.utcnow(),
    )


class MeetingSimulator:
    

    def __init__(self, speed_multiplier: float = 2.5):
        self.speed_multiplier = speed_multiplier

    async def events(self):
        last_delay = 0.0
        for delay, event_type, payload in SCRIPT_EVENTS:
            wait = (delay - last_delay) / self.speed_multiplier
            if wait > 0:
                await asyncio.sleep(wait)
            last_delay = delay
            yield event_type, payload