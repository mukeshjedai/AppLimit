from __future__ import annotations

import html
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import tempfile
import threading
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from applimit.google_auth import (
    auth_middleware,
    build_google_auth_url,
    clear_auth_cookie,
    create_oauth_state,
    exchange_google_code,
    get_session_user,
    is_auth_enabled,
    parse_oauth_state,
    safe_next_path,
    set_auth_cookie,
)
from applimit.util import extract_video_id
from applimit.wiki_store import AzureWikiStore, LocalWikiStore
from applimit.wiki_folders import WikiFolderStore, get_wiki_folder_store
from applimit.wiki_paste import normalize_manual_body, paste_to_display_markdown
from applimit.wiki_files import (
    MAX_WIKI_FILE_BYTES,
    build_attachment_record,
    build_file_markdown_link,
    file_media_type,
    new_file_id,
    page_attachments,
    validate_upload_filename,
    wiki_file_blob_name,
    wiki_file_path,
)
from applimit.wiki_html import (
    max_html_app_bytes,
    max_html_app_mb,
    parse_html_app_metadata,
    parse_html_app_upload,
    parse_html_upload,
    sanitize_wiki_html,
)

log = logging.getLogger(__name__)

app = FastAPI(title="AppLimit - YouTube video translator")
BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.globals["auth_user"] = get_session_user
_static_dir = BASE / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
_extra_cors = os.environ.get("APPLIMIT_CORS_ORIGINS", "").strip()
if _extra_cors:
    _cors_origins.extend(
        o.strip() for o in _extra_cors.split(",") if o.strip()
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(auth_middleware)


@app.on_event("startup")
def _applimit_startup() -> None:
    _ensure_wiki_blob_cors()

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


class JobCreate(BaseModel):
    url: str = Field(..., description="YouTube URL")
    lang: str = Field("hi", description="Target language code (e.g. hi, en, ja)")
    source_lang: str = Field("auto", description="Source language or auto")
    voice: str | None = Field(None, description="Optional Edge TTS voice id")


class InsightRequest(BaseModel):
    url: str = Field(..., description="YouTube URL")
    custom_demand: str | None = Field(
        None, description="Optional custom AI request for the transcript"
    )


class WikiSaveRequest(BaseModel):
    url: str = Field(..., description="YouTube URL")
    insights: dict[str, Any] = Field(..., description="AI insights payload")
    title: str | None = Field(None, description="Optional wiki page title")
    folder_id: str | None = Field(None, description="Folder to add a link when creating")
    auto_fallback_local: bool = Field(
        True, description="If Azure write fails, persist in local store."
    )


class FlashcardRequest(BaseModel):
    url: str = Field(..., description="YouTube URL")
    insights: dict[str, Any] | None = Field(
        None, description="Optional precomputed insights payload"
    )
    custom_demand: str | None = Field(
        None, description="Optional custom AI request when building insights"
    )


class ManualWikiPreviewRequest(BaseModel):
    body: str = Field("", description="Raw pasted notes")


class ManualWikiSaveRequest(BaseModel):
    title: str = Field("", description="Wiki page title")
    body: str = Field(..., description="Raw pasted content")
    page_id: str | None = Field(
        None, description="If set, update this existing manual wiki page"
    )
    folder_id: str | None = Field(None, description="Folder to add a link when creating")
    attachments: list[dict[str, Any]] | None = Field(
        None, description="Optional file attachment metadata to merge on save"
    )
    auto_fallback_local: bool = Field(
        True, description="If Azure write fails, persist in local store."
    )


class PostNotesSaveRequest(BaseModel):
    title: str = Field("", description="Wiki page title")
    body: str = Field(..., description="Markdown content")
    page_id: str | None = Field(
        None, description="If set, update this existing post notes page"
    )
    folder_id: str | None = Field(None, description="Folder to add a link when creating")
    auto_fallback_local: bool = Field(
        True, description="If Azure write fails, persist in local store."
    )


class WikiFolderCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    parent_id: str | None = Field(None, description="Parent folder id for subfolders")


class WikiFolderLinkCreateRequest(BaseModel):
    folder_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=120)
    url: str = Field(..., min_length=1, max_length=2048)
    wiki_page_id: str | None = Field(None, description="Optional linked wiki page id")


class WikiFolderFileCreateRequest(BaseModel):
    folder_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=120)
    page_type: str = Field(
        "post_notes",
        description="Wiki page type: post_notes or manual (paste notes)",
    )


class HtmlWikiSaveRequest(BaseModel):
    title: str = Field("", description="Wiki page title")
    body_html: str = Field(..., description="Sanitized HTML body content")
    filename: str | None = Field(None, description="Original uploaded filename")
    page_id: str | None = Field(
        None, description="If set, update this existing HTML wiki page"
    )
    folder_id: str | None = Field(None, description="Folder to add a link when creating")
    auto_fallback_local: bool = Field(
        True, description="If Azure write fails, persist in local store."
    )


class HtmlAppPrepareUploadRequest(BaseModel):
    filename: str = Field(..., description="Original filename")
    file_size: int = Field(..., ge=1, description="File size in bytes")
    title: str = Field("", description="Page title")
    kind: str = Field("general", description="book, mcq, or general")
    page_id: str | None = Field(None, description="Existing page id when replacing")


class HtmlAppFinalizeRequest(BaseModel):
    page_id: str = Field(..., description="Page id from prepare-upload")
    title: str = Field("", description="Page title")
    kind: str = Field("general", description="book, mcq, or general")
    filename: str = Field("upload.html", description="Original filename")
    folder_id: str | None = Field(None, description="Folder to add a link when creating")
    auto_fallback_local: bool = Field(True)


class HtmlAppUpdateDocumentRequest(BaseModel):
    html: str = Field(..., min_length=1, description="Full HTML document after inline edits")


class StaticHtmlAnchorRequest(BaseModel):
    source_index: int = Field(..., ge=0)
    url: str = Field(..., min_length=1, max_length=2048)
    tooltip: str = Field("", max_length=500)


class WikiCommentCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10000)
    parent_id: str | None = Field(None, max_length=64)
    author_name: str = Field("Anonymous", max_length=200)
    author_email: str = Field("", max_length=320)
    author_picture: str = Field("", max_length=2048)


class WikiNoteCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    body: str = Field(..., min_length=1, max_length=50000)
    author_name: str = Field("Anonymous", max_length=200)
    author_email: str = Field("", max_length=320)


class ExamCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    questions: list[dict[str, Any]] = Field(..., min_length=1, max_length=5000)
    source_filename: str = Field("", max_length=260)


class ExamAnswerRequest(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=64)
    answer: str = Field(..., min_length=1, max_length=1)
    user_email: str = Field(..., min_length=1, max_length=320)
    user_name: str = Field("", max_length=200)


class ExamStatusRequest(BaseModel):
    user_email: str = Field(..., min_length=1, max_length=320)
    user_name: str = Field("", max_length=200)
    current_index: int = Field(0, ge=0)


class ReadAloudRequest(BaseModel):
    text: str = Field(..., description="Plain text to read aloud")
    repeats: int = Field(
        1,
        ge=1,
        le=10000,
        description="Ignored server-side; the browser replays the same audio this many times.",
    )
    lang: str = Field(
        "en",
        description="Language hint for default Edge voice (e.g. en, hi, ja)",
    )
    voice: str | None = Field(
        None,
        description="Optional Edge TTS voice id (overrides lang default)",
    )


class WikiSectionReadTapBody(BaseModel):
    section_key: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Section index key from the rendered page (string digits).",
    )

    @field_validator("section_key")
    @classmethod
    def strip_section_key(cls, v: str) -> str:
        return v.strip()


class WikiLinkFromSelectionRequest(BaseModel):
    parent_id: str = Field(..., description="Wiki page to insert the link into")
    selected_text: str = Field(..., description="Exact substring from markdown body or transcript")
    new_title: str = Field(..., description="Title for the new page")
    source: Literal["manual", "transcript"] = Field(
        "manual",
        description="manual = notes body_raw; transcript = video transcript field",
    )
    new_body: str = Field("", description="Optional markdown body for the new page")
    auto_fallback_local: bool = Field(
        True, description="If Azure write fails, persist in local store."
    )


class FlashcardDeckCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    cards: list[dict[str, Any]] = Field(..., min_length=1, max_length=5000)
    source_filename: str = Field("", max_length=260)


class FlashcardDeckStatusRequest(BaseModel):
    user_email: str = Field(..., min_length=1, max_length=320)
    user_name: str = Field("", max_length=200)
    current_index: int = Field(0, ge=0)
    seen_card_ids: list[str] = Field(default_factory=list, max_length=5000)
    mastered_card_ids: list[str] = Field(default_factory=list, max_length=5000)


class WikiLinkExistingRequest(BaseModel):
    source_page_id: str = Field(..., min_length=1, max_length=64)
    target_page_id: str = Field(..., min_length=1, max_length=64)
    selected_text: str = Field(..., min_length=1, max_length=2000)


class WikiAnchorRequest(BaseModel):
    page_id: str
    selected_text: str = ""
    context_before: str = Field("", max_length=500)
    context_after: str = Field("", max_length=500)
    caret_ratio: float | None = Field(None, ge=0, le=1)
    tooltip_text: str = Field("", max_length=500)
    url: str
    auto_fallback_local: bool = True


class WikiTagsUpdateRequest(BaseModel):
    tags: list[str] = Field(default_factory=list, description="Wiki page tags")


