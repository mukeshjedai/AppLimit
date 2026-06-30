from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path

from pydub import AudioSegment

from applimit.captions import CaptionSegment
from applimit.util import ffprobe_duration_seconds, require_ffmpeg

log = logging.getLogger(__name__)


def _fit_duration(seg: AudioSegment, target_ms: int) -> AudioSegment:
    if target_ms <= 0:
        return AudioSegment.silent(duration=0)
    cur = len(seg)
    if cur == 0:
        return AudioSegment.silent(duration=target_ms)
    if cur <= target_ms:
        pad = target_ms - cur
        return seg + AudioSegment.silent(duration=pad)
    # Speed up to fit (chain if factor > 2; pydub speedup is limited per call)
    factor = cur / target_ms
    out = seg
    while factor > 2.0 + 1e-6:
        out = out.speedup(playback_speed=2.0)
        factor = len(out) / target_ms
    if factor > 1.001:
        out = out.speedup(playback_speed=factor)
    # Trim if still long
    if len(out) > target_ms:
        out = out[:target_ms]
    return out


def build_timeline_audio(
    segments: list[CaptionSegment],
    mp3_paths: list[Path],
    total_duration_sec: float,
) -> AudioSegment:
    if len(segments) != len(mp3_paths):
        raise ValueError("segments and mp3_paths length mismatch")
    total_ms = max(int(math.ceil(total_duration_sec * 1000)), 1)
    mixed = AudioSegment.silent(duration=total_ms)
    for seg, mp3 in zip(segments, mp3_paths, strict=True):
        try:
            clip = AudioSegment.from_file(str(mp3), format="mp3")
        except Exception as e:
            log.warning("Skipping bad TTS file %s: %s", mp3, e)
            continue
        start_ms = int(max(0, seg.start) * 1000)
        end_ms = int(max(seg.start, seg.end) * 1000)
        slot = max(end_ms - start_ms, 1)
        fitted = _fit_duration(clip, slot)
        pos = min(start_ms, total_ms - len(fitted))
        if pos < 0:
            pos = 0
        mixed = mixed.overlay(fitted, position=pos)
    return mixed


def mux_video_audio(
    video_path: Path,
    audio_wav_or_mp3: Path,
    out_path: Path,
) -> Path:
    require_ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_wav_or_mp3),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def write_srt(segments: list[CaptionSegment], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    def ts(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{ts(seg.start)} --> {ts(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def pad_or_trim_audio(audio: AudioSegment, duration_sec: float) -> AudioSegment:
    need_ms = max(int(round(duration_sec * 1000)), 1)
    if len(audio) >= need_ms:
        return audio[:need_ms]
    return audio + AudioSegment.silent(duration=need_ms - len(audio))


def export_audio_wav(audio: AudioSegment, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    audio.export(str(path), format="wav")
    return path


def export_audio_mp3(audio: AudioSegment, path: Path, bitrate: str = "128k") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    audio.export(str(path), format="mp3", bitrate=bitrate)
    return path
