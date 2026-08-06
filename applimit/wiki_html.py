from __future__ import annotations

import os
import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

import bleach

_DEFAULT_HTML_APP_MB = 500
_DEFAULT_HTML_MB = 100
_HEAD_SCAN_BYTES = 512 * 1024
_INLINE_MAX_BYTES = 2 * 1024 * 1024


def max_html_app_bytes() -> int:
    try:
        mb = int(os.environ.get("APPLIMIT_MAX_HTML_APP_MB", str(_DEFAULT_HTML_APP_MB)))
    except ValueError:
        mb = _DEFAULT_HTML_APP_MB
    return max(1, mb) * 1024 * 1024


def max_html_bytes() -> int:
    try:
        mb = int(os.environ.get("APPLIMIT_MAX_HTML_MB", str(_DEFAULT_HTML_MB)))
    except ValueError:
        mb = _DEFAULT_HTML_MB
    return max(1, mb) * 1024 * 1024


def max_html_app_mb() -> int:
    return max(1, max_html_app_bytes() // (1024 * 1024))


def _check_html_extension(filename: str) -> None:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ext and ext not in ("html", "htm", "xhtml"):
        raise ValueError("Upload an .html or .htm file.")


def _size_error(kind: str, max_bytes: int) -> str:
    mb = max(1, max_bytes // (1024 * 1024))
    return f"HTML file too large (max {mb} MB)."
_ALLOWED_TAGS = [
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "caption",
    "code",
    "col",
    "colgroup",
    "dd",
    "del",
    "details",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "iframe",
    "img",
    "ins",
    "kbd",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "q",
    "s",
    "small",
    "source",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
    "var",
    "video",
]

_ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
    "*": ["class", "id", "title", "aria-label", "role"],
    "a": ["href", "rel", "target"],
    "img": ["src", "alt", "width", "height", "loading"],
    "video": ["src", "controls", "preload", "width", "height", "poster"],
    "source": ["src", "type"],
    "iframe": ["src", "width", "height", "allow", "allowfullscreen", "loading", "title"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan", "scope"],
    "col": ["span"],
    "colgroup": ["span"],
    "ol": ["start", "type"],
    "details": ["open"],
}

_EMBED_HOSTS = {
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "m.youtube.com",
    "player.vimeo.com",
    "vimeo.com",
}


def _decode_html_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _strip_tags(text: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _extract_title(html: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if m:
        title = _strip_tags(m.group(1))
        if title:
            return title[:200]
    m = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html)
    if m:
        title = _strip_tags(m.group(1))
        if title:
            return title[:200]
    return ""


def _extract_body_fragment(html: str) -> str:
    raw = html.strip()
    body_m = re.search(r"(?is)<body[^>]*>(.*)</body>", raw)
    if body_m:
        return body_m.group(1).strip()
    cleaned = re.sub(r"(?is)<!DOCTYPE[^>]*>", "", raw)
    cleaned = re.sub(r"(?is)<head[^>]*>.*?</head>", "", cleaned)
    cleaned = re.sub(r"(?is)</?html[^>]*>", "", cleaned)
    return cleaned.strip()


def _is_safe_embed_src(url: str) -> bool:
    try:
        u = urlparse(url.strip())
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    host = u.netloc.lower().split("@")[-1]
    if host.startswith("www."):
        host = host[4:]
    if host in _EMBED_HOSTS:
        return True
    if re.search(r"\.(mp4|webm|ogg)(\?|#|$)", u.path, re.I):
        return True
    return False


def _sanitize_attributes(tag: str, name: str, value: str) -> bool:
    allowed = _ALLOWED_ATTRIBUTES.get(tag, []) + _ALLOWED_ATTRIBUTES.get("*", [])
    if name not in allowed:
        return False
    if name in ("href", "src", "poster"):
        v = (value or "").strip()
        if not v:
            return False
        if v.startswith("#") or v.startswith("/"):
            return True
        if name == "src" and tag == "iframe":
            return _is_safe_embed_src(v)
        try:
            u = urlparse(v)
        except Exception:
            return False
        if u.scheme in ("http", "https", "mailto"):
            return True
        if u.scheme == "" and not v.lower().startswith("javascript:"):
            return True
        return False
    if name == "target" and value not in ("_blank", "_self", "_parent", "_top"):
        return False
    return True


def sanitize_wiki_html(html: str) -> str:
    cleaned = bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_sanitize_attributes,
        protocols=["http", "https", "mailto"],
        strip=True,
    )
    return cleaned.strip()


def html_to_plain_summary(html: str, max_len: int = 160) -> str:
    text = _strip_tags(html)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def parse_html_upload(raw: bytes, filename: str = "") -> dict[str, Any]:
    if not raw:
        raise ValueError("Empty file.")
    limit = max_html_bytes()
    if len(raw) > limit:
        raise ValueError(_size_error("static", limit))

    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ext and ext not in ("html", "htm", "xhtml"):
        raise ValueError("Upload an .html or .htm file.")

    decoded = _decode_html_bytes(raw)
    if not decoded.strip():
        raise ValueError("HTML file is empty.")

    fragment = _extract_body_fragment(decoded)
    if not fragment.strip():
        raise ValueError("No HTML body content found.")

    sanitized = sanitize_wiki_html(fragment)
    if not sanitized.strip():
        raise ValueError("HTML content was removed during sanitization.")

    title = _extract_title(decoded)
    if not title and filename:
        stem = filename.rsplit(".", 1)[0].strip()
        if stem:
            title = stem[:200]

    return {
        "title": title,
        "body_html": sanitized,
        "summary": html_to_plain_summary(sanitized),
        "filename": filename or "upload.html",
    }


def _strip_dangerous_document_tags(html: str) -> str:
    cleaned = re.sub(r"(?is)<base[^>]*>", "", html)
    cleaned = re.sub(r'(?is)<meta[^>]+http-equiv=["\']refresh["\'][^>]*>', "", cleaned)
    return cleaned.strip()


def normalize_html_document(html: str, title: str = "") -> str:
    raw = html.strip()
    if not raw:
        return ""
    if re.search(r"(?is)<html\b", raw):
        return _strip_dangerous_document_tags(raw)
    if re.search(r"(?is)<head\b", raw):
        wrapped = f"<!DOCTYPE html>\n<html>\n{raw}\n</html>"
        return _strip_dangerous_document_tags(wrapped)
    page_title = (title or "Document").strip() or "Document"
    escaped_title = (
        page_title.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    body = _extract_body_fragment(raw) or raw
    wrapped = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        f"<meta charset=\"utf-8\">\n<title>{escaped_title}</title>\n"
        "</head>\n<body>\n"
        f"{body}\n</body>\n</html>"
    )
    return _strip_dangerous_document_tags(wrapped)


def parse_html_app_metadata(
    raw_head: bytes, total_size: int, filename: str = ""
) -> dict[str, Any]:
    """Extract title/summary from the start of a large HTML upload."""
    limit = max_html_app_bytes()
    if total_size <= 0:
        raise ValueError("Empty file.")
    if total_size > limit:
        raise ValueError(_size_error("app", limit))
    _check_html_extension(filename)

    decoded_head = _decode_html_bytes(raw_head)
    if not decoded_head.strip():
        raise ValueError("HTML file is empty.")

    title = _extract_title(decoded_head)
    if not title and filename:
        stem = filename.rsplit(".", 1)[0].strip()
        if stem:
            title = stem[:200]

    if total_size > _INLINE_MAX_BYTES and not re.search(r"(?is)<html\b", decoded_head):
        raise ValueError(
            "Large uploads must be a complete HTML document (include an <html> tag)."
        )

    return {
        "title": title,
        "summary": html_to_plain_summary(decoded_head),
        "filename": filename or "upload.html",
    }


def parse_html_app_upload(raw: bytes, filename: str = "") -> dict[str, Any]:
    """Parse a full interactive HTML upload (MCQ, books, quizzes — scripts allowed)."""
    if not raw:
        raise ValueError("Empty file.")
    limit = max_html_app_bytes()
    if len(raw) > limit:
        raise ValueError(_size_error("app", limit))
    _check_html_extension(filename)

    decoded = _decode_html_bytes(raw)
    if not decoded.strip():
        raise ValueError("HTML file is empty.")

    title = _extract_title(decoded)
    if not title and filename:
        stem = filename.rsplit(".", 1)[0].strip()
        if stem:
            title = stem[:200]

    document = normalize_html_document(decoded, title)
    if not document.strip():
        raise ValueError("Could not build HTML document.")

    return {
        "title": title,
        "document": document,
        "summary": html_to_plain_summary(document),
        "filename": filename or "upload.html",
    }
