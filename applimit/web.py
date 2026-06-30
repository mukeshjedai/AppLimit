from __future__ import annotations

import html
import json
import logging
import mimetypes
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.background import BackgroundTask
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from applimit.util import extract_video_id
from applimit.wiki_store import AzureWikiStore, LocalWikiStore
from applimit.wiki_paste import paste_to_display_markdown

log = logging.getLogger(__name__)

app = FastAPI(title="AppLimit - YouTube video translator")
BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

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
    auto_fallback_local: bool = Field(
        True, description="If Azure write fails, persist in local store."
    )


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


def _store_search(query: str, limit: int, allow_local: bool = True):
    store, backend, warn = _get_store_with_fallback(allow_local=allow_local)
    try:
        return store.search(query=query, limit=limit), backend, warn
    except Exception as e:
        if allow_local and backend == "azure":
            local = LocalWikiStore()
            return (
                local.search(query=query, limit=limit),
                "local",
                f"Azure search failed ({e}). Showing local pages.",
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
    try:
        results, backend, warn = _store_search(query=q, limit=50, allow_local=True)
        err = warn
    except Exception as e:
        results = []
        backend = "none"
        err = str(e)
    return templates.TemplateResponse(
        request,
        "wiki_index.html",
        {
            "title": "Video Wiki",
            "query": q,
            "results": results,
            "error": err,
            "backend": backend,
            "storage_note": _wiki_storage_note(backend),
        },
    )


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


@app.post("/api/wiki/manual/preview")
def manual_wiki_preview(body: ManualWikiPreviewRequest) -> dict[str, str]:
    return {"markdown": paste_to_display_markdown(body.body)}


@app.post("/api/wiki/manual/save")
def save_manual_wiki(body: ManualWikiSaveRequest) -> dict[str, Any]:
    if not str(body.body).strip():
        raise HTTPException(status_code=400, detail="Body is empty.")
    title = (body.title or "").strip() or "Untitled"
    if body.page_id:
        pid = body.page_id.strip()
        existing, _, _ = _store_get(pid, allow_local=True)
        if not existing:
            raise HTTPException(status_code=404, detail="Wiki page not found")
        if existing.get("page_type") != "manual":
            raise HTTPException(
                status_code=400,
                detail="This page is not a manual notes page.",
            )
        page: dict[str, Any] = {
            **existing,
            **_EMPTY_WIKI_FIELDS,
            "page_type": "manual",
            "title": title,
            "body_raw": body.body,
            "id": pid,
            "created_at": existing.get("created_at") or _utc_now_iso(),
            "updated_at": _utc_now_iso(),
        }
    else:
        page = {
            **_EMPTY_WIKI_FIELDS,
            "page_type": "manual",
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


@app.get("/api/wiki/images/{image_name}")
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
    nb = (body.new_body or "").strip()
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


@app.get("/api/wiki/list")
def list_wiki_pages(q: str = "", limit: int = 50) -> dict:
    items, backend, warn = _store_search(
        query=q, limit=max(1, min(200, limit)), allow_local=True
    )
    return {"backend": backend, "warning": warn, "items": items}


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
