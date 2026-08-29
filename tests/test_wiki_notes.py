from __future__ import annotations

import pytest
from fastapi import HTTPException

from applimit import web


def test_create_page_note_with_unique_title(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"id": "page1", "page_type": "manual", "page_notes": []}
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (page, "local", None))
    monkeypatch.setattr(web, "_store_save", lambda value, **_kwargs: (value, "local", None))

    result = web.create_wiki_note(
        "page1", web.WikiNoteCreateRequest(title="Key idea", body="Remember **this**.")
    )

    assert result["note"]["title"] == "Key idea"
    assert result["note"]["id"]
    assert page["page_notes"] == result["notes"]


def test_page_note_title_is_unique_case_insensitively(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {
        "id": "page1",
        "page_notes": [{"id": "n1", "title": "Key Idea", "body": "Existing"}],
    }
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (page, "local", None))

    with pytest.raises(HTTPException) as error:
        web.create_wiki_note(
            "page1", web.WikiNoteCreateRequest(title="  key   idea ", body="Duplicate")
        )

    assert error.value.status_code == 409
