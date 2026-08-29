from __future__ import annotations

import pytest
from fastapi import HTTPException

from applimit import web


def _question() -> dict:
    return {
        "question": "What is 2 + 2?",
        "options": ["3", "4", "5", "6"],
        "correct_answer": "B",
    }


def test_create_exam_normalizes_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "_store_save", lambda value, **_kwargs: (value, "local", None))
    result = web.create_exam(web.ExamCreateRequest(title="Math", questions=[_question()]))

    assert result["exam"]["question_count"] == 1
    assert result["exam"]["title"] == "Math"


def test_exam_rejects_invalid_answer_key() -> None:
    question = _question()
    question["correct_answer"] = "E"
    with pytest.raises(HTTPException) as error:
        web._normalize_exam_questions([question])
    assert error.value.status_code == 400


def test_answer_is_checked_and_progress_is_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    questions = web._normalize_exam_questions([_question()])
    exam = {
        "id": "exam1",
        "page_type": "exam",
        "title": "Math",
        "exam_questions": questions,
        "exam_statuses": {},
    }
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (exam, "local", None))
    monkeypatch.setattr(web, "_store_save", lambda value, **_kwargs: (value, "local", None))

    result = web.answer_exam_question(
        "exam1",
        web.ExamAnswerRequest(
            question_id=questions[0]["id"], answer="B", user_email="reader@example.com"
        ),
    )

    assert result["result"]["correct"] is True
    assert result["summary"]["completed"] is True
    assert result["summary"]["correct_count"] == 1


def test_public_exam_hides_unattempted_answer_key() -> None:
    questions = web._normalize_exam_questions([_question()])
    public = web._exam_public_payload(
        {"id": "exam1", "title": "Math", "exam_questions": questions, "exam_statuses": {}}
    )
    assert "correct_answer" not in public["questions"][0]
