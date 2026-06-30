from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from applimit.captions import CaptionSegment


def transcript_text(segments: list[CaptionSegment]) -> str:
    return " ".join(s.text.strip() for s in segments if s.text.strip())


def _extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model did not return JSON.")
    return json.loads(text[start : end + 1])


def _as_list_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for x in value:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def _as_obj_list(value: Any, key_a: str, key_b: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    for x in value:
        if not isinstance(x, dict):
            continue
        a = str(x.get(key_a, "")).strip()
        b = str(x.get(key_b, "")).strip()
        if a and b:
            out.append({key_a: a, key_b: b})
    return out


def build_insights_ai(
    segments: list[CaptionSegment],
    custom_demand: str | None = None,
) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    txt = transcript_text(segments)
    if not txt:
        raise RuntimeError("Transcript text is empty.")

    # Keep token/cost bounded for long transcripts.
    transcript_slice = txt[:120_000]
    demand = (custom_demand or "").strip()

    schema_hint = {
        "terminologies": ["term 1", "term 2"],
        "concepts": [{"concept": "X", "definition": "clear definition"}],
        "important_points": ["point 1", "point 2"],
        "questions_and_definitions": [{"question": "What is X?", "definition": "X is ..."}],
        "custom_response": "response to custom_demand or empty string",
    }

    prompt = (
        "You are an expert video-study assistant. "
        "Read the transcript and produce high quality educational notes.\n\n"
        "Return ONLY valid JSON with this exact shape:\n"
        f"{json.dumps(schema_hint, ensure_ascii=True)}\n\n"
        "Rules:\n"
        "- terminologies: 10-18 key terms from transcript domain.\n"
        "- concepts: 6-10 core concepts with precise definitions.\n"
        "- important_points: 8-14 concise key takeaways.\n"
        "- questions_and_definitions: 6-10 high-value Q&A entries.\n"
        "- custom_response: if custom_demand is empty return ''.\n"
        "- Do not include markdown, no code fences.\n\n"
        f"custom_demand: {demand!r}\n\n"
        f"transcript:\n{transcript_slice}"
    )

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=os.environ.get("APPLIMIT_OPENAI_MODEL", "gpt-4.1-mini"),
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
    )
    raw = resp.choices[0].message.content or "{}"
    data = _extract_json(raw)

    return {
        "transcript": txt,
        "terminologies": _as_list_str(data.get("terminologies")),
        "concepts": _as_obj_list(data.get("concepts"), "concept", "definition"),
        "important_points": _as_list_str(data.get("important_points")),
        "questions_and_definitions": _as_obj_list(
            data.get("questions_and_definitions"), "question", "definition"
        ),
        "custom_response": str(data.get("custom_response", "")).strip(),
        "segment_count": len(segments),
    }


def build_flashcards_ai(insights_payload: dict[str, Any]) -> list[dict[str, str]]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    terms = _as_list_str(insights_payload.get("terminologies"))
    points = _as_list_str(insights_payload.get("important_points"))
    concepts = _as_obj_list(insights_payload.get("concepts"), "concept", "definition")
    qdefs = _as_obj_list(
        insights_payload.get("questions_and_definitions"), "question", "definition"
    )

    schema_hint = {
        "flashcards": [
            {"front": "Question/Term on front", "back": "Clear concise answer on back"}
        ]
    }
    prompt = (
        "Create high quality study flashcards from this structured material.\n"
        "Return ONLY JSON in this exact shape:\n"
        f"{json.dumps(schema_hint, ensure_ascii=True)}\n\n"
        "Rules:\n"
        "- 15 to 35 flashcards.\n"
        "- Mix term-definition, concept understanding, and question-answer cards.\n"
        "- front and back should be concise and exam-ready.\n"
        "- No markdown, no extra keys.\n\n"
        f"terminologies: {json.dumps(terms, ensure_ascii=False)}\n"
        f"important_points: {json.dumps(points, ensure_ascii=False)}\n"
        f"concepts: {json.dumps(concepts, ensure_ascii=False)}\n"
        f"questions_and_definitions: {json.dumps(qdefs, ensure_ascii=False)}\n"
    )

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=os.environ.get("APPLIMIT_OPENAI_MODEL", "gpt-4.1-mini"),
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
    )
    raw = resp.choices[0].message.content or "{}"
    data = _extract_json(raw)
    cards_raw = data.get("flashcards")
    out: list[dict[str, str]] = []
    if isinstance(cards_raw, list):
        for c in cards_raw:
            if not isinstance(c, dict):
                continue
            f = str(c.get("front", "")).strip()
            b = str(c.get("back", "")).strip()
            if f and b:
                out.append({"front": f, "back": b})
    return out