def _normalize_tags(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        tag = re.sub(r"\s+", " ", str(item or "").strip().lower())
        if not tag or len(tag) > 48:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= 32:
            break
    return out


def _normalize_tag_filter(raw: str) -> str:
    tags = _normalize_tags([raw] if raw else [])
    return tags[0] if tags else ""


_EMPTY_WIKI_FIELDS: dict[str, Any] = {
    "transcript": "",
    "terminologies": [],
    "important_points": [],
    "concepts": [],
    "questions_and_definitions": [],
    "custom_response": "",
    "segment_count": 0,
    "video_id": "",
    "source_url": "",
    "embed_url": "",
}


def _md_inline_token_pattern(word: str) -> str:
    """Regex for one visible word: plain text or common Markdown / TeX wrappers (same text when rendered)."""
    e = re.escape(word)
    # Plain word must not match inside `` `...` `` (otherwise we'd capture only the inner letters).
    plain = rf"(?<!\x60){e}(?!\x60)"
    return (
        rf"(?:\${e}\$|`{e}`|\*\*\*{e}\*\*\*|\*\*{e}\*\*|\*{e}\*|__{e}__|_{e}_|{plain})"
    )


def _pick_selection_segment(haystack: str, user_sel: str) -> str | None:
    """Resolve selected text to a substring of haystack (exact or flexible whitespace).

    Browser selection is plain text from rendered HTML; ``body_raw`` may use Markdown
    emphasis (e.g. *x*) where the user sees ``x``. After literal and whitespace-flexible
    matching, we try word-by-word patterns that allow optional inline md around each word.
    """
    if not user_sel or not haystack:
        return None
    candidates: list[str] = []
    for c in (user_sel, user_sel.strip()):
        if c and c not in candidates:
            candidates.append(c)
    collapsed = re.sub(r"\s+", " ", user_sel).strip()
    if collapsed and collapsed not in candidates:
        candidates.append(collapsed)
    for c in candidates:
        if c in haystack:
            return c
    words = [w for w in re.split(r"\s+", user_sel.strip()) if w]
    if not words:
        return None
    pat = r"\s*".join(re.escape(w) for w in words)
    m = re.search(pat, haystack, re.DOTALL)
    if m:
        return m.group(0)
    # Plain words in selection vs *word* / **word** / `word` in saved markdown
    pat_md = r"\s+".join(_md_inline_token_pattern(w) for w in words)
    m2 = re.search(pat_md, haystack, re.DOTALL)
    if m2:
        return m2.group(0)
    return None


def _md_link_label(text: str, fallback: str) -> str:
    t = "".join(c for c in text.strip() if c not in "[]\r\n\t")
    if len(t) < 1:
        t = (
            "".join(c for c in fallback.strip() if c not in "[]\r\n")[:80] or "page"
        )
    return t[:800]


def _render_transcript_with_links(transcript: str, links: list[dict[str, Any]]) -> str:
    out = html.escape(transcript or "")
    for L in links:
        sn = str(L.get("snippet") or "")
        wid = str(L.get("wiki_id") or "").strip()
        if not sn or not wid:
            continue
        ess = html.escape(sn)
        if ess not in out:
            continue
        href = f"/wiki/{html.escape(wid)}"
        rep = f'<a class="wiki-inline-link" href="{href}">{ess}</a>'
        out = out.replace(ess, rep, 1)
    return out


def _wiki_storage_note(backend: str) -> str:
    local_dir = (
        os.environ.get("APPLIMIT_LOCAL_WIKI_DIR", "").strip()
        or str(Path.cwd() / "wiki-data")
    )
    if backend == "azure":
        return (
            "Pages are stored in Azure Blob. Use the same "
            "APPLIMIT_AZURE_STORAGE_CONNECTION_STRING (or account + credentials) "
            "in every environment to see one shared list."
        )
    return (
        f"Pages are stored as JSON under: {local_dir}. "
        "Another host (or Azure) shows a different list unless both use the same Azure Blob settings."
    )


def _wiki_audio_dir() -> Path:
    root = Path.cwd() / "wiki-audio"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _wiki_audio_path(page_id: str) -> Path:
    return _wiki_audio_dir() / f"{page_id}_hi.mp3"


def _wiki_image_dir() -> Path:
    root = Path.cwd() / "wiki-images"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _wiki_image_path(image_name: str) -> Path:
    clean = Path(image_name).name
    if clean != image_name or not clean:
        raise HTTPException(status_code=404, detail="Image not found")
    return _wiki_image_dir() / clean


def _wiki_image_blob_name(image_name: str) -> str:
    clean = Path(image_name).name
    if clean != image_name or not clean:
        raise HTTPException(status_code=404, detail="Image not found")
    return f"images/{clean}"


def _image_media_type(image_name: str) -> str:
    return mimetypes.guess_type(image_name)[0] or "application/octet-stream"


def _upload_wiki_image_blob(image_name: str, raw: bytes) -> bool:
    try:
        store = AzureWikiStore()
        cc = store._container_client()
        bc = cc.get_blob_client(_wiki_image_blob_name(image_name))
        bc.upload_blob(
            raw,
            overwrite=True,
            content_type=_image_media_type(image_name),
        )
        return True
    except Exception:
        return False


def _download_wiki_image_blob(image_name: str) -> tuple[bytes, str] | None:
    try:
        store = AzureWikiStore()
        cc = store._container_client()
        bc = cc.get_blob_client(_wiki_image_blob_name(image_name))
        raw = bc.download_blob().readall()
        props = bc.get_blob_properties()
        media_type = (
            getattr(getattr(props, "content_settings", None), "content_type", None)
            or _image_media_type(image_name)
        )
        return raw, media_type
    except Exception:
        return None


def _wiki_video_dir() -> Path:
    root = Path.cwd() / "wiki-videos"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _wiki_video_path(video_name: str) -> Path:
    clean = Path(video_name).name
    if clean != video_name or not clean:
        raise HTTPException(status_code=404, detail="Video not found")
    return _wiki_video_dir() / clean


def _wiki_video_blob_name(video_name: str) -> str:
    clean = Path(video_name).name
    if clean != video_name or not clean:
        raise HTTPException(status_code=404, detail="Video not found")
    return f"videos/{clean}"


def _video_media_type(video_name: str) -> str:
    return mimetypes.guess_type(video_name)[0] or "application/octet-stream"


def _upload_wiki_video_blob(video_name: str, raw: bytes) -> bool:
    try:
        store = AzureWikiStore()
        cc = store._container_client()
        bc = cc.get_blob_client(_wiki_video_blob_name(video_name))
        bc.upload_blob(
            raw,
            overwrite=True,
            content_type=_video_media_type(video_name),
        )
        return True
    except Exception:
        return False


def _download_wiki_video_blob(video_name: str) -> tuple[bytes, str] | None:
    try:
        store = AzureWikiStore()
        cc = store._container_client()
        bc = cc.get_blob_client(_wiki_video_blob_name(video_name))
        raw = bc.download_blob().readall()
        props = bc.get_blob_properties()
        media_type = (
            getattr(getattr(props, "content_settings", None), "content_type", None)
            or _video_media_type(video_name)
        )
        return raw, media_type
    except Exception:
        return None


def _upload_wiki_file_blob(file_id: str, raw: bytes, content_type: str) -> bool:
    try:
        store = AzureWikiStore()
        cc = store._container_client()
        bc = cc.get_blob_client(wiki_file_blob_name(file_id))
        bc.upload_blob(
            raw,
            overwrite=True,
            content_type=content_type,
        )
        return True
    except Exception:
        return False


def _download_wiki_file_blob(file_id: str) -> tuple[bytes, str] | None:
    try:
        store = AzureWikiStore()
        cc = store._container_client()
        bc = cc.get_blob_client(wiki_file_blob_name(file_id))
        raw = bc.download_blob().readall()
        props = bc.get_blob_properties()
        media_type = (
            getattr(getattr(props, "content_settings", None), "content_type", None)
            or file_media_type(file_id)
        )
        return raw, media_type
    except Exception:
        return None


def _persist_wiki_file_bytes(file_id: str, raw: bytes) -> None:
    if not _upload_wiki_file_blob(file_id, raw, file_media_type(file_id)):
        wiki_file_path(file_id).write_bytes(raw)


def _merge_attachments(
    existing: list[dict[str, Any]] | None,
    incoming: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in existing or []:
        if isinstance(item, dict) and item.get("id"):
            merged[str(item["id"])] = item
    for item in incoming or []:
        if isinstance(item, dict) and item.get("id"):
            merged[str(item["id"])] = item
    return list(merged.values())


def _append_page_attachment(page: dict[str, Any], attachment: dict[str, Any]) -> dict[str, Any]:
    current = page_attachments(page)
    return _merge_attachments(current, [attachment])


def _wiki_html_app_dir() -> Path:
    root = Path.cwd() / "wiki-html-apps"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _wiki_html_app_path(page_id: str) -> Path:
    clean = page_id.strip()
    if not clean or not re.fullmatch(r"[a-zA-Z0-9_-]+", clean):
        raise HTTPException(status_code=404, detail="HTML app not found")
    return _wiki_html_app_dir() / f"{clean}.html"


def _wiki_html_app_blob_name(page_id: str) -> str:
    clean = page_id.strip()
    if not clean or not re.fullmatch(r"[a-zA-Z0-9_-]+", clean):
        raise HTTPException(status_code=404, detail="HTML app not found")
    return f"html-apps/{clean}.html"


def _upload_wiki_html_app_blob(page_id: str, raw: bytes) -> bool:
    try:
        store = AzureWikiStore()
        cc = store._container_client()
        bc = cc.get_blob_client(_wiki_html_app_blob_name(page_id))
        bc.upload_blob(
            raw,
            overwrite=True,
            content_type="text/html; charset=utf-8",
        )
        return True
    except Exception:
        return False


def _download_wiki_html_app_blob(page_id: str) -> bytes | None:
    try:
        store = AzureWikiStore()
        cc = store._container_client()
        bc = cc.get_blob_client(_wiki_html_app_blob_name(page_id))
        return bc.download_blob().readall()
    except Exception:
        return None


def _read_wiki_html_app_document(page_id: str) -> bytes:
    blob = _download_wiki_html_app_blob(page_id)
    if blob is not None:
        return blob
    p = _wiki_html_app_path(page_id)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="HTML document not found")
    return p.read_bytes()


def _read_html_app_blob_head(page_id: str, max_head: int = 512 * 1024) -> tuple[bytes, int]:
    try:
        store = AzureWikiStore()
        cc = store._container_client()
        bc = cc.get_blob_client(_wiki_html_app_blob_name(page_id))
        props = bc.get_blob_properties()
        size = int(getattr(props, "size", 0) or 0)
        if size <= 0:
            raise ValueError("empty blob")
        length = min(size, max_head)
        head = bc.download_blob(offset=0, length=length).readall()
        return head, size
    except Exception:
        pass
    p = _wiki_html_app_path(page_id)
    if not p.is_file():
        raise HTTPException(
            status_code=400,
            detail="Upload not found. Complete the file upload first.",
        )
    size = p.stat().st_size
    with p.open("rb") as fh:
        head = fh.read(min(size, max_head))
    return head, size


def _write_wiki_html_app_document(page_id: str, raw: bytes) -> None:
    if not _upload_wiki_html_app_blob(page_id, raw):
        _wiki_html_app_path(page_id).write_bytes(raw)


def _write_wiki_html_app_document_from_path(page_id: str, src: Path) -> None:
    if _upload_wiki_html_app_blob_from_path(page_id, src):
        return
    dest = _wiki_html_app_path(page_id)
    shutil.copyfile(src, dest)


def _upload_wiki_html_app_blob_from_path(page_id: str, src: Path) -> bool:
    try:
        store = AzureWikiStore()
        cc = store._container_client()
        bc = cc.get_blob_client(_wiki_html_app_blob_name(page_id))
        with src.open("rb") as fh:
            bc.upload_blob(
                fh,
                overwrite=True,
                content_type="text/html; charset=utf-8",
            )
        return True
    except Exception:
        return False


def _wiki_blob_container_name() -> str:
    return (
        os.environ.get("APPLIMIT_AZURE_WIKI_CONTAINER", "applimit-wiki").strip()
        or "applimit-wiki"
    )


def _wiki_cors_origins() -> list[str]:
    origins = ["http://localhost:7071", "http://127.0.0.1:7071"]
    site = os.environ.get("WEBSITE_HOSTNAME", "").strip()
    if site:
        origins.append(f"https://{site}")
    extra = os.environ.get("APPLIMIT_CORS_ORIGINS", "").strip()
    if extra:
        origins.extend(part.strip() for part in extra.split(",") if part.strip())
    return list(dict.fromkeys(origins))


def _ensure_wiki_blob_cors() -> None:
    conn = (
        os.environ.get("APPLIMIT_AZURE_STORAGE_CONNECTION_STRING")
        or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        or ""
    ).strip()
    if not conn:
        return
    try:
        from azure.storage.blob import BlobServiceClient, CorsRule

        origins = _wiki_cors_origins()
        rule = CorsRule(
            allowed_origins=origins,
            allowed_methods=["GET", "HEAD", "PUT", "OPTIONS"],
            allowed_headers=["*"],
            exposed_headers=["*"],
            max_age_in_seconds=3600,
        )
        service = BlobServiceClient.from_connection_string(conn)
        service.set_service_properties(cors=[rule])
        log.info("Configured blob CORS for origins: %s", ", ".join(origins))
    except Exception:
        log.exception("Could not configure blob storage CORS")


def _create_blob_upload_sas(blob_name: str, minutes: int = 120) -> str | None:
    conn = (
        os.environ.get("APPLIMIT_AZURE_STORAGE_CONNECTION_STRING")
        or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        or ""
    ).strip()
    if not conn:
        return None
    try:
        from datetime import timedelta

        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        account_name = ""
        account_key = ""
        for part in conn.split(";"):
            if part.startswith("AccountName="):
                account_name = part.split("=", 1)[1]
            elif part.startswith("AccountKey="):
                account_key = part.split("=", 1)[1]
        if not account_name or not account_key:
            return None
        container = _wiki_blob_container_name()
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=container,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(create=True, write=True),
            expiry=datetime.now(tz=timezone.utc) + timedelta(minutes=minutes),
        )
        return (
            f"https://{account_name}.blob.core.windows.net/"
            f"{container}/{blob_name}?{sas}"
        )
    except Exception:
        log.exception("Could not create blob upload SAS")
        return None


def _html_app_kind(kind: str) -> str:
    html_kind = kind.strip().lower()
    if html_kind not in ("book", "mcq", "general"):
        return "general"
    return html_kind


async def _stream_upload_to_temp(
    upload: UploadFile, max_bytes: int
) -> tuple[Path, int]:
    suffix = Path(upload.filename or "upload.html").suffix or ".html"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    path = Path(tmp.name)
    total = 0
    try:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"HTML file too large (max {max_bytes // (1024 * 1024)} MB).",
                )
            tmp.write(chunk)
    finally:
        tmp.close()
    if total <= 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty file.")
    return path, total


