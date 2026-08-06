from __future__ import annotations

import pytest

from applimit.wiki_html import (
    html_to_plain_summary,
    max_html_app_bytes,
    parse_html_app_metadata,
    parse_html_app_upload,
    parse_html_upload,
    sanitize_wiki_html,
)


def test_parse_html_extracts_body_and_title():
    raw = b"""<!DOCTYPE html>
<html><head><title>My Doc</title></head>
<body><h1>Hello</h1><p>World <strong>bold</strong></p></body></html>"""
    parsed = parse_html_upload(raw, "doc.html")
    assert parsed["title"] == "My Doc"
    assert "<h1>" in parsed["body_html"]
    assert "Hello" in parsed["body_html"]
    assert "World" in parsed["summary"]


def test_sanitize_strips_script():
    raw = b"<html><body><p>OK</p><script>alert(1)</script></body></html>"
    parsed = parse_html_upload(raw, "x.html")
    assert "script" not in parsed["body_html"].lower()
    assert "OK" in parsed["body_html"]


def test_sanitize_keeps_safe_links_and_images():
    html = '<p><a href="https://example.com">Link</a></p><img src="/api/wiki/images/x.png" alt="pic">'
    cleaned = sanitize_wiki_html(html)
    assert 'href="https://example.com"' in cleaned
    assert 'src="/api/wiki/images/x.png"' in cleaned


def test_html_to_plain_summary():
    assert html_to_plain_summary("<p>One two three</p>") == "One two three"


def test_rejects_non_html_extension():
    with pytest.raises(ValueError, match="html"):
        parse_html_upload(b"<p>x</p>", "notes.txt")


def test_parse_html_app_keeps_document_structure():
    raw = b"""<!DOCTYPE html><html><head><title>Quiz</title></head>
<body><button onclick="alert(1)">Go</button></body></html>"""
    parsed = parse_html_app_upload(raw, "quiz.html")
    assert "Quiz" in parsed["title"]
    assert "onclick" in parsed["document"]
    assert "<button" in parsed["document"]


def test_normalize_html_document_wraps_fragment():
    from applimit.wiki_html import normalize_html_document

    doc = normalize_html_document("<p>Chapter 1</p>", "My Book")
    assert "<html" in doc.lower()
    assert "Chapter 1" in doc


def test_rejects_empty_file():
    with pytest.raises(ValueError, match="Empty"):
        parse_html_upload(b"", "empty.html")


def test_rejects_empty_app_file():
    with pytest.raises(ValueError, match="Empty"):
        parse_html_app_upload(b"", "empty.html")


def test_max_html_app_bytes_env(monkeypatch):
    monkeypatch.setenv("APPLIMIT_MAX_HTML_APP_MB", "750")
    assert max_html_app_bytes() == 750 * 1024 * 1024


def test_parse_html_app_metadata_large_requires_html_tag():
    head = b"<!DOCTYPE html><html><head><title>Big Book</title></head><body>"
    meta = parse_html_app_metadata(head, 50 * 1024 * 1024, "book.html")
    assert meta["title"] == "Big Book"


def test_parse_html_app_metadata_rejects_fragment_when_large():
    head = b"<div>chapter</div>"
    with pytest.raises(ValueError, match="complete HTML"):
        parse_html_app_metadata(head, 5 * 1024 * 1024, "x.html")
