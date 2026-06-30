from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

DownloadProgress = Callable[[float, str], None]
"""(phase_frac_0_1, detail)"""


def download_video(
    url: str,
    out_dir: Path,
    out_name: str = "source",
    on_progress: DownloadProgress | None = None,
) -> Path:
    """
    Download best video+audio muxed to mp4 using yt-dlp (Python API for progress hooks).
    """
    from yt_dlp import YoutubeDL

    out_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(out_dir / f"{out_name}.%(ext)s")

    files_done = [0]
    best = [0.0]

    def hook(d: dict) -> None:
        if not on_progress:
            return
        st = d.get("status")
        if st == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = float(d.get("downloaded_bytes") or 0)
            if total:
                cur = got / float(total)
                # Up to two streams (e.g. video + audio) before merge; stay monotonic across files.
                base = files_done[0] / 2.0
                frac = base + cur / 2.0
                best[0] = max(best[0], 0.02 + 0.93 * frac)
                mb = got / (1024 * 1024)
                tot_mb = float(total) / (1024 * 1024)
                on_progress(best[0], f"Download {mb:.1f} / {tot_mb:.1f} MiB")
            else:
                best[0] = max(best[0], 0.02)
                on_progress(best[0], "Downloading…")
        elif st == "finished":
            files_done[0] = min(2, files_done[0] + 1)
            best[0] = max(best[0], 0.02 + 0.93 * (files_done[0] / 2.0))
            on_progress(best[0], "Merging streams…")

    ydl_opts: dict = {
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
    }
    log.info("Running yt-dlp…")
    if on_progress:
        on_progress(0.0, "Starting download…")
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    if on_progress:
        on_progress(1.0, "Download complete")

    mp4 = out_dir / f"{out_name}.mp4"
    if not mp4.is_file():
        raise FileNotFoundError(f"Expected output not found: {mp4}")
    return mp4
