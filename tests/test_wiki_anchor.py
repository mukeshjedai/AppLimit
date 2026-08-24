from __future__ import annotations

import pytest

from applimit import web


def test_native_anchor_inserts_at_caret(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"id": "page1", "page_type": "manual", "body_raw": "Alpha beta gamma."}
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (page, "local", None))
    monkeypatch.setattr(web, "_store_save", lambda value, **_kwargs: (value, "local", None))

    web.wiki_anchor(
        web.WikiAnchorRequest(
            page_id="page1",
            context_before="Alpha beta",
            context_after=" gamma.",
            tooltip_text="Alpha beta gamma",
            url="https://example.com/details",
        )
    )

    assert page["body_raw"] == (
        'Alpha beta[↗](https://example.com/details "Alpha beta gamma") gamma.'
    )


def test_native_anchor_normalizes_chatgpt_web_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"id": "page1", "page_type": "manual", "body_raw": "Selected"}
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (page, "local", None))
    monkeypatch.setattr(web, "_store_save", lambda value, **_kwargs: (value, "local", None))

    web.wiki_anchor(
        web.WikiAnchorRequest(
            page_id="page1",
            selected_text="Selected",
            url="https://chatgpt.com/c/WEB:abc-123",
        )
    )

    assert "WEB:" not in page["body_raw"]
    assert "https://chatgpt.com/c/abc-123" in page["body_raw"]
