from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from applimit.captions import CaptionSegment, try_fetch_transcript

log = logging.getLogger(__name__)

WhisperProgress = Callable[[float, str], None]
"""(phase_0_1, detail)"""


def segments_to_caption_format(segments: list) -> list[CaptionSegment]:
    """Normalize faster-whisper segments to CaptionSegment."""
    out: list[CaptionSegment] = []
    for s in segments:
        text = getattr(s, "text", None) or ""
        text = text.strip()
        if not text:
            continue
        start = float(getattr(s, "start"))
        end = float(getattr(s, "end"))
        out.append(CaptionSegment(start=start, end=end, text=text))
    return out


def transcribe_audio(
    audio_path: Path,
    model_size: str | None = None,
    device: str = "auto",
    compute_type: str | None = None,
    on_progress: WhisperProgress | None = None,
) -> list[CaptionSegment]:
    """Transcribe audio file with faster-whisper (slower than captions, works without subs)."""
    from faster_whisper import WhisperModel

    def tick(p: float, msg: str) -> None:
        if on_progress:
            on_progress(max(0.0, min(1.0, p)), msg)

    size = model_size or os.environ.get("APPLIMIT_WHISPER_MODEL", "small")
    ct = compute_type if compute_type is not None else os.environ.get(
        "APPLIMIT_WHISPER_COMPUTE", "default"
    )
    tick(0.02, f"Loading Whisper ({size})…")
    model = WhisperModel(size, device=device, compute_type=ct)
    tick(0.08, "Transcribing audio…")
    segments_gen, info = model.transcribe(
        str(audio_path),
        vad_filter=True,
        word_timestamps=False,
    )
    total_dur = float(getattr(info, "duration", 0.0) or 0.0)
    raw: list = []
    for seg in segments_gen:
        raw.append(seg)
        if total_dur > 0 and on_progress:
            t = max(0.0, float(getattr(seg, "end", 0.0)))
            p = 0.08 + 0.92 * min(1.0, t / total_dur)
            tick(p, f"Speech → text {t:.0f}s / {total_dur:.0f}s")
    tick(1.0, "Transcription complete")
    return segments_to_caption_format(raw)


def extract_wav_16k(video_path: Path, wav_out: Path) -> Path:
    """Extract mono 16kHz WAV for Whisper."""
    import subprocess

    wav_out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav_out),
        ],
        check=True,
        capture_output=True,
    )
    return wav_out


def get_segments(
    video_id: str,
    video_path: Path,
    work_dir: Path,
    prefer_captions: bool = True,
    whisper_model: str | None = None,
    on_transcribe: WhisperProgress | None = None,
) -> list[CaptionSegment]:
    def tick(p: float, msg: str) -> None:
        if on_transcribe:
            on_transcribe(p, msg)

    if prefer_captions:
        tick(0.0, "Fetching YouTube captions…")
        caps = try_fetch_transcript(video_id)
        if caps:
            tick(1.0, f"Using captions ({len(caps)} cues)")
            log.info("Using YouTube captions (%d segments)", len(caps))
            return caps
        tick(0.04, "No captions — preparing speech recognition…")

    tick(0.06, "Extracting audio for Whisper…")
    wav = work_dir / "speech_16k.wav"
    extract_wav_16k(video_path, wav)

    def whisper_tick(wp: float, msg: str) -> None:
        tick(0.1 + 0.9 * wp, msg)

    return transcribe_audio(wav, model_size=whisper_model, on_progress=whisper_tick)
