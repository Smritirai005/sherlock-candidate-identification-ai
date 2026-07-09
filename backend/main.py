

import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from models import Participant, MeetingState
from meeting_simulator import MeetingSimulator, build_invite
from confidence_engine import ConfidenceEngine

app = FastAPI(title="Sherlock Candidate Identification")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


invite = build_invite()
engine = ConfidenceEngine(invite)
state = MeetingState(
    meeting_id="demo-meeting-001",
    invite=invite,
    participants={},
    scores={},
    selected_candidate_id=None,
    is_ambiguous=True,
    transcript_lines_seen=0,
    last_updated=datetime.utcnow(),
    event_log=[],
)

connected_clients: list[WebSocket] = []
recent_transcript: list[str] = []  # rolling window, all speakers, for LLM context


def _log(msg: str):
    stamp = datetime.utcnow().strftime("%H:%M:%S")
    state.event_log.append(f"[{stamp}] {msg}")
    state.event_log = state.event_log[-30:] 


def _serialize_state() -> dict:
    
    return {
        "meeting_id": state.meeting_id,
        "invite": {
            "candidate_name": state.invite.candidate_name,
            "candidate_email": state.invite.candidate_email,
            "interviewer_names": state.invite.interviewer_names,
        },
        "participants": {
            pid: {
                "participant_id": p.participant_id,
                "display_name": p.display_name,
                "email": p.email,
                "webcam_on": p.webcam_on,
                "speaking_seconds": round(p.speaking_seconds, 1),
                "utterance_count": p.utterance_count,
            } for pid, p in state.participants.items()
        },
        "scores": {
            pid: {
                "participant_id": s.participant_id,
                "display_name": s.display_name,
                "role_guess": s.role_guess.value,
                "confidence": round(s.confidence, 3),
                "explanation": s.explanation,
                "signals": [
                    {
                        "signal_name": r.signal_name,
                        "score": round(r.score, 2),
                        "weight": round(r.weight, 2),
                        "confidence_in_signal": round(r.confidence_in_signal, 2),
                        "reason": r.reason,
                    } for r in s.signals
                ],
            } for pid, s in state.scores.items()
        },
        "selected_candidate_id": state.selected_candidate_id,
        "is_ambiguous": state.is_ambiguous,
        "transcript_lines_seen": state.transcript_lines_seen,
        "event_log": state.event_log,
    }


async def _broadcast():
    payload = json.dumps(_serialize_state())
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_text(payload)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        connected_clients.remove(ws)


def _recompute_and_select():
    state.scores = engine.compute(state.participants, recent_transcript)
    selected, ambiguous = engine.select_candidate(state.scores)
    state.selected_candidate_id = selected
    state.is_ambiguous = ambiguous
    if selected:
        state.scores[selected].explanation = engine.explain(state.scores[selected])
    state.last_updated = datetime.utcnow()


async def _run_meeting_simulation():

    _log("Meeting simulation started.")
    sim = MeetingSimulator(speed_multiplier=2.5)
    async for event_type, payload in sim.events():
        if event_type == "join":
            pid = payload["id"]
            state.participants[pid] = Participant(
                participant_id=pid,
                display_name=payload["name"],
                email=payload.get("email"),
                joined_at=datetime.utcnow(),
            )
            _log(f"{payload['name']} joined the meeting.")

        elif event_type == "rename":
            pid = payload["id"]
            if pid in state.participants:
                state.participants[pid].display_name = payload["new"]
                _log(f"Display name changed: '{payload['old']}' -> '{payload['new']}'.")

        elif event_type == "speak":
            pid = payload["id"]
            text = payload["text"]
            if pid in state.participants:
                p = state.participants[pid]
                # rough estimate: ~2.5 words/sec speaking rate
                est_seconds = max(1.0, len(text.split()) / 2.5)
                p.speaking_seconds += est_seconds
                p.utterance_count += 1
                p.utterances.append(text)
                state.transcript_lines_seen += 1
                recent_transcript.append(f"{p.display_name}: {text}")
                _log(f"{p.display_name}: \"{text[:60]}{'...' if len(text) > 60 else ''}\"")

        _recompute_and_select()
        await _broadcast()

    _log("Meeting simulation complete.")
    await _broadcast()


@app.on_event("startup")
async def on_startup():
    
    asyncio.create_task(_run_meeting_simulation())


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)
    await ws.send_text(json.dumps(_serialize_state()))  # send current state immediately
    try:
        while True:
            await ws.receive_text()  
    except WebSocketDisconnect:
        if ws in connected_clients:
            connected_clients.remove(ws)


@app.get("/api/state")
async def get_state():
    return _serialize_state()


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")