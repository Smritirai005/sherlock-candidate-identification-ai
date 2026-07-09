import os
import json
import re
import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


def _api_key() -> str | None:
    return os.environ.get("GROQ_API_KEY")


def is_live() -> bool:
    """Whether we currently expect real Groq calls to work."""
    return bool(_api_key())


def classify_utterance_role(utterance: str, context: list[str]) -> dict:
    if not _api_key():
        return _heuristic_role_classification(utterance)

    system_prompt = (
        "You are a signal detector inside Sherlock, an interview-fraud-detection "
        "system. You are given ONE utterance from a live job interview transcript, "
        "plus a little context. Decide whether the speaker is more likely acting as "
        "the INTERVIEWER (asking questions, giving instructions, evaluating) or the "
        "CANDIDATE (answering questions, describing their own background/experience/skills). "
        "Respond with ONLY compact JSON, no prose, no markdown fences, in this exact shape: "
        '{"role": "interviewer" | "candidate" | "unclear", "confidence": 0.0-1.0, "reason": "<=15 words"}'
    )
    user_prompt = (
        f"Recent context (may be empty):\n" + "\n".join(context[-4:]) +
        f"\n\nUtterance to classify:\n\"{utterance}\""
    )

    try:
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "temperature": 0,
                "max_tokens": 100,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=6,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        text = re.sub(r"^```json|```$", "", text).strip()
        parsed = json.loads(text)
        parsed["confidence"] = float(parsed.get("confidence", 0.5))
        return parsed
    except Exception as exc:  # noqa: BLE001 - deliberately broad, this is a soft-fail path
        fallback = _heuristic_role_classification(utterance)
        fallback["reason"] += f" (Groq unavailable: {type(exc).__name__}, used heuristic fallback)"
        return fallback


def _heuristic_role_classification(utterance: str) -> dict:
    """Zero-dependency fallback used when Groq is unreachable/unset.
    Cheap but not useless: interview questions are syntactically distinctive."""
    u = utterance.strip().lower()
    question_starters = ("what", "why", "how", "can you", "could you", "tell me",
                          "walk me through", "describe", "have you", "do you")
    first_person_markers = (" i ", "i've", "i'm", "i built", "i worked", "my ",
                             "in my experience", "i led", "i designed")

    is_question = u.endswith("?") or u.startswith(question_starters)
    has_first_person = any(m in f" {u} " for m in first_person_markers)

    if is_question and not has_first_person:
        return {"role": "interviewer", "confidence": 0.65,
                "reason": "phrased as a question, no first-person narrative (heuristic)"}
    if has_first_person and not is_question:
        return {"role": "candidate", "confidence": 0.65,
                "reason": "first-person narrative about own experience (heuristic)"}
    return {"role": "unclear", "confidence": 0.3,
            "reason": "no strong lexical signal either way (heuristic)"}


def generate_explanation(participant_name: str, signal_summaries: list[str], confidence: float) -> str:
    if not _api_key():
        return _template_explanation(participant_name, signal_summaries, confidence)

    prompt = (
        f"Write a 1-2 sentence plain-English explanation for why Sherlock identified "
        f"'{participant_name}' as the interview candidate, at {confidence:.0%} confidence. "
        f"Base it ONLY on this evidence, do not invent anything:\n- " + "\n- ".join(signal_summaries) +
        "\nBe concise and factual, suitable for an auditor reading a case log."
    )
    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "temperature": 0.2,
                "max_tokens": 120,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=6,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:  # noqa: BLE001
        return _template_explanation(participant_name, signal_summaries, confidence)


def _template_explanation(participant_name: str, signal_summaries: list[str], confidence: float) -> str:
    top = "; ".join(signal_summaries[:3])
    return f"{participant_name} selected at {confidence:.0%} confidence based on: {top}."