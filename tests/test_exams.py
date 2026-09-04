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


def test_long_answer_requires_supported_marks_and_model_answer() -> None:
    question = {
        "type": "long_answer",
        "question": "Explain destructive interference.",
        "marks": 5,
        "model_answer": "Two coherent amplitudes cancel when they have opposite phase.",
        "marking_criteria": ["Mentions coherent amplitudes", "Explains opposite phase"],
    }
    normalized = web._normalize_exam_questions([question])[0]
    assert normalized["type"] == "long_answer"
    assert normalized["marks"] == 5
    assert normalized["model_answer"].startswith("Two coherent")

    question["marks"] = 7
    with pytest.raises(HTTPException) as error:
        web._normalize_exam_questions([question])
    assert error.value.status_code == 400


def test_long_answer_is_ai_graded_and_marks_are_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    questions = web._normalize_exam_questions([{
        "type": "long_answer",
        "question": "Explain quantum interference.",
        "marks": 10,
        "model_answer": "Probability amplitudes combine and interfere.",
        "marking_criteria": ["Discusses amplitudes", "Connects amplitudes to probability"],
    }])
    exam = {
        "id": "exam-written",
        "page_type": "exam",
        "title": "Written physics",
        "exam_questions": questions,
        "exam_statuses": {},
    }
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (exam, "local", None))
    monkeypatch.setattr(web, "_store_save", lambda value, **_kwargs: (value, "local", None))
    monkeypatch.setattr(web, "grade_long_answer", lambda **_kwargs: {
        "awarded_marks": 8,
        "feedback": "Clear explanation.",
        "strengths": ["Correct use of amplitudes"],
        "improvements": ["Explain measurement probabilities"],
    })

    result = web.answer_exam_question(
        "exam-written",
        web.ExamAnswerRequest(
            question_id=questions[0]["id"],
            answer="The amplitudes combine constructively or destructively.",
            user_email="reader@example.com",
        ),
    )

    assert result["result"]["awarded_marks"] == 8
    assert result["result"]["max_marks"] == 10
    assert result["summary"]["total_marks"] == 10
    assert result["summary"]["awarded_marks"] == 8
    assert result["summary"]["percentage"] == 80.0


def test_public_long_answer_includes_study_material() -> None:
    questions = web._normalize_exam_questions([{
        "type": "long_answer",
        "question": "Explain a concept.",
        "marks": 5,
        "model_answer": "The standard answer.",
        "marking_criteria": ["Key point"],
    }])
    public = web._exam_public_payload(
        {"id": "exam1", "title": "Study", "exam_questions": questions, "exam_statuses": {}}
    )
    assert public["questions"][0]["model_answer"] == "The standard answer."
    assert public["questions"][0]["marking_criteria"] == ["Key point"]
