from __future__ import annotations

import json
import os
from typing import Any


class ExamGradingError(RuntimeError):
    pass


def grade_long_answer(
    *,
    question: str,
    student_answer: str,
    model_answer: str,
    marking_criteria: list[str],
    max_marks: int,
) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ExamGradingError("AI grading is not configured. Set OPENAI_API_KEY on the server.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=os.environ.get("APPLIMIT_OPENAI_MODEL", "gpt-4.1-mini"),
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a consistent exam marker. Grade only against the supplied model answer and "
                    "marking criteria. Award an integer mark from 0 through max_marks. Return JSON with "
                    "awarded_marks (integer), feedback (concise string), strengths (string array), and "
                    "improvements (string array). Do not infer facts absent from the rubric."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "max_marks": max_marks,
                        "model_answer": model_answer,
                        "marking_criteria": marking_criteria,
                        "student_answer": student_answer,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    raw = response.choices[0].message.content or "{}"
    try:
        result = json.loads(raw)
        awarded = max(0, min(max_marks, int(result.get("awarded_marks", 0))))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ExamGradingError("The AI marker returned an invalid result.") from exc
    return {
        "awarded_marks": awarded,
        "feedback": str(result.get("feedback") or "Answer graded.")[:4000],
        "strengths": [str(value)[:500] for value in (result.get("strengths") or [])[:10]],
        "improvements": [str(value)[:500] for value in (result.get("improvements") or [])[:10]],
    }