def _save_html_app_page(
    *,
    pid: str,
    page_title: str,
    filename: str,
    html_kind: str,
    summary: str,
    existing: dict[str, Any] | None,
    auto_fallback_local: bool,
    folder_id: str | None = None,
) -> dict[str, Any]:
    if existing:
        page: dict[str, Any] = {
            **existing,
            **_EMPTY_WIKI_FIELDS,
            "page_type": "html_app",
            "title": page_title,
            "body_raw": summary,
            "html_filename": filename,
            "html_kind": html_kind,
            "id": pid,
            "created_at": existing.get("created_at") or _utc_now_iso(),
            "updated_at": _utc_now_iso(),
        }
    else:
        page = {
            **_EMPTY_WIKI_FIELDS,
            "page_type": "html_app",
            "title": page_title,
            "body_raw": summary,
            "html_filename": filename,
            "html_kind": html_kind,
            "id": pid,
            "updated_at": _utc_now_iso(),
        }
    try:
        saved, backend, warn = _store_save(page, allow_local=bool(auto_fallback_local))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    folder_warn = _maybe_link_page_to_folder(
        folder_id, saved["id"], page_title, is_new=existing is None
    )
    if folder_warn:
        warn = f"{warn}; {folder_warn}" if warn else folder_warn
    return {
        "id": saved["id"],
        "url": f"/wiki/{saved['id']}",
        "backend": backend,
        "warning": warn,
    }


def _wiki_uploaded_translated_glob(page_id: str) -> list[Path]:
    return list(_wiki_audio_dir().glob(f"{page_id}_translated_upload.*"))


def _wiki_uploaded_translated_path(page_id: str) -> Path | None:
    g = _wiki_uploaded_translated_glob(page_id)
    if not g:
        return None
    return max(g, key=lambda p: p.stat().st_mtime)


def _get_store_with_fallback(allow_local: bool = True):
    try:
        return AzureWikiStore(), "azure", ""
    except Exception as e:
        if allow_local:
            return LocalWikiStore(), "local", str(e)
        raise


def _store_save(page: dict[str, Any], allow_local: bool = True):
    store, backend, warn = _get_store_with_fallback(allow_local=allow_local)
    try:
        saved = store.save_page(page)
        return saved, backend, warn
    except Exception as e:
        if allow_local and backend == "azure":
            local = LocalWikiStore()
            saved = local.save_page(page)
            return (
                saved,
                "local",
                f"Azure save failed ({e}). Fell back to local persistent store.",
            )
        raise


def _store_search(query: str, limit: int, allow_local: bool = True, tag: str = ""):
    tag_filter = _normalize_tag_filter(tag)
    store, backend, warn = _get_store_with_fallback(allow_local=allow_local)
    try:
        return store.search(query=query, limit=limit, tag=tag_filter), backend, warn
    except Exception as e:
        if allow_local and backend == "azure":
            local = LocalWikiStore()
            return (
                local.search(query=query, limit=limit, tag=tag_filter),
                "local",
                f"Azure search failed ({e}). Showing local pages.",
            )
        raise


def _store_list_tags(prefix: str, limit: int, allow_local: bool = True):
    store, backend, warn = _get_store_with_fallback(allow_local=allow_local)
    pref = _normalize_tag_filter(prefix)
    try:
        return store.list_tags(prefix=pref, limit=limit), backend, warn
    except Exception as e:
        if allow_local and backend == "azure":
            local = LocalWikiStore()
            return (
                local.list_tags(prefix=pref, limit=limit),
                "local",
                f"Azure tag list failed ({e}). Showing local tags.",
            )
        raise


def _store_get(page_id: str, allow_local: bool = True):
    store, backend, warn = _get_store_with_fallback(allow_local=allow_local)
    try:
        page = store.get_page(page_id)
        if page is None and allow_local and backend == "azure":
            local = LocalWikiStore()
            fallback = local.get_page(page_id)
            if fallback is not None:
                return (
                    fallback,
                    "local",
                    "Page not found in Azure; loaded from local persistent store.",
                )
        return page, backend, warn
    except Exception as e:
        if allow_local and backend == "azure":
            local = LocalWikiStore()
            return (
                local.get_page(page_id),
                "local",
                f"Azure read failed ({e}). Read from local store.",
            )
        raise


def _folder_store_with_fallback(allow_local: bool = True) -> tuple[WikiFolderStore, str, str | None]:
    warn: str | None = None
    try:
        store, backend = get_wiki_folder_store(allow_local=False)
        return store, backend, warn
    except Exception as e:
        if not allow_local:
            raise
        store, backend = get_wiki_folder_store(allow_local=True)
        return store, backend, f"Azure folder store unavailable ({e}). Using local folders."


def _maybe_link_page_to_folder(
    folder_id: str | None,
    page_id: str,
    title: str,
    *,
    is_new: bool,
) -> str | None:
    fid = (folder_id or "").strip()
    if not fid or not is_new:
        return None
    try:
        store, _, _ = _folder_store_with_fallback(allow_local=True)
        store.create_link(fid, title or "Untitled", f"/wiki/{page_id}", page_id)
    except Exception as e:
        return f"Page saved but folder link failed: {e}"
    return None


def _run_job(job_id: str, url: str, lang: str, source_lang: str, voice: str | None) -> None:
    from applimit.pipeline import run

    out = Path.cwd() / "web_out" / job_id
    out.mkdir(parents=True, exist_ok=True)
    try:
        with _lock:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["stage"] = "start"

        def on_progress(
            stage: str, phase: float, overall: float, detail: str
        ) -> None:
            with _lock:
                if job_id in _jobs:
                    _jobs[job_id]["stage"] = stage
                    _jobs[job_id]["phase_progress"] = phase
                    _jobs[job_id]["progress"] = overall
                    _jobs[job_id]["detail"] = detail

        res = run(
            url,
            output_dir=out,
            target_lang=lang,
            source_lang=source_lang,
            voice=voice,
            on_progress=on_progress,
        )
        with _lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["video"] = str(res.video_out)
            _jobs[job_id]["srt"] = str(res.subtitles_srt)
            _jobs[job_id]["audio"] = str(res.audio_out)
            _jobs[job_id]["stage"] = "complete"
            _jobs[job_id]["progress"] = 1.0
    except Exception as e:
        log.exception("Job failed")
        with _lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)


@app.get("/login")
def login_page(request: Request, next: str = "/") -> Response:
    if get_session_user(request):
        return RedirectResponse(url=safe_next_path(next), status_code=307)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "title": "Sign in to AppLimit",
            "next_path": safe_next_path(next),
            "next_encoded": urllib.parse.quote(safe_next_path(next), safe=""),
            "error": request.query_params.get("error"),
        },
    )


@app.get("/sign-in")
def sign_in_alias(next: str = "/") -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={urllib.parse.quote(safe_next_path(next))}", status_code=307)


@app.get("/auth/google")
def auth_google_start(request: Request, next: str = "/") -> RedirectResponse:
    if not is_auth_enabled():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured.")
    state = create_oauth_state(next)
    return RedirectResponse(url=build_google_auth_url(request, state), status_code=307)


@app.get("/auth/google/callback")
def auth_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        return RedirectResponse(url=f"/login?error={urllib.parse.quote(error)}", status_code=307)
    if not code or not state:
        return RedirectResponse(url="/login?error=missing_code", status_code=307)
    ok, next_path = parse_oauth_state(state)
    if not ok:
        return RedirectResponse(url="/login?error=invalid_state", status_code=307)
    user = exchange_google_code(request, code)
    response = RedirectResponse(url=next_path, status_code=307)
    set_auth_cookie(response, user)
    return response


@app.get("/auth/logout")
def auth_logout(request: Request, next: str = "/login") -> RedirectResponse:
    response = RedirectResponse(url=safe_next_path(next), status_code=307)
    clear_auth_cookie(response)
    return response


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"title": "Translate YouTube videos"},
    )


@app.get("/insights", response_class=HTMLResponse)
def insights_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "insights.html",
        {"title": "YouTube Transcript Insights"},
    )


@app.get("/flashcards", response_class=HTMLResponse)
def flashcards_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "flashcards.html",
        {"title": "AI Flashcards"},
    )


@app.get("/wiki", response_class=HTMLResponse)
def wiki_index(request: Request, q: str = "") -> HTMLResponse:
    folder_warn: str | None = None
    try:
        results, backend, warn = _store_search(query=q, limit=50, allow_local=True)
        err = warn
    except Exception as e:
        results = []
        backend = "none"
        err = str(e)
    try:
        _, _fb, folder_warn = _folder_store_with_fallback(allow_local=True)
    except Exception as e:
        if not err:
            err = str(e)
    return templates.TemplateResponse(
        request,
        "wiki_index.html",
        {
            "title": "Video Wiki",
            "query": q,
            "results": results,
            "error": err,
            "folder_warn": folder_warn,
            "backend": backend,
            "storage_note": _wiki_storage_note(backend),
        },
    )


@app.get("/api/wiki/folders/tree")
def wiki_folders_tree() -> dict[str, Any]:
    store, backend, warn = _folder_store_with_fallback(allow_local=True)
    return {"tree": store.build_tree(), "backend": backend, "warning": warn}


@app.get("/api/wiki/folders/flat")
def wiki_folders_flat() -> dict[str, Any]:
    store, backend, warn = _folder_store_with_fallback(allow_local=True)
    return {"folders": store.list_flat(), "backend": backend, "warning": warn}


@app.post("/api/wiki/folders")
def wiki_folder_create(body: WikiFolderCreateRequest) -> dict[str, Any]:
    store, backend, warn = _folder_store_with_fallback(allow_local=True)
    try:
        folder = store.create_folder(body.name, body.parent_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"folder": folder, "backend": backend, "warning": warn}


@app.post("/api/wiki/folders/links")
def wiki_folder_link_create(body: WikiFolderLinkCreateRequest) -> dict[str, Any]:
    store, backend, warn = _folder_store_with_fallback(allow_local=True)
    url = body.url.strip()
    wiki_page_id = body.wiki_page_id
    if wiki_page_id and not url.startswith("/wiki/"):
        url = f"/wiki/{wiki_page_id.strip()}"
    try:
        link = store.create_link(body.folder_id, body.title, url, wiki_page_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"link": link, "backend": backend, "warning": warn}


