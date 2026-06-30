from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable

import edge_tts
from pydub import AudioSegment

from applimit.captions import CaptionSegment

log = logging.getLogger(__name__)

SegmentProgress = Callable[[int, int], None]

# Default neural voices (Microsoft Edge TTS). Override with APPLIMIT_EDGE_VOICE.
DEFAULT_VOICE_BY_LANG = {
    "hi": "hi-IN-SwaraNeural",
    "en": "en-US-AriaNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "zh-cn": "zh-CN-XiaoxiaoNeural",
    "ar": "ar-SA-ZariyahNeural",
    "pt": "pt-BR-FranciscaNeural",
    "ru": "ru-RU-SvetlanaNeural",
}


def voice_for_lang(lang_code: str, override: str | None = None) -> str:
    if override:
        return override
    env = os.environ.get("APPLIMIT_EDGE_VOICE")
    if env:
        return env
    key = lang_code.lower().strip()
    return DEFAULT_VOICE_BY_LANG.get(key, DEFAULT_VOICE_BY_LANG["hi"])


async def _synthesize_one(text: str, voice: str, out_path: Path) -> None:
    safe_text = (text or "").strip()
    if not safe_text:
        safe_text = "..."

    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(safe_text, voice)
            await communicate.save(str(out_path))
            if out_path.is_file() and out_path.stat().st_size > 0:
                return
        except Exception as e:
            if attempt == 2:
                log.warning("TTS failed for one segment: %s", e)
            await asyncio.sleep(0.5 * (attempt + 1))

    # Avoid failing the whole job on one bad segment.
    AudioSegment.silent(duration=300).export(str(out_path), format="mp3")


async def synthesize_segments_async(
    segments: list[CaptionSegment],
    voice: str,
    out_dir: Path,
    concurrency: int = 3,
    on_segment_progress: SegmentProgress | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    total = len(segments)
    done = 0
    lock = asyncio.Lock()

    async def one(i: int, seg: CaptionSegment) -> Path:
        nonlocal done
        async with sem:
            p = out_dir / f"tts_{i:05d}.mp3"
            await _synthesize_one(seg.text, voice, p)
        if on_segment_progress:
            async with lock:
                done += 1
                on_segment_progress(done, total)
        return p

    tasks = [one(i, s) for i, s in enumerate(segments)]
    return await asyncio.gather(*tasks)


def synthesize_segments(
    segments: list[CaptionSegment],
    voice: str,
    out_dir: Path,
    concurrency: int | None = None,
    on_segment_progress: SegmentProgress | None = None,
) -> list[Path]:
    conc = concurrency if concurrency is not None else max(
        3, int(os.environ.get("APPLIMIT_TTS_CONCURRENCY", "6"))
    )
    return asyncio.run(
        synthesize_segments_async(
            segments, voice, out_dir, conc, on_segment_progress
        )
    )
