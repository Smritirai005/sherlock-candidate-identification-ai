# Sherlock — Real-Time Interview Candidate Identification

A working prototype that watches a live interview meeting and continuously figures out **which participant is the candidate** — even when they join as "MacBook Pro," the interviewer typed the wrong name into the calendar invite, or a silent observer is sitting in the call.

Built for the Sherlock internship challenge. Uses **Groq** (Llama 3.3 70B) as the LLM reasoning signal, with an automatic offline fallback so the system never breaks if the API key is missing or unreachable.

![Architecture](docs/architecture.svg)

---

## Why this approach

Sherlock's fraud detectors need to point their cameras and microphones at the right person. The one thing you can never fully trust is a display name — it's user-editable, often a device name, and the interviewer's own metadata (the invite) can be wrong too. So the system is built around one idea:

> **No single fact is ever fully trusted. Every fact is a vote, and votes are weighed by how much evidence backs them.**

Five independent, individually-weak signals each score every participant from 0 (strong evidence *against* being the candidate) to 1 (strong evidence *for*). They're combined into one normalized confidence score per participant, smoothed over time, and re-evaluated after every event in the meeting. The system explains itself by keeping the human-readable reason behind every signal, all the way through to the final explanation.

## The five signals

| Signal | What it checks | Why it's only *weak* evidence alone |
|---|---|---|
| **Identity match** | Fuzzy string match between display name and the invite's candidate name | Beaten by nicknames, device names ("MacBook Pro"), typos |
| **Email match** | Exact match between the participant's account email and the invite's candidate email | Strong when available, but the platform doesn't always expose participant emails |
| **Elimination** | Fuzzy match against *known interviewer* names from the invite — actively suppresses confidence for matched interviewers | Only helps if the interviewer list is accurate and complete (observers aren't on it) |
| **Speaking ratio** | Share of total floor time — candidates tend to give longer answers than any single interviewer asks questions | A very talkative interviewer or a quiet candidate can invert this |
| **LLM role signal** | Groq classifies each utterance as sounding like a question/lead (interviewer) or a first-person answer (candidate) | Language model judgment, not ground truth — can misread short or off-topic turns |

Each signal also reports a **confidence-in-signal** value (how much evidence *it* has personally seen). A participant who hasn't spoken yet contributes zero weight from the speaking and LLM signals — they simply don't vote until they have something to vote on. This is what lets the system **keep learning as the interview progresses**: early on the pick leans on name/email signals; a few minutes in, the speaking-pattern and LLM signals dominate and can override a bad name match.

## Handling the brief's specific edge cases

| Case from the brief | How it's handled |
|---|---|
| Candidate joins as "MacBook Pro" | Identity-match signal treats device-like names as **neutral**, not counter-evidence (see `signals.py::name_match_signal`) |
| Candidate joins using a nickname | Fuzzy matching (`difflib.SequenceMatcher`) tolerates partial matches; LLM/speaking signals compensate further |
| Interviewer enters the wrong candidate name | Demonstrated directly in the scripted demo — invite says "Alexander Johnson," candidate never uses that name, system still identifies them correctly on other signals |
| Multiple interviewers present | Elimination signal checks against *all* names in `interviewer_names`, not just one |
| Candidate changes their display name mid-call | `rename` event updates `Participant.display_name` live; scores recompute on the next tick |
| Multiple observers join silently | Observers who never speak get zero weight from 2 of 5 signals and stay near the neutral 0.5 raw score, so they rank below anyone showing positive evidence |
| Not enough evidence yet | `select_candidate()` refuses to return a pick below a confidence floor, and flags `is_ambiguous=True` rather than guessing |
| Two participants look similar | If the top two confidences are within `AMBIGUITY_MARGIN`, the system still shows a leading guess but flags it as ambiguous in the UI |

## Architecture

```
Meeting platform events ─┐
                          ├─▶ Participant state ─▶ 5 signal detectors ─▶ Confidence engine ─▶ Selected candidate + explanation ─▶ Live dashboard (WebSocket)
Calendar invite ─────────┘
```

- **`meeting_simulator.py`** — stands in for a real Zoom/Meet/Teams webhook adapter. Plays a scripted meeting that deliberately exercises every trap in the brief. **This is the only piece you'd swap out to go live** — everything downstream operates on the same `Participant`/event shape regardless of where events come from.
- **`signals.py`** — the five independent detectors described above. Each is a pure function: `(participant, context) -> SignalResult`. Easy to unit test, easy to add a sixth signal (e.g. real face-embedding similarity to an ID photo) without touching anything else.
- **`confidence_engine.py`** — weighted combination, exponential-moving-average smoothing (so a single noisy line doesn't flip the pick), normalization across participants, and the ambiguity/selection policy.
- **`groq_client.py`** — Groq API wrapper for the LLM role-classification signal and the natural-language explanation. Every call is wrapped in a broad `try/except`; on any failure it falls back to a fast, dependency-free heuristic classifier so the pipeline never stalls on a flaky network call.
- **`main.py`** — FastAPI app: runs the simulated meeting as a background task, recomputes confidence after every event, and broadcasts full state over a WebSocket to any connected browser.
- **`frontend/index.html`** — single-file dashboard (no build step). Renders live confidence bars, role tags, per-signal reasoning, and an evidence log, styled like a case file.

## Setup

```bash
git clone <your-repo-url>
cd sherlock-candidate-id
pip install -r requirements.txt

# Optional but recommended — enables the real LLM signal instead of the offline heuristic
cp .env.example .env
# then edit .env and set GROQ_API_KEY=your_key_here  (free key: https://console.groq.com)

cd backend
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** — the scripted demo meeting starts automatically on server boot and plays out over ~15 seconds (6x real-time speed, configurable in `meeting_simulator.py`).

Run the test suite:
```bash
cd backend && python -m pytest ../tests -v
```

## Plugging into a real meeting platform

Replace `MeetingSimulator` with an adapter that listens to Zoom/Meet/Teams webhooks (or their meeting SDKs) and emits the same three event shapes already used in `main.py`:

```python
("join",   {"id": participant_id, "name": display_name, "email": email_or_none})
("rename", {"id": participant_id, "old": old_name, "new": new_name})
("speak",  {"id": participant_id, "text": utterance_text})
```

Everything downstream — signals, confidence engine, WebSocket broadcast, UI — needs no changes. Real deployments would also want:
- Real audio-derived `speaking_seconds` (from the platform's speaking-activity events) instead of the word-count estimate used here
- A webcam-based signal (e.g. face embedding similarity to a candidate ID photo, if available) — the `Participant.webcam_on` field is already wired for this
- Per-meeting state in Redis/Postgres instead of the single in-memory `MeetingState` used in this prototype

## Key assumptions

- The calendar invite is available but **not fully trusted** — its candidate name can be wrong (this is explicitly demonstrated in the scripted demo), though its candidate email and interviewer list are assumed accurate.
- The platform provides a per-participant audio stream and speaker-attributed transcript, as stated in the brief — this prototype simulates that stream rather than integrating a real platform SDK (see above for the adapter boundary).
- "Speaking seconds" is estimated from transcript word count (~2.5 words/sec) in the simulator; a real deployment would use the platform's actual speaking-activity timestamps.
- One meeting is held in memory at a time in this prototype; the state model is already keyed by `meeting_id` for multi-meeting scaling.

## Trade-offs and what I'd improve next

- **LLM calls are per-utterance and synchronous.** At scale, batch multiple recent utterances per participant into a single Groq call per tick instead of one call per utterance, and move classification to an async queue so a slow LLM response never blocks the event loop.
- **No real audio/video signals yet.** Voice-print continuity (does this audio stream sound like the same person throughout — catches mid-call swaps) and face-embedding match against an ID photo would be strong additions; the signal interface is designed to make this a drop-in addition (`signals.py` already imports nothing platform-specific).
- **Ambiguity handling is threshold-based**, not a full Bayesian posterior. A proper Bayesian update (treating each signal as a likelihood ratio) would give more principled uncertainty bounds than the current weighted-average-plus-margin heuristic.
- **No persistence across reconnects/interview segments.** A real system should snapshot state periodically so a service restart mid-interview doesn't lose evidence already gathered.
- **Single meeting, single process.** Horizontal scaling would move `MeetingState` into Redis keyed by `meeting_id`, and the WebSocket broadcast into a pub/sub fan-out (e.g. Redis Streams or a message broker) so multiple API instances can serve the same meeting's viewers.

## Repository structure

```
sherlock-candidate-id/
├── backend/
│   ├── main.py                # FastAPI app, event loop, WebSocket
│   ├── models.py               # shared dataclasses
│   ├── signals.py               # the 5 weak-signal detectors
│   ├── confidence_engine.py    # combination, smoothing, selection policy
│   ├── groq_client.py          # Groq wrapper + offline fallback
│   └── meeting_simulator.py    # scripted demo meeting (swap for a real adapter)
├── frontend/
│   └── index.html               # single-file live dashboard
├── tests/
│   └── test_signals.py          # unit + end-to-end tests, incl. brief's edge cases
├── docs/
│   ├── architecture.svg
│   └── EVALUATION.md
├── requirements.txt
├── .env.example
└── README.md
```