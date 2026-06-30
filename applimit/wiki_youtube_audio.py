from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def ensure_original_audio_file(source_url: str, page_id: str, out_dir: Path) -> Path:
    """
    Download best-quality audio from YouTube (original track), cache under out_dir.
    Returns path to the audio file (extension depends on source; often .m4a or .webm).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = f"{page_id}_original.*"
    existing = list(out_dir.glob(pattern))
    if existing:
        return max(existing, key=lambda p: p.stat().st_mtime)

    from yt_dlp import YoutubeDL

    out_template = str(out_dir / f"{page_id}_original.%(ext)s")
    ydl_opts: dict = {
        "format": "bestaudio/ba/b",
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    log.info("Fetching original audio for wiki page %s", page_id)
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([source_url])

    after = list(out_dir.glob(pattern))
    if not after:
        raise FileNotFoundError(f"No audio file written for {page_id}")
    return max(after, key=lambda p: p.stat().st_mtime)


def guess_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".mp4": "audio/mp4",
        ".webm": "audio/webm",
        ".opus": "audio/opus",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
    }.get(ext, "application/octet-stream")
