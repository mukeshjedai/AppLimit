from __future__ import annotations

import pytest

from applimit import web


def test_wiki_graph_builds_edges_from_backlinks(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        "a": {"id": "a", "title": "Alpha", "page_type": "manual", "backlinks": []},
        "b": {"id": "b", "title": "Beta", "page_type": "post_notes", "backlinks": [{"source_page_id": "a", "keyword": "Related idea"}]},
    }
    monkeypatch.setattr(web, "_store_search", lambda **_kwargs: (list(pages.values()), "local", None))
    monkeypatch.setattr(web, "_store_get", lambda page_id, **_kwargs: (pages.get(page_id), "local", None))

    result = web.wiki_graph()

    assert [node["title"] for node in result["nodes"]] == ["Alpha", "Beta"]
    assert result["edges"][0]["source"] == "a"
    assert result["edges"][0]["target"] == "b"
    assert result["edges"][0]["label"] == "Related idea"


def test_connect_wiki_graph_pages_updates_both_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        "a": {"id": "a", "title": "Alpha", "page_type": "manual"},
        "b": {"id": "b", "title": "Beta", "page_type": "post_notes"},
    }
    saved: list[dict] = []
    monkeypatch.setattr(web, "_store_get", lambda page_id, **_kwargs: (pages.get(page_id), "local", None))
    monkeypatch.setattr(web, "_store_save", lambda page, **_kwargs: (saved.append(page.copy()) or page, "local", None))

    result = web.connect_wiki_graph_pages(web.WikiGraphConnectionRequest(source_page_id="a", target_page_id="b", label="Explains"))

    assert result["ok"] is True
    assert pages["a"]["graph_links"][0]["target_page_id"] == "b"
    assert pages["b"]["backlinks"][0]["source_page_id"] == "a"
    assert pages["b"]["backlinks"][0]["keyword"] == "Explains"
    assert len(saved) == 2
