from __future__ import annotations

import pytest
from fastapi import HTTPException

from applimit import web


def test_create_comment_and_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"id": "page1", "page_type": "manual", "comments": []}
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (page, "local", None))
    monkeypatch.setattr(web, "_store_save", lambda value, **_kwargs: (value, "local", None))

    root = web.create_wiki_comment(
        "page1",
        web.WikiCommentCreateRequest(body="First comment", author_name="Mukesh"),
    )["comment"]
    reply = web.create_wiki_comment(
        "page1",
        web.WikiCommentCreateRequest(body="A reply", parent_id=root["id"], author_name="Reader"),
    )["comment"]

    assert root["parent_id"] is None
    assert reply["parent_id"] == root["id"]
    assert len(page["comments"]) == 2


def test_reply_requires_existing_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"id": "page1", "page_type": "manual", "comments": []}
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (page, "local", None))

    with pytest.raises(HTTPException, match="Parent comment not found"):
        web.create_wiki_comment(
            "page1",
            web.WikiCommentCreateRequest(body="Reply", parent_id="missing"),
        )
