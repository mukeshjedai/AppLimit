from __future__ import annotations

import pytest
from fastapi import HTTPException

from applimit import web


def test_link_keyword_to_existing_page_creates_backlink(monkeypatch: pytest.MonkeyPatch) -> None:
    source = {"id": "source", "page_type": "manual", "title": "Source", "body_raw": "Study photon interference."}
    target = {"id": "target", "page_type": "manual", "title": "Photon", "body_raw": "Target"}
    pages = {"source": source, "target": target}
    monkeypatch.setattr(web, "_store_get", lambda page_id, **_kwargs: (pages.get(page_id), "local", None))
    monkeypatch.setattr(web, "_store_save", lambda page, **_kwargs: (page, "local", None))

    result = web.wiki_link_existing(web.WikiLinkExistingRequest(
        source_page_id="source", target_page_id="target", selected_text="photon"
    ))

    assert "[photon](/wiki/target)" in source["body_raw"]
    assert result["keyword"] == "photon"
    assert target["backlinks"][0]["source_page_id"] == "source"


def test_link_keyword_rejects_same_page(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(HTTPException) as error:
        web.wiki_link_existing(web.WikiLinkExistingRequest(
            source_page_id="same", target_page_id="same", selected_text="term"
        ))
    assert error.value.status_code == 400