@app.post("/api/wiki/folders/files")
def wiki_folder_create_file(body: WikiFolderFileCreateRequest) -> dict[str, Any]:
    page_type = (body.page_type or "post_notes").strip()
    if page_type not in ("post_notes", "manual"):
        raise HTTPException(
            status_code=400,
            detail="page_type must be post_notes or manual.",
        )
    title = (body.title or "").strip() or "Untitled"
    page: dict[str, Any] = {
        **_EMPTY_WIKI_FIELDS,
        "page_type": page_type,
        "title": title,
        "body_raw": "",
        "updated_at": _utc_now_iso(),
    }
    try:
        saved, backend, warn = _store_save(page, allow_local=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    fstore, _, fw = _folder_store_with_fallback(allow_local=True)
    try:
        link = fstore.create_link(
            body.folder_id,
            title,
            f"/wiki/{saved['id']}",
            saved["id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if fw:
        warn = f"{warn}; {fw}" if warn else fw
    edit_url = (
        f"/wiki/post-notes?edit={saved['id']}"
        if page_type == "post_notes"
        else f"/wiki/paste?edit={saved['id']}"
    )
    return {
        "id": saved["id"],
        "url": f"/wiki/{saved['id']}",
        "edit_url": edit_url,
        "link": link,
        "backend": backend,
        "warning": warn,
    }


@app.delete("/api/wiki/folders/{folder_id}")
def wiki_folder_delete(folder_id: str) -> dict[str, Any]:
    store, backend, warn = _folder_store_with_fallback(allow_local=True)
    try:
        store.delete_folder(folder_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "backend": backend, "warning": warn}


@app.delete("/api/wiki/folders/links/{link_id}")
def wiki_folder_link_delete(link_id: str) -> dict[str, Any]:
    store, backend, warn = _folder_store_with_fallback(allow_local=True)
    try:
        store.delete_link(link_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "backend": backend, "warning": warn}


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@app.get("/wiki/paste", response_class=HTMLResponse)
def wiki_paste_editor(request: Request, edit: str | None = None) -> HTMLResponse:
    initial_title = ""
    initial_body = ""
    editing_id: str | None = None
    if edit:
        page, _, _ = _store_get(edit.strip(), allow_local=True)
        if not page or page.get("page_type") != "manual":
            raise HTTPException(
                status_code=404,
                detail="Manual wiki page not found for editing.",
            )
        initial_title = str(page.get("title", ""))
        initial_body = str(page.get("body_raw", ""))
        editing_id = str(page.get("id", ""))
    return templates.TemplateResponse(
        request,
        "wiki_paste.html",
        {
            "title": "Paste notes to wiki",
            "initial_title": initial_title,
            "initial_body": initial_body,
            "editing_id": editing_id,
        },
    )


@app.get("/wiki/post-notes", response_class=HTMLResponse)
def wiki_post_notes_editor(request: Request, edit: str | None = None) -> HTMLResponse:
    initial_title = ""
    initial_body = ""
    editing_id: str | None = None
    if edit:
        page, _, _ = _store_get(edit.strip(), allow_local=True)
        if not page or page.get("page_type") != "post_notes":
            raise HTTPException(
                status_code=404,
                detail="Post notes wiki page not found for editing.",
            )
        initial_title = str(page.get("title", ""))
        initial_body = str(page.get("body_raw", ""))
        editing_id = str(page.get("id", ""))
    return templates.TemplateResponse(
        request,
        "wiki_post_notes.html",
        {
            "title": "Post notes",
            "initial_title": initial_title,
            "initial_body": initial_body,
            "editing_id": editing_id,
        },
    )


@app.get("/wiki/upload-html", response_class=HTMLResponse)
def wiki_upload_html_editor(request: Request, edit: str | None = None) -> HTMLResponse:
    initial_title = ""
    initial_body_html = ""
    initial_filename = ""
    editing_id: str | None = None
    if edit:
        page, _, _ = _store_get(edit.strip(), allow_local=True)
        if not page or page.get("page_type") != "html":
            raise HTTPException(
                status_code=404,
                detail="HTML wiki page not found for editing.",
            )
        initial_title = str(page.get("title", ""))
        initial_body_html = str(page.get("body_raw", ""))
        initial_filename = str(page.get("html_filename", ""))
        editing_id = str(page.get("id", ""))
    return templates.TemplateResponse(
        request,
        "wiki_upload_html.html",
        {
            "title": "Upload HTML to wiki",
            "initial_title": initial_title,
            "initial_body_html": initial_body_html,
            "initial_filename": initial_filename,
            "editing_id": editing_id,
        },
    )


@app.post("/api/wiki/html/preview")
async def html_wiki_preview(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected.")
    raw = await file.read()
    try:
        parsed = parse_html_upload(raw, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "title": parsed["title"],
        "body_html": parsed["body_html"],
        "summary": parsed["summary"],
        "filename": parsed["filename"],
    }


@app.post("/api/wiki/html/save")
def save_html_wiki(body: HtmlWikiSaveRequest) -> dict[str, Any]:
    cleaned = sanitize_wiki_html(str(body.body_html))
    if not cleaned.strip():
        raise HTTPException(status_code=400, detail="HTML body is empty.")
    title = (body.title or "").strip() or "Untitled"
    filename = (body.filename or "").strip() or "upload.html"
    if body.page_id:
        pid = body.page_id.strip()
        existing, _, _ = _store_get(pid, allow_local=True)
        if not existing:
            raise HTTPException(status_code=404, detail="Wiki page not found")
        if existing.get("page_type") != "html":
            raise HTTPException(
                status_code=400,
                detail="This page is not an HTML wiki page.",
            )
        page: dict[str, Any] = {
            **existing,
            **_EMPTY_WIKI_FIELDS,
            "page_type": "html",
            "title": title,
            "body_raw": cleaned,
            "html_filename": filename,
            "id": pid,
            "created_at": existing.get("created_at") or _utc_now_iso(),
            "updated_at": _utc_now_iso(),
        }
    else:
        page = {
            **_EMPTY_WIKI_FIELDS,
            "page_type": "html",
            "title": title,
            "body_raw": cleaned,
            "html_filename": filename,
            "updated_at": _utc_now_iso(),
        }
    try:
        saved, backend, warn = _store_save(
            page, allow_local=bool(body.auto_fallback_local)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    folder_warn = _maybe_link_page_to_folder(
        body.folder_id, saved["id"], title, is_new=not body.page_id
    )
    if folder_warn:
        warn = f"{warn}; {folder_warn}" if warn else folder_warn
    return {
        "id": saved["id"],
        "url": f"/wiki/{saved['id']}",
        "backend": backend,
        "warning": warn,
    }


@app.get("/wiki/html-workspace", response_class=HTMLResponse)
def wiki_html_workspace(request: Request, edit: str | None = None) -> HTMLResponse:
    initial_title = ""
    initial_kind = "general"
    initial_filename = ""
    editing_id: str | None = None
    if edit:
        page, _, _ = _store_get(edit.strip(), allow_local=True)
        if not page or page.get("page_type") != "html_app":
            raise HTTPException(
                status_code=404,
                detail="Interactive HTML page not found for editing.",
            )
        initial_title = str(page.get("title", ""))
        initial_kind = str(page.get("html_kind") or "general")
        initial_filename = str(page.get("html_filename", ""))
        editing_id = str(page.get("id", ""))
    try:
        results, backend, warn = _store_search(query="", limit=80, allow_local=True)
    except Exception as e:
        results, backend, warn = [], "none", str(e)
    saved_apps = [r for r in results if r.get("page_type") == "html_app"]
    return templates.TemplateResponse(
        request,
        "wiki_html_workspace.html",
        {
            "title": "HTML workspace",
            "initial_title": initial_title,
            "initial_kind": initial_kind,
            "initial_filename": initial_filename,
            "editing_id": editing_id,
            "saved_apps": saved_apps,
            "backend": backend,
            "storage_note": warn,
            "max_mb": max_html_app_mb(),
        },
    )


@app.post("/api/wiki/html-app/prepare-upload")
def prepare_html_app_upload(body: HtmlAppPrepareUploadRequest) -> dict[str, Any]:
    limit = max_html_app_bytes()
    if body.file_size > limit:
        raise HTTPException(
            status_code=413,
            detail=f"HTML file too large (max {limit // (1024 * 1024)} MB).",
        )
    _check_filename = (body.filename or "").strip()
    if not _check_filename:
        raise HTTPException(status_code=400, detail="filename is required")

    if body.page_id:
        pid = body.page_id.strip()
        existing, _, _ = _store_get(pid, allow_local=True)
        if not existing:
            raise HTTPException(status_code=404, detail="Wiki page not found")
        if existing.get("page_type") != "html_app":
            raise HTTPException(
                status_code=400,
                detail="This page is not an interactive HTML workspace page.",
            )
    else:
        pid = uuid.uuid4().hex[:14]

    upload_url = _create_blob_upload_sas(_wiki_html_app_blob_name(pid))
    _ensure_wiki_blob_cors()
    return {
        "page_id": pid,
        "upload_url": upload_url,
        "direct_upload": upload_url is not None,
        "max_mb": limit // (1024 * 1024),
    }


@app.post("/api/wiki/html-app/finalize")
def finalize_html_app_upload(body: HtmlAppFinalizeRequest) -> dict[str, Any]:
    pid = body.page_id.strip()
    if not pid:
        raise HTTPException(status_code=400, detail="page_id is required")

    existing, _, _ = _store_get(pid, allow_local=True)
    if existing and existing.get("page_type") != "html_app":
        raise HTTPException(
            status_code=400,
            detail="This page is not an interactive HTML workspace page.",
        )

    try:
        head, total_size = _read_html_app_blob_head(pid)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    limit = max_html_app_bytes()
    if total_size > limit:
        raise HTTPException(
            status_code=413,
            detail=f"HTML file too large (max {limit // (1024 * 1024)} MB).",
        )

    filename = (body.filename or "").strip() or "upload.html"
    try:
        if total_size <= 2 * 1024 * 1024:
            full = _read_wiki_html_app_document(pid)
            parsed = parse_html_app_upload(full, filename)
            # Parse metadata only. Keep the uploaded Blob byte-for-byte intact;
            # the document is isolated when embedded by the frontend iframe.
            summary = parsed["summary"]
            default_title = parsed["title"]
        else:
            meta = parse_html_app_metadata(head, total_size, filename)
            summary = meta["summary"]
            default_title = meta["title"]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    page_title = (body.title or "").strip() or default_title or "Untitled"
    html_kind = _html_app_kind(body.kind)
    return _save_html_app_page(
        pid=pid,
        page_title=page_title,
        filename=filename,
        html_kind=html_kind,
        summary=summary,
        existing=existing,
        auto_fallback_local=body.auto_fallback_local,
        folder_id=body.folder_id,
    )


@app.post("/api/wiki/html-app/preview")
async def html_app_preview(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected.")
    raw = await file.read()
    try:
        parsed = parse_html_app_upload(raw, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "title": parsed["title"],
        "summary": parsed["summary"],
        "filename": parsed["filename"],
    }


@app.post("/api/wiki/html-app/save")
async def save_html_app(
    file: UploadFile = File(...),
    title: str = Form(""),
    kind: str = Form("general"),
    page_id: str | None = Form(None),
    folder_id: str | None = Form(None),
    auto_fallback_local: bool = Form(True),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected.")

    limit = max_html_app_bytes()
    tmp_path: Path | None = None
    try:
        tmp_path, total = await _stream_upload_to_temp(file, limit)
        filename = (file.filename or "").strip() or "upload.html"

        if total <= 2 * 1024 * 1024:
            raw = tmp_path.read_bytes()
            try:
                parsed = parse_html_app_upload(raw, filename)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            doc_bytes = parsed["document"].encode("utf-8")
            summary = parsed["summary"]
            default_title = parsed["title"]
        else:
            with tmp_path.open("rb") as fh:
                head_bytes = fh.read(512 * 1024)
            try:
                meta = parse_html_app_metadata(head_bytes, total, filename)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            summary = meta["summary"]
            default_title = meta["title"]
            doc_bytes = None

        page_title = (title or "").strip() or default_title or "Untitled"
        html_kind = _html_app_kind(kind)
        existing: dict[str, Any] | None = None

        if page_id:
            pid = page_id.strip()
            existing, _, _ = _store_get(pid, allow_local=True)
            if not existing:
                raise HTTPException(status_code=404, detail="Wiki page not found")
            if existing.get("page_type") != "html_app":
                raise HTTPException(
                    status_code=400,
                    detail="This page is not an interactive HTML workspace page.",
                )
        else:
            pid = uuid.uuid4().hex[:14]

        if doc_bytes is not None:
            _write_wiki_html_app_document(pid, doc_bytes)
        else:
            _write_wiki_html_app_document_from_path(pid, tmp_path)

        return _save_html_app_page(
            pid=pid,
            page_title=page_title,
            filename=filename,
            html_kind=html_kind,
            summary=summary,
            existing=existing,
            auto_fallback_local=auto_fallback_local,
            folder_id=folder_id,
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


@app.get("/api/wiki/html-app/{page_id}/document", response_model=None)
def get_html_app_document(page_id: str) -> Response:
    page, _, _ = _store_get(page_id.strip(), allow_local=True)
    if not page or page.get("page_type") != "html_app":
        raise HTTPException(status_code=404, detail="Interactive HTML page not found")
    raw = _read_wiki_html_app_document(page_id.strip())
    return Response(content=raw, media_type="text/html; charset=utf-8")


@app.post("/api/wiki/html-app/{page_id}/update-document")
def update_html_app_document(page_id: str, body: HtmlAppUpdateDocumentRequest) -> dict[str, Any]:
    pid = page_id.strip()
    page, _, _ = _store_get(pid, allow_local=True)
    if not page or page.get("page_type") != "html_app":
        raise HTTPException(status_code=404, detail="Interactive HTML page not found")
    raw = body.html.encode("utf-8")
    limit = max_html_app_bytes()
    if len(raw) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"HTML file too large (max {max(1, limit // (1024 * 1024))} MB).",
        )
    if not raw.strip():
        raise HTTPException(status_code=400, detail="HTML document is empty.")
    _write_wiki_html_app_document(pid, raw)
    return {"ok": True, "page_id": pid}


@app.post("/api/wiki/html-app/{page_id}/anchors")
def add_static_html_anchor(page_id: str, body: StaticHtmlAnchorRequest) -> dict[str, Any]:
    pid = page_id.strip()
    page, _, _ = _store_get(pid, allow_local=True)
    if not page or page.get("page_type") != "html_app":
        raise HTTPException(status_code=404, detail="Interactive HTML page not found")
    parsed = urllib.parse.urlparse(body.url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Enter a valid HTTP or HTTPS URL.")
    anchors = list(page.get("html_anchors") or [])
    if len(anchors) >= 5000:
        raise HTTPException(status_code=400, detail="This page has reached its anchor limit.")
    anchor = {
        "source_index": body.source_index,
        "url": urllib.parse.urlunparse(parsed._replace(fragment="")),
        "tooltip": re.sub(r"\s+", " ", body.tooltip).strip()[:240] or "Linked page",
    }
    anchors.append(anchor)
    page["html_anchors"] = anchors
    page["updated_at"] = _utc_now_iso()
    _store_save(page, allow_local=True)
    return {"ok": True, "anchor": anchor}


@app.get("/api/wiki/pages/{page_id}/comments")
def list_wiki_comments(page_id: str) -> dict[str, Any]:
    page, backend, warning = _store_get(page_id.strip(), allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    return {
        "comments": list(page.get("comments") or []),
        "backend": backend,
        "warning": warning,
    }


@app.post("/api/wiki/pages/{page_id}/comments")
def create_wiki_comment(page_id: str, body: WikiCommentCreateRequest) -> dict[str, Any]:
    pid = page_id.strip()
    page, _, _ = _store_get(pid, allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    comments = list(page.get("comments") or [])
    parent_id = (body.parent_id or "").strip() or None
    if parent_id and not any(str(item.get("id")) == parent_id for item in comments):
        raise HTTPException(status_code=400, detail="Parent comment not found")
    clean_body = body.body.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not clean_body:
        raise HTTPException(status_code=400, detail="Comment is empty")
    comment = {
        "id": uuid.uuid4().hex[:16],
        "parent_id": parent_id,
        "body": clean_body,
        "author_name": re.sub(r"\s+", " ", body.author_name).strip()[:200] or "Anonymous",
        "author_email": body.author_email.strip().lower()[:320],
        "author_picture": body.author_picture.strip()[:2048],
        "created_at": _utc_now_iso(),
    }
    comments.append(comment)
    page["comments"] = comments
    page["updated_at"] = _utc_now_iso()
    saved, backend, warning = _store_save(page, allow_local=True)
    return {
        "comment": comment,
        "comments": list(saved.get("comments") or comments),
        "backend": backend,
        "warning": warning,
    }


@app.get("/api/wiki/pages/{page_id}/notes")
def list_wiki_notes(page_id: str) -> dict[str, Any]:
    page, backend, warning = _store_get(page_id.strip(), allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    return {
        "notes": list(page.get("page_notes") or []),
        "backend": backend,
        "warning": warning,
    }


@app.post("/api/wiki/pages/{page_id}/notes")
def create_wiki_note(page_id: str, body: WikiNoteCreateRequest) -> dict[str, Any]:
    pid = page_id.strip()
    page, _, _ = _store_get(pid, allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    notes = list(page.get("page_notes") or [])
    title = re.sub(r"\s+", " ", body.title).strip()
    if not title:
        raise HTTPException(status_code=400, detail="Note title is required")
    if any(str(note.get("title") or "").strip().casefold() == title.casefold() for note in notes):
        raise HTTPException(status_code=409, detail="A note with this title already exists on this page")
    clean_body = body.body.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not clean_body:
        raise HTTPException(status_code=400, detail="Note is empty")
    note = {
        "id": uuid.uuid4().hex[:16],
        "title": title,
        "body": clean_body,
        "author_name": re.sub(r"\s+", " ", body.author_name).strip()[:200] or "Anonymous",
        "author_email": body.author_email.strip().lower()[:320],
        "created_at": _utc_now_iso(),
    }
    notes.append(note)
    page["page_notes"] = notes
    page["updated_at"] = _utc_now_iso()
    saved, backend, warning = _store_save(page, allow_local=True)
    return {
        "note": note,
        "notes": list(saved.get("page_notes") or notes),
        "backend": backend,
        "warning": warning,
    }


@app.post("/api/wiki/manual/preview")
def manual_wiki_preview(body: ManualWikiPreviewRequest) -> dict[str, str]:
    return {"markdown": paste_to_display_markdown(body.body)}


@app.post("/api/wiki/manual/save")
def save_manual_wiki(body: ManualWikiSaveRequest) -> dict[str, Any]:
    if not str(body.body).strip():
        raise HTTPException(status_code=400, detail="Body is empty.")
    title = (body.title or "").strip() or "Untitled"
    normalized_body = normalize_manual_body(body.body)
    existing_page: dict[str, Any] | None = None
    if body.page_id:
        pid = body.page_id.strip()
        existing_page, _, _ = _store_get(pid, allow_local=True)
        if not existing_page:
            raise HTTPException(status_code=404, detail="Wiki page not found")
        if existing_page.get("page_type") != "manual":
            raise HTTPException(
                status_code=400,
                detail="This page is not a manual notes page.",
            )
        page = {
            **existing_page,
            **_EMPTY_WIKI_FIELDS,
            "page_type": "manual",
            "title": title,
            "body_raw": normalized_body,
            "id": pid,
            "created_at": existing_page.get("created_at") or _utc_now_iso(),
            "updated_at": _utc_now_iso(),
        }
    else:
        page = {
            **_EMPTY_WIKI_FIELDS,
            "page_type": "manual",
            "title": title,
            "body_raw": normalized_body,
            "updated_at": _utc_now_iso(),
        }
    if body.attachments is not None:
        page["attachments"] = _merge_attachments(page_attachments(existing_page), body.attachments)
    elif existing_page and existing_page.get("attachments"):
        page["attachments"] = page_attachments(existing_page)
    try:
        saved, backend, warn = _store_save(
            page, allow_local=bool(body.auto_fallback_local)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    folder_warn = _maybe_link_page_to_folder(
        body.folder_id, saved["id"], title, is_new=not body.page_id
    )
    if folder_warn:
        warn = f"{warn}; {folder_warn}" if warn else folder_warn
    return {
        "id": saved["id"],
        "url": f"/wiki/{saved['id']}",
        "backend": backend,
        "warning": warn,
    }


@app.post("/api/wiki/post-notes/save")
def save_post_notes_wiki(body: PostNotesSaveRequest) -> dict[str, Any]:
    if not str(body.body).strip():
        raise HTTPException(status_code=400, detail="Body is empty.")
    title = (body.title or "").strip() or "Untitled"
    if body.page_id:
        pid = body.page_id.strip()
        existing, _, _ = _store_get(pid, allow_local=True)
        if not existing:
            raise HTTPException(status_code=404, detail="Wiki page not found")
        if existing.get("page_type") != "post_notes":
            raise HTTPException(
                status_code=400,
                detail="This page is not a post notes page.",
            )
        page: dict[str, Any] = {
            **existing,
            **_EMPTY_WIKI_FIELDS,
            "page_type": "post_notes",
            "title": title,
            "body_raw": body.body,
            "id": pid,
            "created_at": existing.get("created_at") or _utc_now_iso(),
            "updated_at": _utc_now_iso(),
        }
    else:
        page = {
            **_EMPTY_WIKI_FIELDS,
            "page_type": "post_notes",
            "title": title,
            "body_raw": body.body,
            "updated_at": _utc_now_iso(),
        }
    try:
        saved, backend, warn = _store_save(
            page, allow_local=bool(body.auto_fallback_local)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    folder_warn = _maybe_link_page_to_folder(
        body.folder_id, saved["id"], title, is_new=not body.page_id
    )
    if folder_warn:
        warn = f"{warn}; {folder_warn}" if warn else folder_warn
    return {
        "id": saved["id"],
        "url": f"/wiki/{saved['id']}",
        "backend": backend,
        "warning": warn,
    }


@app.post("/api/wiki/manual/upload-image")
async def upload_manual_wiki_image(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")
    max_bytes = 20 * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="Image too large (max 20 MB).")

    ext = Path(file.filename).suffix.lower()
    allowed = {
        ".apng",
        ".avif",
        ".gif",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image format. Use png, jpg, gif, webp, avif, or apng.",
        )

    image_id = uuid.uuid4().hex[:14]
    name = f"{image_id}{ext}"
    if not _upload_wiki_image_blob(name, raw):
        out = _wiki_image_dir() / name
        out.write_bytes(raw)
    url = f"/api/wiki/images/{name}"
    alt = Path(file.filename).stem.strip() or "image"
    return {"url": url, "markdown": f"![{alt}]({url})"}


@app.post("/api/wiki/manual/upload-video")
async def upload_manual_wiki_video(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")
    max_bytes = 100 * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="Video too large (max 100 MB).")

    ext = Path(file.filename).suffix.lower()
    allowed = {".mp4", ".webm", ".ogg", ".mov", ".m4v"}
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Unsupported video format. Use mp4, webm, ogg, mov, or m4v.",
        )

    video_id = uuid.uuid4().hex[:14]
    name = f"{video_id}{ext}"
    if not _upload_wiki_video_blob(name, raw):
        out = _wiki_video_dir() / name
        out.write_bytes(raw)
    url = f"/api/wiki/videos/{name}"
    return {"url": url, "markdown": f"@[video]({url})"}


@app.post("/api/wiki/files/upload")
async def upload_wiki_file(
    file: UploadFile = File(...),
    page_id: str | None = Form(None),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected.")
    original_name = validate_upload_filename(file.filename)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(raw) > MAX_WIKI_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB).")

    file_id = new_file_id(original_name)
    content_type = file.content_type or file_media_type(file_id)
    _persist_wiki_file_bytes(file_id, raw)
    attachment = build_attachment_record(
        file_id=file_id,
        original_name=original_name,
        size=len(raw),
        content_type=content_type,
        uploaded_at=_utc_now_iso(),
    )
    url = attachment["url"]
    markdown = build_file_markdown_link(original_name, url)

    if page_id:
        pid = page_id.strip()
        existing, _, _ = _store_get(pid, allow_local=True)
        if not existing:
            raise HTTPException(status_code=404, detail="Wiki page not found")
        page = {
            **existing,
            "attachments": _append_page_attachment(existing, attachment),
            "updated_at": _utc_now_iso(),
        }
        try:
            _store_save(page, allow_local=True)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    return {
        **attachment,
        "markdown": markdown,
        "linked_to_page": bool(page_id),
    }


@app.get("/api/wiki/pages/{page_id}/files")
def list_wiki_page_files(page_id: str) -> dict[str, Any]:
    page, backend, warn = _store_get(page_id.strip(), allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    return {
        "page_id": page_id,
        "attachments": page_attachments(page),
        "backend": backend,
        "warning": warn,
    }


@app.delete("/api/wiki/pages/{page_id}/files/{file_id}")
def delete_wiki_page_file(page_id: str, file_id: str) -> dict[str, Any]:
    pid = page_id.strip()
    fid = Path(file_id).name
    existing, backend, warn = _store_get(pid, allow_local=True)
    if not existing:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    attachments = [a for a in page_attachments(existing) if str(a.get("id")) != fid]
    page = {
        **existing,
        "attachments": attachments,
        "updated_at": _utc_now_iso(),
    }
    try:
        saved, backend, warn = _store_save(page, allow_local=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {
        "page_id": saved["id"],
        "attachments": page_attachments(saved),
        "backend": backend,
        "warning": warn,
    }


@app.get("/api/wiki/files/{file_id}", response_model=None)
def get_wiki_file(file_id: str) -> FileResponse | Response:
    fid = Path(file_id).name
    blob = _download_wiki_file_blob(fid)
    if blob is not None:
        raw, media_type = blob
        attachment = Response(content=raw, media_type=media_type)
        return attachment
    p = wiki_file_path(fid)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        p,
        filename=p.name,
        media_type=file_media_type(p.name),
    )


@app.get("/api/wiki/videos/{video_name}", response_model=None)
def get_manual_wiki_video(video_name: str) -> FileResponse | Response:
    blob = _download_wiki_video_blob(video_name)
    if blob is not None:
        raw, media_type = blob
        return Response(content=raw, media_type=media_type)
    p = _wiki_video_path(video_name)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Video not found")
    media_type = _video_media_type(p.name)
    return FileResponse(p, filename=p.name, media_type=media_type)


@app.get("/api/wiki/images/{image_name}", response_model=None)
def get_manual_wiki_image(image_name: str) -> FileResponse | Response:
    blob = _download_wiki_image_blob(image_name)
    if blob is not None:
        raw, media_type = blob
        return Response(content=raw, media_type=media_type)
    p = _wiki_image_path(image_name)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    media_type = _image_media_type(p.name)
    return FileResponse(p, filename=p.name, media_type=media_type)


@app.post("/api/wiki/link-existing")
def wiki_link_existing(body: WikiLinkExistingRequest) -> dict[str, Any]:
    source_id = body.source_page_id.strip()
    target_id = body.target_page_id.strip()
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Choose a different destination page")
    source, _, _ = _store_get(source_id, allow_local=True)
    target, _, _ = _store_get(target_id, allow_local=True)
    if not source:
        raise HTTPException(status_code=404, detail="Source wiki page not found")
    if not target or target.get("page_type") in {"exam", "flashcard_deck"}:
        raise HTTPException(status_code=404, detail="Destination wiki page not found")

    page_type = str(source.get("page_type") or "video")
    matched: str | None = None
    if page_type in {"manual", "post_notes"}:
        raw = str(source.get("body_raw") or "")
        matched = _pick_selection_segment(raw, body.selected_text)
        if not matched:
            raise HTTPException(status_code=422, detail="Could not match the selected keyword to the saved page text")
        link_md = f"[{_md_link_label(matched, str(target.get('title') or 'page'))}](/wiki/{target_id})"
        source["body_raw"] = raw.replace(matched, link_md, 1)
    elif page_type == "video":
        transcript = str(source.get("transcript") or "")
        matched = _pick_selection_segment(transcript, body.selected_text)
        if not matched:
            raise HTTPException(status_code=422, detail="Could not match the selected keyword to the saved transcript")
        links = list(source.get("transcript_links") or [])
        links.append({"snippet": matched, "wiki_id": target_id})
        source["transcript_links"] = links
    else:
        raise HTTPException(status_code=400, detail="Keyword links are supported on Paste Notes, Post Notes, and transcript pages")

    created_at = _utc_now_iso()
    backlinks = list(target.get("backlinks") or [])
    duplicate = any(
        str(item.get("source_page_id")) == source_id
        and str(item.get("keyword") or "").casefold() == str(matched).casefold()
        for item in backlinks
    )
    backlink = {
        "id": uuid.uuid4().hex[:16],
        "source_page_id": source_id,
        "source_title": str(source.get("title") or "Untitled"),
        "keyword": str(matched)[:2000],
        "created_at": created_at,
    }
    if not duplicate:
        backlinks.append(backlink)
    target["backlinks"] = backlinks[-500:]
    source["updated_at"] = created_at
    target["updated_at"] = created_at
    _store_save(source, allow_local=True)
    saved_target, backend, warning = _store_save(target, allow_local=True)
    return {
        "ok": True,
        "source_page_id": source_id,
        "target_page_id": target_id,
        "keyword": matched,
        "backlinks": list(saved_target.get("backlinks") or backlinks),
        "backend": backend,
        "warning": warning,
    }


@app.post("/api/wiki/link-from-selection")
def wiki_link_from_selection(body: WikiLinkFromSelectionRequest) -> dict[str, Any]:
    parent_id = body.parent_id.strip()
    if not parent_id:
        raise HTTPException(status_code=400, detail="parent_id is required")
    parent, _b, _w = _store_get(parent_id, allow_local=True)
    if not parent:
        raise HTTPException(status_code=404, detail="Parent page not found")

    new_id = uuid.uuid4().hex[:14]
    title = (body.new_title or "").strip() or "Linked page"
    nb = normalize_manual_body(body.new_body) if (body.new_body or "").strip() else ""
    child: dict[str, Any] = {
        **_EMPTY_WIKI_FIELDS,
        "page_type": "manual",
        "id": new_id,
        "title": title,
        "body_raw": nb
        or (
            f"*Linked from* [{_md_link_label(str(parent.get('title') or 'Page'), 'parent')}](/wiki/{parent_id})\n\n"
        ),
        "linked_from_page_id": parent_id,
        "linked_selection": "",
        "updated_at": _utc_now_iso(),
    }

    try:
        if body.source == "manual":
            if parent.get("page_type") != "manual":
                raise HTTPException(
                    status_code=400,
                    detail="Link from notes selection only applies to manual wiki pages.",
                )
            raw = str(parent.get("body_raw", ""))
            matched = _pick_selection_segment(raw, body.selected_text)
            if not matched:
                raise HTTPException(
                    status_code=422,
                    detail="Could not match the selection to saved markdown. "
                    "Try a shorter unique phrase, or select text that matches the note once "
                    "(including if it uses italics, bold, or code in the source).",
                )
            child["linked_selection"] = matched[:2000]
            link_md = f"[{_md_link_label(matched, title)}](/wiki/{new_id})"
            parent["body_raw"] = raw.replace(matched, link_md, 1)
            parent["updated_at"] = _utc_now_iso()
            saved_child, backend, warn = _store_save(
                child, allow_local=bool(body.auto_fallback_local)
            )
            _store_save(parent, allow_local=bool(body.auto_fallback_local))
            return {
                "id": saved_child["id"],
                "url": f"/wiki/{saved_child['id']}",
                "backend": backend,
                "warning": warn,
            }

        # transcript (video pages)
        tr = str(parent.get("transcript", ""))
        if not tr.strip():
            raise HTTPException(status_code=400, detail="This page has no transcript to link from.")
        matched = _pick_selection_segment(tr, body.selected_text)
        if not matched:
            raise HTTPException(
                status_code=422,
                detail="Could not match the selection to the saved transcript. Try selecting a shorter exact phrase.",
            )
        child["linked_selection"] = matched[:2000]
        links = list(parent.get("transcript_links") or [])
        links.append({"snippet": matched, "wiki_id": new_id})
        parent["transcript_links"] = links
        parent["updated_at"] = _utc_now_iso()
        saved_child, backend, warn = _store_save(
            child, allow_local=bool(body.auto_fallback_local)
        )
        _store_save(parent, allow_local=bool(body.auto_fallback_local))
        return {
            "id": saved_child["id"],
            "url": f"/wiki/{saved_child['id']}",
            "backend": backend,
            "warning": warn,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/wiki/anchor")
def wiki_anchor(body: WikiAnchorRequest) -> dict[str, Any]:
    page, _backend, _warning = _store_get(body.page_id.strip(), allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    if page.get("page_type") != "manual":
        raise HTTPException(status_code=400, detail="Anchors apply to Paste Notes pages.")

    parsed = urllib.parse.urlparse(body.url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Enter a valid HTTP or HTTPS URL.")
    clean_path = parsed.path
    if parsed.hostname in {"chatgpt.com", "www.chatgpt.com"}:
        clean_path = re.sub(r"^/c/(?:WEB%3A|WEB:)", "/c/", clean_path, flags=re.IGNORECASE)
    safe_url = urllib.parse.urlunparse(parsed._replace(path=clean_path, fragment=""))
    tooltip = re.sub(r"\s+", " ", body.tooltip_text).strip()[:240] or "Linked page"
    tooltip = tooltip.replace("\\", "\\\\").replace('"', '\\"')
    anchor = f'[↗]({safe_url} "{tooltip}")'

    raw = str(page.get("body_raw", ""))
    matched = _pick_selection_segment(raw, body.selected_text) if body.selected_text.strip() else ""
    if matched:
        page["body_raw"] = raw.replace(matched, matched + anchor, 1)
    else:
        before, after = body.context_before, body.context_after
        needle = before + after
        caret = raw.find(needle) + len(before) if needle and raw.count(needle) == 1 else -1
        if caret < 0 and before and raw.count(before) == 1:
            caret = raw.find(before) + len(before)
        if caret < 0 and after and raw.count(after) == 1:
            caret = raw.find(after)
        # Renderers can substantially transform Markdown (especially KaTeX), so
        # the visible DOM context is not always present verbatim in body_raw.
        # Preserve the user's clicked position using its relative document offset
        # as a graceful fallback instead of rejecting the anchor.
        if caret < 0 and body.caret_ratio is not None:
            caret = round(len(raw) * body.caret_ratio)
            caret = max(0, min(len(raw), caret))
            # Avoid splitting a Markdown word when the proportional position
            # lands in its middle. Prefer the nearest whitespace boundary.
            boundaries = [
                pos for pos in (raw.rfind(" ", 0, caret), raw.find(" ", caret))
                if pos >= 0
            ]
            if boundaries:
                nearest = min(boundaries, key=lambda pos: abs(pos - caret))
                if abs(nearest - caret) <= 40:
                    caret = nearest
        if caret < 0:
            raise HTTPException(status_code=422, detail="Could not match the clicked text position.")
        page["body_raw"] = raw[:caret] + anchor + raw[caret:]

    page["updated_at"] = _utc_now_iso()
    saved, backend, warning = _store_save(page, allow_local=body.auto_fallback_local)
    return {
        "id": saved["id"],
        "url": f"/wiki/{saved['id']}",
        "anchor_url": safe_url,
        "tooltip": re.sub(r"\s+", " ", body.tooltip_text).strip()[:240] or "Linked page",
        "backend": backend,
        "warning": warning,
    }


def _unlink_read_aloud_temp(path: str) -> None:
    Path(path).unlink(missing_ok=True)


@app.post("/api/tts/read-aloud")
def tts_read_aloud(body: ReadAloudRequest) -> FileResponse:
    from applimit.tts import voice_for_lang
    from applimit.wiki_audio import synthesize_read_aloud_mp3

    """Synthesize speech (Edge TTS stream → MP3 bytes; no ffmpeg). Repeats are client-side."""
    raw = (body.text or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="text is required")
    if len(raw) > 50_000:
        raise HTTPException(
            status_code=400,
            detail="text is too long (max 50000 characters)",
        )
    lang = (body.lang or "en").strip() or "en"
    try:
        voice = voice_for_lang(lang, body.voice)
    except Exception:
        voice = voice_for_lang("en", body.voice)
    fd, path_str = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        synthesize_read_aloud_mp3(
            raw,
            Path(path_str),
            voice=voice,
        )
    except Exception as e:
        Path(path_str).unlink(missing_ok=True)
        log.exception("read-aloud failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return FileResponse(
        path_str,
        media_type="audio/mpeg",
        filename="read-aloud.mp3",
        background=BackgroundTask(_unlink_read_aloud_temp, path_str),
    )


@app.get("/wiki/{page_id}", response_class=HTMLResponse)
def wiki_page(request: Request, page_id: str) -> HTMLResponse:
    page, backend, _warn = _store_get(page_id, allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    results, _b2, _w2 = _store_search(query="", limit=30, allow_local=True)
    if page.get("page_type") == "manual":
        md = paste_to_display_markdown(str(page.get("body_raw", "")))
        return templates.TemplateResponse(
            request,
            "wiki_manual.html",
            {
                "title": page.get("title") or f"Wiki {page_id}",
                "page": page,
                "results": results,
                "backend": backend,
                "body_markdown_json": json.dumps(md),
            },
        )
    if page.get("page_type") == "post_notes":
        return templates.TemplateResponse(
            request,
            "wiki_post_notes_view.html",
            {
                "title": page.get("title") or f"Wiki {page_id}",
                "page": page,
                "results": results,
                "backend": backend,
                "body_markdown_json": json.dumps(str(page.get("body_raw", ""))),
            },
        )
    if page.get("page_type") == "html":
        body_html = sanitize_wiki_html(str(page.get("body_raw", "")))
        return templates.TemplateResponse(
            request,
            "wiki_html_page.html",
            {
                "title": page.get("title") or f"Wiki {page_id}",
                "page": page,
                "results": results,
                "backend": backend,
                "body_html": body_html,
            },
        )
    if page.get("page_type") == "html_app":
        return templates.TemplateResponse(
            request,
            "wiki_html_app.html",
            {
                "title": page.get("title") or f"Wiki {page_id}",
                "page": page,
                "results": results,
                "backend": backend,
                "document_url": f"/api/wiki/html-app/{page_id}/document",
            },
        )
    links = page.get("transcript_links") or []
    transcript_html = (
        _render_transcript_with_links(str(page.get("transcript", "")), links)
        if links
        else None
    )
    return templates.TemplateResponse(
        request,
        "wiki_page.html",
        {
            "title": page.get("title") or f"Wiki {page_id}",
            "page": page,
            "results": results,
            "backend": backend,
            "hindi_audio_ready": _wiki_audio_path(page_id).is_file(),
            "uploaded_translated_ready": _wiki_uploaded_translated_path(page_id) is not None,
            "transcript_html": transcript_html,
        },
    )


@app.get("/api/wiki/{page_id}/section-reads")
def wiki_section_reads_get(page_id: str) -> dict[str, Any]:
    page, backend, _warn = _store_get(page_id, allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    if page.get("page_type") != "manual":
        raise HTTPException(
            status_code=400,
            detail="Section read counts are only available for manual (pasted notes) wiki pages.",
        )
    store: AzureWikiStore | LocalWikiStore = (
        LocalWikiStore() if backend == "local" else AzureWikiStore()
    )
    return {"counts": store.get_section_read_counts(page_id)}


@app.post("/api/wiki/{page_id}/section-reads")
def wiki_section_reads_post(
    page_id: str, body: WikiSectionReadTapBody
) -> dict[str, Any]:
    page, backend, _warn = _store_get(page_id, allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    if page.get("page_type") != "manual":
        raise HTTPException(
            status_code=400,
            detail="Section read counts are only available for manual (pasted notes) wiki pages.",
        )
    store: AzureWikiStore | LocalWikiStore = (
        LocalWikiStore() if backend == "local" else AzureWikiStore()
    )
    try:
        n = store.increment_section_read_count(page_id, body.section_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"section_key": body.section_key, "count": n}


@app.post("/api/insights")
def generate_insights(body: InsightRequest) -> dict:
    from applimit.captions import try_fetch_transcript
    from applimit.insights import build_insights_ai

    vid = extract_video_id(body.url)
    if not vid:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL or video id")
    segs = try_fetch_transcript(vid)
    if not segs:
        raise HTTPException(
            status_code=422,
            detail="Transcript unavailable for this video. Try a video with captions.",
        )
    try:
        payload = build_insights_ai(segs, custom_demand=body.custom_demand)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {e}") from e
    payload["video_id"] = vid
    return payload


@app.post("/api/flashcards")
def generate_flashcards(body: FlashcardRequest) -> dict:
    from applimit.captions import try_fetch_transcript
    from applimit.insights import build_flashcards_ai, build_insights_ai

    vid = extract_video_id(body.url)
    if not vid:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL or video id")
    insights = body.insights
    if not insights:
        segs = try_fetch_transcript(vid)
        if not segs:
            raise HTTPException(
                status_code=422,
                detail="Transcript unavailable for this video. Try a video with captions.",
            )
        try:
            insights = build_insights_ai(segs, custom_demand=body.custom_demand)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"AI analysis failed: {e}") from e
        insights["video_id"] = vid
    try:
        cards = build_flashcards_ai(insights)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Flashcard generation failed: {e}") from e
    return {"video_id": vid, "count": len(cards), "flashcards": cards}


def _normalize_flashcard_deck(raw_cards: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, raw in enumerate(raw_cards):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"Flashcard {index + 1} must be an object")
        front = str(raw.get("front") or raw.get("question") or raw.get("term") or raw.get("prompt") or "").strip()
        back = str(raw.get("back") or raw.get("answer") or raw.get("definition") or raw.get("response") or "").strip()
        if not front or not back:
            raise HTTPException(status_code=400, detail=f"Flashcard {index + 1} requires non-empty front and back text")
        normalized.append({"id": uuid.uuid4().hex[:12], "front": front[:20000], "back": back[:20000]})
    return normalized


def _flashcard_user_key(email: str) -> str:
    return email.strip().lower()


def _flashcard_deck_summary(deck: dict[str, Any], user_email: str = "") -> dict[str, Any]:
    cards = list(deck.get("flashcard_cards") or [])
    status = dict((deck.get("flashcard_statuses") or {}).get(_flashcard_user_key(user_email)) or {}) if user_email else {}
    valid_ids = {str(card.get("id") or "") for card in cards}
    seen = {str(value) for value in status.get("seen_card_ids") or []} & valid_ids
    mastered = {str(value) for value in status.get("mastered_card_ids") or []} & valid_ids
    return {
        "id": deck.get("id"),
        "title": deck.get("title") or "Untitled flashcards",
        "card_count": len(cards),
        "seen_count": len(seen),
        "mastered_count": len(mastered),
        "current_index": min(int(status.get("current_index") or 0), max(0, len(cards) - 1)),
        "progress_percent": round((len(mastered) / len(cards)) * 100) if cards else 0,
        "completed": bool(cards) and len(mastered) >= len(cards),
        "created_at": deck.get("created_at", ""),
        "updated_at": deck.get("updated_at", ""),
    }


@app.get("/api/flashcards/decks")
def list_flashcard_decks(user_email: str = "") -> dict[str, Any]:
    items, backend, warning = _store_search(query="", limit=200, allow_local=True)
    decks: list[dict[str, Any]] = []
    for item in items:
        if item.get("page_type") != "flashcard_deck":
            continue
        deck, _, _ = _store_get(str(item.get("id") or ""), allow_local=True)
        if deck:
            decks.append(_flashcard_deck_summary(deck, user_email))
    decks.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return {"decks": decks, "backend": backend, "warning": warning}


@app.post("/api/flashcards/decks")
def create_flashcard_deck(body: FlashcardDeckCreateRequest) -> dict[str, Any]:
    cards = _normalize_flashcard_deck(body.cards)
    deck = {
        "id": uuid.uuid4().hex[:16],
        "page_type": "flashcard_deck",
        "title": re.sub(r"\s+", " ", body.title).strip(),
        "source_filename": Path(body.source_filename).name if body.source_filename else "",
        "flashcard_cards": cards,
        "flashcard_statuses": {},
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
    }
    saved, backend, warning = _store_save(deck, allow_local=True)
    return {"deck": _flashcard_deck_summary(saved), "backend": backend, "warning": warning}


@app.get("/api/flashcards/decks/{deck_id}")
def get_flashcard_deck(deck_id: str, user_email: str = "") -> dict[str, Any]:
    deck, backend, warning = _store_get(deck_id.strip(), allow_local=True)
    if not deck or deck.get("page_type") != "flashcard_deck":
        raise HTTPException(status_code=404, detail="Flashcard deck not found")
    summary = _flashcard_deck_summary(deck, user_email)
    status = dict((deck.get("flashcard_statuses") or {}).get(_flashcard_user_key(user_email)) or {}) if user_email else {}
    return {
        "deck": {
            **summary,
            "cards": list(deck.get("flashcard_cards") or []),
            "status": {
                "current_index": summary["current_index"],
                "seen_card_ids": list(status.get("seen_card_ids") or []),
                "mastered_card_ids": list(status.get("mastered_card_ids") or []),
            },
        },
        "backend": backend,
        "warning": warning,
    }


@app.put("/api/flashcards/decks/{deck_id}/status")
def save_flashcard_deck_status(deck_id: str, body: FlashcardDeckStatusRequest) -> dict[str, Any]:
    deck, _, _ = _store_get(deck_id.strip(), allow_local=True)
    if not deck or deck.get("page_type") != "flashcard_deck":
        raise HTTPException(status_code=404, detail="Flashcard deck not found")
    cards = list(deck.get("flashcard_cards") or [])
    valid_ids = {str(card.get("id") or "") for card in cards}
    seen = list(dict.fromkeys(str(value) for value in body.seen_card_ids if str(value) in valid_ids))
    mastered = list(dict.fromkeys(str(value) for value in body.mastered_card_ids if str(value) in valid_ids))
    statuses = dict(deck.get("flashcard_statuses") or {})
    statuses[_flashcard_user_key(body.user_email)] = {
        "user_name": re.sub(r"\s+", " ", body.user_name).strip()[:200],
        "current_index": min(body.current_index, max(0, len(cards) - 1)),
        "seen_card_ids": seen,
        "mastered_card_ids": mastered,
        "updated_at": _utc_now_iso(),
    }
    deck["flashcard_statuses"] = statuses
    deck["updated_at"] = _utc_now_iso()
    saved, backend, warning = _store_save(deck, allow_local=True)
    return {"deck": _flashcard_deck_summary(saved, body.user_email), "backend": backend, "warning": warning}


def _normalize_insights_payload(d: dict[str, Any]) -> dict[str, Any]:
    def list_str(v: Any) -> list[str]:
        if not isinstance(v, list):
            return []
        return [str(x).strip() for x in v if str(x).strip()]

    def list_obj(v: Any, a: str, b: str) -> list[dict[str, str]]:
        if not isinstance(v, list):
            return []
        out: list[dict[str, str]] = []
        for x in v:
            if not isinstance(x, dict):
                continue
            aa = str(x.get(a, "")).strip()
            bb = str(x.get(b, "")).strip()
            if aa and bb:
                out.append({a: aa, b: bb})
        return out

    return {
        "transcript": str(d.get("transcript", "")).strip(),
        "terminologies": list_str(d.get("terminologies")),
        "concepts": list_obj(d.get("concepts"), "concept", "definition"),
        "important_points": list_str(d.get("important_points")),
        "questions_and_definitions": list_obj(
            d.get("questions_and_definitions"), "question", "definition"
        ),
        "custom_response": str(d.get("custom_response", "")).strip(),
        "segment_count": int(d.get("segment_count", 0) or 0),
    }


@app.post("/api/wiki/save")
def save_wiki_page(body: WikiSaveRequest) -> dict:
    vid = extract_video_id(body.url)
    if not vid:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL or video id")
    clean = _normalize_insights_payload(body.insights or {})
    if not clean["transcript"]:
        raise HTTPException(status_code=400, detail="Insights transcript is empty.")
    title = (body.title or f"Video {vid}").strip()
    page = {
        "title": title,
        "video_id": vid,
        "source_url": body.url,
        "embed_url": f"https://www.youtube.com/embed/{vid}",
        **clean,
    }
    try:
        saved, backend, warn = _store_save(page, allow_local=bool(body.auto_fallback_local))
    except Exception as e:
        msg = (
            f"Wiki persistence failed: {e}. "
            "If using Azure Blob with az login, assign 'Storage Blob Data Contributor' role to your signed-in user/service principal on the storage account."
        )
        raise HTTPException(status_code=500, detail=msg) from e
    folder_warn = _maybe_link_page_to_folder(
        body.folder_id,
        saved["id"],
        title,
        is_new=True,
    )
    if folder_warn:
        warn = f"{warn}; {folder_warn}" if warn else folder_warn
    return {
        "id": saved["id"],
        "url": f"/wiki/{saved['id']}",
        "backend": backend,
        "warning": warn,
    }


@app.post("/api/wiki/{page_id}/generate-hindi-audio")
def generate_wiki_hindi_audio(page_id: str) -> dict:
    from applimit.wiki_audio import synthesize_hindi_mp3, translate_text_to_hindi_openai

    page, backend, warn = _store_get(page_id, allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    transcript = str(page.get("transcript", "")).strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="Wiki transcript is empty.")
    out = _wiki_audio_path(page_id)
    try:
        hindi = translate_text_to_hindi_openai(transcript)
        synthesize_hindi_mp3(hindi, out)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Hindi audio generation failed: {e}") from e
    return {
        "page_id": page_id,
        "backend": backend,
        "warning": warn,
        "audio_url": f"/api/wiki/{page_id}/hindi-audio",
    }


@app.get("/api/wiki/{page_id}/hindi-audio")
def get_wiki_hindi_audio(page_id: str) -> FileResponse:
    p = _wiki_audio_path(page_id)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Hindi audio not generated yet.")
    return FileResponse(p, filename=p.name, media_type="audio/mpeg")


@app.get("/api/wiki/{page_id}/original-audio")
def get_wiki_original_audio(page_id: str) -> FileResponse:
    from applimit.wiki_youtube_audio import ensure_original_audio_file, guess_media_type

    page, _backend, _warn = _store_get(page_id, allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    source_url = str(page.get("source_url", "")).strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="Wiki page has no source URL.")
    try:
        p = ensure_original_audio_file(source_url, page_id, _wiki_audio_dir())
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"Could not download original audio: {e}"
        ) from e
    return FileResponse(
        p,
        filename=p.name,
        media_type=guess_media_type(p),
    )


@app.post("/api/wiki/{page_id}/upload-translated-audio")
async def upload_wiki_translated_audio(
    page_id: str, file: UploadFile = File(...)
) -> dict:
    page, _backend, _warn = _store_get(page_id, allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")
    max_bytes = 250 * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="File too large (max 250 MB).")
    ext = Path(file.filename).suffix.lower()
    if ext not in (".mp3", ".m4a", ".wav", ".webm", ".ogg", ".opus", ".aac", ".flac"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported format. Use mp3, m4a, wav, webm, ogg, opus, aac, or flac.",
        )
    out_dir = _wiki_audio_dir()
    for old in _wiki_uploaded_translated_glob(page_id):
        try:
            old.unlink()
        except OSError:
            pass
    out = out_dir / f"{page_id}_translated_upload{ext}"
    out.write_bytes(raw)
    return {
        "page_id": page_id,
        "audio_url": f"/api/wiki/{page_id}/uploaded-translated-audio",
    }


@app.get("/api/wiki/{page_id}/uploaded-translated-audio")
def get_wiki_uploaded_translated_audio(page_id: str) -> FileResponse:
    from applimit.wiki_youtube_audio import guess_media_type

    p = _wiki_uploaded_translated_path(page_id)
    if not p or not p.is_file():
        raise HTTPException(status_code=404, detail="No uploaded translated audio.")
    return FileResponse(
        p,
        filename=p.name,
        media_type=guess_media_type(p),
    )


@app.patch("/api/wiki/pages/{page_id}/tags")
def update_wiki_page_tags(page_id: str, body: WikiTagsUpdateRequest) -> dict[str, Any]:
    existing, _backend, _warn = _store_get(page_id.strip(), allow_local=True)
    if not existing:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    tags = _normalize_tags(body.tags)
    page: dict[str, Any] = {
        **existing,
        "tags": tags,
        "updated_at": _utc_now_iso(),
    }
    try:
        saved, backend, warn = _store_save(page, allow_local=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {
        "id": saved["id"],
        "tags": saved.get("tags") or [],
        "backend": backend,
        "warning": warn,
    }


@app.get("/api/wiki/pages/{page_id}")
def wiki_page_json(page_id: str) -> dict[str, Any]:
    """Return wiki page JSON for the Next.js frontend."""
    page, backend, warn = _store_get(page_id, allow_local=True)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    out: dict[str, Any] = {
        "page": page,
        "backend": backend,
        "warning": warn,
        "attachments": page_attachments(page),
    }
    page_type = page.get("page_type")
    if page_type == "manual":
        out["body_markdown"] = paste_to_display_markdown(str(page.get("body_raw", "")))
    elif page_type == "post_notes":
        out["body_markdown"] = str(page.get("body_raw", ""))
    elif page_type == "html":
        out["body_html"] = sanitize_wiki_html(str(page.get("body_raw", "")))
    elif page_type == "html_app":
        out["document_url"] = f"/api/wiki/html-app/{page_id}/document"
    else:
        links = page.get("transcript_links") or []
        transcript = str(page.get("transcript", ""))
        out["transcript_html"] = (
            _render_transcript_with_links(transcript, links) if links else None
        )
        out["transcript"] = transcript
        out["hindi_audio_ready"] = _wiki_audio_path(page_id).is_file()
        out["uploaded_translated_ready"] = (
            _wiki_uploaded_translated_path(page_id) is not None
        )
    return out


def _exam_user_key(email: str) -> str:
    return email.strip().lower()


def _normalize_exam_questions(raw_questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_questions):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"Question {index + 1} must be an object")
        prompt = str(raw.get("question") or raw.get("prompt") or raw.get("text") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail=f"Question {index + 1} has no question text")
        raw_options = raw.get("options")
        if isinstance(raw_options, dict):
            options = [str(raw_options.get(letter) or raw_options.get(letter.lower()) or "").strip() for letter in "ABCD"]
        elif isinstance(raw_options, list):
            options = [str(value).strip() for value in raw_options]
        else:
            options = [
                str(raw.get(letter) or raw.get(letter.lower()) or raw.get(f"option_{letter.lower()}") or raw.get(f"option{letter}") or "").strip()
                for letter in "ABCD"
            ]
        if len(options) != 4 or any(not option for option in options):
            raise HTTPException(status_code=400, detail=f"Question {index + 1} must contain four non-empty options")
        correct = str(raw.get("correct_answer") or raw.get("answer") or raw.get("correct") or "").strip().upper()
        if correct not in {"A", "B", "C", "D"}:
            raise HTTPException(status_code=400, detail=f"Question {index + 1} correct answer must be A, B, C, or D")
        normalized.append({
            "id": uuid.uuid4().hex[:12],
            "question": prompt,
            "options": options,
            "correct_answer": correct,
        })
    return normalized


def _exam_summary(exam: dict[str, Any], user_email: str = "") -> dict[str, Any]:
    questions = list(exam.get("exam_questions") or [])
    status = dict((exam.get("exam_statuses") or {}).get(_exam_user_key(user_email)) or {}) if user_email else {}
    answers = dict(status.get("answers") or {})
    correct = sum(1 for answer in answers.values() if answer.get("correct") is True)
    return {
        "id": exam.get("id"),
        "title": exam.get("title") or "Untitled exam",
        "question_count": len(questions),
        "answered_count": len(answers),
        "correct_count": correct,
        "incorrect_count": len(answers) - correct,
        "current_index": int(status.get("current_index") or 0),
        "completed": len(questions) > 0 and len(answers) >= len(questions),
        "created_at": exam.get("created_at", ""),
        "updated_at": exam.get("updated_at", ""),
    }


def _exam_public_payload(exam: dict[str, Any], user_email: str = "") -> dict[str, Any]:
    summary = _exam_summary(exam, user_email)
    questions = [
        {"id": question.get("id"), "question": question.get("question"), "options": list(question.get("options") or [])}
        for question in exam.get("exam_questions") or []
    ]
    status = dict((exam.get("exam_statuses") or {}).get(_exam_user_key(user_email)) or {}) if user_email else {}
    return {**summary, "questions": questions, "status": {"answers": dict(status.get("answers") or {}), "current_index": summary["current_index"]}}


@app.get("/api/exams")
def list_exams(user_email: str = "") -> dict[str, Any]:
    items, backend, warning = _store_search(query="", limit=200, allow_local=True)
    exams: list[dict[str, Any]] = []
    for item in items:
        if item.get("page_type") != "exam":
            continue
        exam, _, _ = _store_get(str(item.get("id") or ""), allow_local=True)
        if exam:
            exams.append(_exam_summary(exam, user_email))
    return {"exams": exams, "backend": backend, "warning": warning}


@app.post("/api/exams")
def create_exam(body: ExamCreateRequest) -> dict[str, Any]:
    questions = _normalize_exam_questions(body.questions)
    exam = {
        "id": uuid.uuid4().hex[:16],
        "page_type": "exam",
        "title": re.sub(r"\s+", " ", body.title).strip(),
        "source_filename": Path(body.source_filename).name if body.source_filename else "",
        "exam_questions": questions,
        "exam_statuses": {},
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
    }
    saved, backend, warning = _store_save(exam, allow_local=True)
    return {"exam": _exam_summary(saved), "backend": backend, "warning": warning}


@app.get("/api/exams/{exam_id}")
def get_exam(exam_id: str, user_email: str = "") -> dict[str, Any]:
    exam, backend, warning = _store_get(exam_id.strip(), allow_local=True)
    if not exam or exam.get("page_type") != "exam":
        raise HTTPException(status_code=404, detail="Exam not found")
    return {"exam": _exam_public_payload(exam, user_email), "backend": backend, "warning": warning}


@app.post("/api/exams/{exam_id}/answer")
def answer_exam_question(exam_id: str, body: ExamAnswerRequest) -> dict[str, Any]:
    exam, _, _ = _store_get(exam_id.strip(), allow_local=True)
    if not exam or exam.get("page_type") != "exam":
        raise HTTPException(status_code=404, detail="Exam not found")
    answer = body.answer.strip().upper()
    if answer not in {"A", "B", "C", "D"}:
        raise HTTPException(status_code=400, detail="Answer must be A, B, C, or D")
    questions = list(exam.get("exam_questions") or [])
    question_index = next((index for index, question in enumerate(questions) if str(question.get("id")) == body.question_id), -1)
    if question_index < 0:
        raise HTTPException(status_code=404, detail="Question not found")
    question = questions[question_index]
    correct_answer = str(question.get("correct_answer") or "").upper()
    user_key = _exam_user_key(body.user_email)
    statuses = dict(exam.get("exam_statuses") or {})
    status = dict(statuses.get(user_key) or {})
    answers = dict(status.get("answers") or {})
    answers[body.question_id] = {
        "answer": answer,
        "correct": answer == correct_answer,
        "correct_answer": correct_answer,
        "answered_at": _utc_now_iso(),
    }
    status.update({
        "user_name": re.sub(r"\s+", " ", body.user_name).strip()[:200],
        "answers": answers,
        "current_index": min(question_index + 1, max(0, len(questions) - 1)),
        "updated_at": _utc_now_iso(),
    })
    statuses[user_key] = status
    exam["exam_statuses"] = statuses
    exam["updated_at"] = _utc_now_iso()
    saved, backend, warning = _store_save(exam, allow_local=True)
    summary = _exam_summary(saved, body.user_email)
    return {"result": answers[body.question_id], "summary": summary, "backend": backend, "warning": warning}


@app.put("/api/exams/{exam_id}/status")
def save_exam_status(exam_id: str, body: ExamStatusRequest) -> dict[str, Any]:
    exam, _, _ = _store_get(exam_id.strip(), allow_local=True)
    if not exam or exam.get("page_type") != "exam":
        raise HTTPException(status_code=404, detail="Exam not found")
    questions = list(exam.get("exam_questions") or [])
    user_key = _exam_user_key(body.user_email)
    statuses = dict(exam.get("exam_statuses") or {})
    status = dict(statuses.get(user_key) or {})
    status.update({
        "user_name": re.sub(r"\s+", " ", body.user_name).strip()[:200],
        "current_index": min(body.current_index, max(0, len(questions) - 1)),
        "updated_at": _utc_now_iso(),
    })
    status.setdefault("answers", {})
    statuses[user_key] = status
    exam["exam_statuses"] = statuses
    exam["updated_at"] = _utc_now_iso()
    saved, backend, warning = _store_save(exam, allow_local=True)
    return {"summary": _exam_summary(saved, body.user_email), "backend": backend, "warning": warning}


@app.get("/api/wiki/list")
def list_wiki_pages(q: str = "", tag: str = "", limit: int = 50) -> dict:
    tag_filter = _normalize_tag_filter(tag)
    items, backend, warn = _store_search(
        query=q,
        tag=tag_filter,
        limit=max(1, min(200, limit)),
        allow_local=True,
    )
    items = [item for item in items if item.get("page_type") not in {"exam", "flashcard_deck"}]
    return {
        "backend": backend,
        "warning": warn,
        "items": items,
        "tag": tag_filter,
        "query": (q or "").strip(),
    }


@app.get("/api/wiki/tags")
def list_wiki_tags(q: str = "", limit: int = 20) -> dict:
    tags, backend, warn = _store_list_tags(
        prefix=q,
        limit=max(1, min(100, limit)),
        allow_local=True,
    )
    return {
        "backend": backend,
        "warning": warn,
        "tags": tags,
        "query": (q or "").strip().lower(),
    }


@app.post("/api/jobs")
def create_job(body: JobCreate) -> dict:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "status": "queued",
            "stage": "queued",
            "progress": 0.0,
            "phase_progress": 0.0,
            "detail": "",
            "error": None,
            "video": None,
            "srt": None,
            "audio": None,
        }
    t = threading.Thread(
        target=_run_job,
        args=(job_id, body.url, body.lang, body.source_lang, body.voice),
        daemon=True,
    )
    t.start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    with _lock:
        j = _jobs.get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Unknown job")
    return {"job_id": job_id, **j}


@app.get("/api/jobs/{job_id}/video")
def download_video(job_id: str) -> FileResponse:
    with _lock:
        j = _jobs.get(job_id)
    if not j or j.get("status") != "done" or not j.get("video"):
        raise HTTPException(status_code=404, detail="Video not ready")
    path = Path(j["video"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(path, filename=path.name, media_type="video/mp4")


@app.get("/api/jobs/{job_id}/subtitles")
def download_subtitles(job_id: str) -> FileResponse:
    with _lock:
        j = _jobs.get(job_id)
    if not j or j.get("status") != "done" or not j.get("srt"):
        raise HTTPException(status_code=404, detail="Subtitles not ready")
    path = Path(j["srt"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(path, filename=path.name, media_type="text/plain")


@app.get("/api/jobs/{job_id}/audio")
def download_audio(job_id: str) -> FileResponse:
    with _lock:
        j = _jobs.get(job_id)
    if not j or j.get("status") != "done" or not j.get("audio"):
        raise HTTPException(status_code=404, detail="Audio not ready")
    path = Path(j["audio"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(path, filename=path.name, media_type="audio/mpeg")


def main() -> None:
    import uvicorn

    uvicorn.run("applimit.web:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
