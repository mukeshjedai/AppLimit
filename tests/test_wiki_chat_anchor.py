from __future__ import annotations

import pytest
from fastapi import HTTPException

from applimit import web


def test_chat_anchor_updates_selected_text(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"id": "page1", "page_type": "manual", "body_raw": "Read quantum tunnelling today."}
    saved = {}

    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (page, "local", None))

    def fake_save(value, **_kwargs):
        saved.update(value)
        return value, "local", None

    monkeypatch.setattr(web, "_store_save", fake_save)
    result = web.wiki_chat_anchor(
        web.WikiChatAnchorRequest(
            page_id="page1",
            selected_text="quantum tunnelling",
            chat_url="https://chatgpt.com/c/abc123?temporary=1",
        )
    )

    assert result["id"] == "page1"
    assert 'quantum tunnelling[↗](https://chatgpt.com/c/abc123 "Singularity chat")' in saved["body_raw"]


def test_chat_anchor_rejects_non_chatgpt_url(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"id": "page1", "page_type": "manual", "body_raw": "Selected text"}
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (page, "local", None))

    with pytest.raises(HTTPException, match="ChatGPT"):
        web.wiki_chat_anchor(
            web.WikiChatAnchorRequest(
                page_id="page1",
                selected_text="Selected text",
                chat_url="https://example.com/c/abc123",
            )
        )
