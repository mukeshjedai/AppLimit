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
    assert root["color"] == "black"


def test_edit_comment_color_and_preserve_thread(monkeypatch):
    import hashlib
    from applimit import active_recall
    page = {"id": "page1", "comments": [{"id": "c1", "body": "old", "author_email": "author@example.com", "parent_id": "root", "created_at": "original"}]}
    monkeypatch.setattr(web, "_store_get", lambda *a, **kw: (page, "local", None))
    monkeypatch.setattr(web, "_store_save", lambda value, **kw: (value, "local", None))
    monkeypatch.setattr(active_recall, "signed_user", lambda request: hashlib.sha256(b"author@example.com").hexdigest())
    result = web.edit_wiki_comment("page1", "c1", web.WikiCommentEditRequest(body=" changed ", color="blue"), None)["comment"]
    assert result["body"] == "changed" and result["color"] == "blue"
    assert result["parent_id"] == "root" and result["created_at"] == "original"
    assert result["updated_at"]
    monkeypatch.setattr(active_recall, "signed_user", lambda request: "other")
    with pytest.raises(HTTPException) as error:
        web.edit_wiki_comment("page1", "c1", web.WikiCommentEditRequest(body="bad", color="red"), None)
    assert error.value.status_code == 403


def test_comment_color_validation():
    from pydantic import ValidationError
    for color in ("red", "black", "blue"):
        assert web.WikiCommentCreateRequest(body="text", color=color).color == color
    with pytest.raises(ValidationError):
        web.WikiCommentEditRequest(body="text", color="green")


def test_rich_comment_sanitization_and_empty_content():
    from applimit.comment_format import clean_comment
    value = clean_comment('<p><b>Bold</b><span style="color: red; position:fixed" onclick="evil()">red</span><img src=x onerror="evil()"></p>', "html")
    assert '<b>Bold</b>' in value and 'color:red' in value
    assert 'onclick' not in value and 'onerror' not in value and '<img' not in value and 'position' not in value
    assert clean_comment('<div><br></div>', 'html') == ''
    assert clean_comment('<p>&nbsp;</p>', 'html') == ''


def test_create_rich_comment_preserves_format(monkeypatch):
    page = {"id": "page1", "comments": []}
    monkeypatch.setattr(web, "_store_get", lambda *a, **kw: (page, "local", None))
    monkeypatch.setattr(web, "_store_save", lambda value, **kw: (value, "local", None))
    comment = web.create_wiki_comment('page1', web.WikiCommentCreateRequest(body='<b>Hello</b><span style="color:blue">world</span>', content_format='html'))['comment']
    assert comment['content_format'] == 'html'
    assert '<b>Hello</b>' in comment['body'] and 'color:blue' in comment['body']


def test_reply_requires_existing_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"id": "page1", "page_type": "manual", "comments": []}
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (page, "local", None))

    with pytest.raises(HTTPException, match="Parent comment not found"):
        web.create_wiki_comment(
            "page1",
            web.WikiCommentCreateRequest(body="Reply", parent_id="missing"),
        )
