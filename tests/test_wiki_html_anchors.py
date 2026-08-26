from __future__ import annotations

import pytest

from applimit import web


def test_static_html_anchor_is_saved_as_page_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"id": "html1", "page_type": "html_app", "html_anchors": []}
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (page, "local", None))
    monkeypatch.setattr(web, "_store_save", lambda value, **_kwargs: (value, "local", None))

    result = web.add_static_html_anchor(
        "html1",
        web.StaticHtmlAnchorRequest(
            source_index=12,
            url="https://example.com/topic#fragment",
            tooltip="  Topic   details  ",
        ),
    )

    assert result["anchor"] == {
        "source_index": 12,
        "url": "https://example.com/topic",
        "tooltip": "Topic details",
    }
    assert page["html_anchors"] == [result["anchor"]]
