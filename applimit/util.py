from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse


_YT_HOSTS = ("youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com")


def extract_video_id(url: str) -> str | None:
    """Parse a YouTube URL or ID into an 11-character video id."""
    u = url.strip()
    if re.fullmatch(r"[\w-]{11}", u):
        return u
    parsed = urlparse(u)
    host = (parsed.hostname or "").lower()
    if host.endswith("youtu.be"):
        seg = parsed.path.strip("/").split("/")[0]
        return seg[:11] if len(seg) >= 11 else None
    if "youtube" in host:
        if parsed.path == "/watch":
            q = parse_qs(parsed.query)
            v = q.get("v", [None])[0]
            return v[:11] if v and len(v) >= 11 else None
        m = re.match(r"^/shorts/([\w-]{11})", parsed.path)
        if m:
            return m.group(1)
        m = re.match(r"^/embed/([\w-]{11})", parsed.path)
        if m:
            return m.group(1)
    return None


def require_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install ffmpeg and ensure it is available in your shell."
        )
    return exe


def ffprobe_duration_seconds(path: Path) -> float:
    require_ffmpeg()
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(r.stdout.strip())


def is_youtube_url(url: str) -> bool:
    try:
        p = urlparse(url.strip())
        h = (p.hostname or "").lower()
        return any(h == x or h.endswith("." + x) for x in ("youtube.com", "youtu.be"))
    except Exception:
        return False
