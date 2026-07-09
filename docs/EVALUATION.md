# Evaluation

## How I tested

**Unit level.** Each signal in `signals.py` is tested in isolation against synthetic participants (`tests/test_signals.py`) — e.g. verifying the identity-match signal treats "MacBook Pro" as neutral rather than as a mismatch, and that the elimination signal actively suppresses a participant whose name matches a known interviewer.

**End-to-end / scripted scenario.** `meeting_simulator.py` plays a scripted meeting containing every trap named in the brief in a single run: a candidate joining as a device name, a wrong candidate name on the invite, two interviewers, a silent observer, and a mid-call display-name change. `tests/test_signals.py::test_end_to_end_...` asserts the correct participant is selected and ranked above both interviewers despite all of that.

**Manual dashboard testing.** Ran the full stack (`uvicorn` + browser) and watched confidence scores evolve turn-by-turn in the live UI, confirming the score for the candidate climbs as they answer more questions, and that the "ambiguous" banner correctly appears/disappears as the gap between the top two participants changes.

**Offline-mode testing.** Ran the entire suite and the live server with no `GROQ_API_KEY` set at all, confirming the heuristic fallback in `groq_client.py` keeps the system fully functional (all 8 tests pass without network access).

## Edge cases covered

| Edge case | Test/demo coverage |
|---|---|
| Device name as display name | Unit test + scripted demo (`MacBook Pro`) |
| Wrong candidate name on invite | Scripted demo uses `"Alexander Johnson"` as the invite name while the candidate never states that name |
| Multiple interviewers | Scripted demo includes 2 interviewers; elimination signal checks against the full list |
| Silent observer | Scripted demo includes a participant (`guest_88213`) who never speaks |
| Mid-call display name change | Scripted `rename` event; confirmed scores recompute correctly on the next tick |
| No distinguishing evidence at all | Unit test `test_no_selection_when_evidence_is_too_thin` — confirms the system reports `is_ambiguous=True` rather than picking arbitrarily |
| Missing participant email | Unit test confirms `email_match` contributes zero weight (not a wrong guess) when data is absent |

## Accuracy, in this prototype's terms

With synthetic/scripted data there is no population to compute a precision/recall curve over — the honest claim is narrower: **the system correctly resolves every named edge case in the brief in the scripted demo, using signal combinations that fail individually but succeed together.** Concretely, in the demo scenario:

- The identity-match signal *alone* would be actively wrong (candidate never matches the invite name).
- The elimination signal alone doesn't help identify the candidate, only rule out interviewers.
- The speaking-ratio and LLM-role signals alone are directionally correct but not decisive early in the call (low `confidence_in_signal` while evidence is thin).
- The **combination**, weighted by how much evidence each signal has accumulated, converges to the correct participant by roughly the third or fourth speaking turn, and stays correct thereafter.

A production accuracy claim would require running this against a labeled dataset of real (recorded, consented) interviews across a range of platforms and behaviors — this prototype demonstrates the *mechanism* for getting there, not a validated accuracy number.

## Known limitations

- **No real audio/video analysis.** Voice-print consistency and face-embedding matching are the two highest-value signals not yet implemented — they're the ones that would catch a mid-call identity swap, which none of the current five signals are designed to detect.
- **LLM role classification is per-utterance**, so very short utterances ("Yeah," "Sure") get low-confidence, low-information classifications. Aggregating multiple recent utterances per participant before classifying would improve signal quality at some latency cost.
- **The heuristic fallback is intentionally simple** (keyword/question-mark based). It's a safety net for availability, not a substitute for the LLM signal's accuracy — expect a real deployment to rely on the LLM path being available the large majority of the time.
- **Ambiguity detection uses a fixed margin threshold** (`AMBIGUITY_MARGIN = 0.12`), not a statistically principled confidence interval. It works for the demo's scale but should be recalibrated against real data.
- **No handling yet for a candidate leaving and a different person rejoining** using the same participant slot — a real system would need to treat a `leave` immediately followed by a `join` with different voice/face signals as a fresh identity question, not a continuation.