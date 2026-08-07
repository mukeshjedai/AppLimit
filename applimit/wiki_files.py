from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

MAX_WIKI_FILE_BYTES = 50 * 1024 * 1024

ALLOWED_FILE_EXTENSIONS = {
    ".7z",
    ".aac",
    ".avi",
    ".csv",
    ".doc",
    ".docx",
    ".flac",
    ".gif",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".odp",
    ".ods",
    ".odt",
    ".ogg",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".rtf",
    ".svg",
    ".tar",
    ".txt",
    ".wav",
    ".webm",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
}

BLOCKED_FILE_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".exe",
    ".htm",
    ".html",
    ".js",
    ".mjs",
    ".msi",
    ".ps1",
    ".scr",
    ".sh",
    ".vbs",
    ".wsf",
}


def wiki_file_dir() -> Path:
    root = Path.cwd() / "wiki-files"
    root.mkdir(parents=True, exist_ok=True)
    return root


def wiki_file_path(file_id: str) -> Path:
    clean = Path(file_id).name
    if clean != file_id or not clean:
        raise HTTPException(status_code=404, detail="File not found")
    return wiki_file_dir() / clean


def wiki_file_blob_name(file_id: str) -> str:
    clean = Path(file_id).name
    if clean != file_id or not clean:
        raise HTTPException(status_code=404, detail="File not found")
    return f"files/{clean}"


def file_media_type(file_id: str) -> str:
    return mimetypes.guess_type(file_id)[0] or "application/octet-stream"


def sanitize_original_filename(name: str) -> str:
    base = Path(name or "file").name
    base = re.sub(r"[^\w.\- ()\[\]]+", "_", base).strip("._ ")
    return base[:180] or "file"


def validate_upload_filename(filename: str) -> str:
    original = sanitize_original_filename(filename)
    ext = Path(original).suffix.lower()
    if not ext:
        raise HTTPException(status_code=400, detail="File must have an extension.")
    if ext in BLOCKED_FILE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {ext} is not allowed.")
    if ext not in ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Use pdf, docx, xlsx, pptx, zip, txt, md, csv, audio, video, or common image formats.",
        )
    return original


def is_image_upload(file: UploadFile, original_name: str) -> bool:
    if file.content_type and file.content_type.startswith("image/"):
        return True
    return Path(original_name).suffix.lower() in {".apng", ".avif", ".gif", ".jpg", ".jpeg", ".png", ".webp"}


def new_file_id(original_name: str) -> str:
    ext = Path(original_name).suffix.lower()
    return f"{uuid.uuid4().hex[:14]}{ext}"


def build_attachment_record(
    *,
    file_id: str,
    original_name: str,
    size: int,
    content_type: str,
    uploaded_at: str,
) -> dict[str, Any]:
    return {
        "id": file_id,
        "filename": original_name,
        "size": size,
        "content_type": content_type,
        "uploaded_at": uploaded_at,
        "url": f"/api/wiki/files/{file_id}",
    }


def build_file_markdown_link(original_name: str, url: str) -> str:
    label = original_name.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return f"[{label}]({url})"


def page_attachments(page: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not page:
        return []
    raw = page.get("attachments")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and item.get("id"):
            out.append(item)
    return out
