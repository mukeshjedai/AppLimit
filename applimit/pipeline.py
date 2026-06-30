from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from applimit import compose, download, transcribe, translate, tts
from applimit.progress import ProgressTracker
from applimit.util import extract_video_id, ffprobe_duration_seconds

log = logging.getLogger(__name__)

ProgressCb = Callable[[str, float, float, str], None]
"""(stage, phase_frac, overall_frac, detail)"""


@dataclass
class PipelineResult:
    video_out: Path
    subtitles_srt: Path
    audio_out: Path


def run(
    url: str,
    output_dir: Path,
    target_lang: str = "hi",
    source_lang: str = "auto",
    voice: str | None = None,
    whisper_model: str | None = None,
    on_progress: ProgressCb | None = None,
) -> PipelineResult:
    tracker = ProgressTracker(on_progress)

    def report(stage: str, phase: float, detail: str = "") -> None:
        tracker.fire(stage, phase, detail)

    vid = extract_video_id(url)
    if not vid:
        raise ValueError("Could not parse a YouTube video id from the URL.")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix="applimit_"))
    try:
        report("download", 0.0, "Queued…")

        def dl_prog(p: float, d: str) -> None:
            report("download", p, d)

        src_mp4 = download.download_video(url, work, "source", on_progress=dl_prog)
        report("download", 1.0, "Download complete")

        report("transcribe", 0.0, "Starting…")

        def tr_prog(p: float, d: str) -> None:
            report("transcribe", p, d)

        segments = transcribe.get_segments(
            vid,
            src_mp4,
            work,
            prefer_captions=True,
            whisper_model=whisper_model,
            on_transcribe=tr_prog,
        )
        if not segments:
            raise RuntimeError("No speech segments produced.")
        report("transcribe", 1.0, f"{len(segments)} segments")

        nlines = len(segments)
        lang_norm = translate.normalize_lang(target_lang)
        report("translate", 0.0, f"0 / {nlines} lines")

        translated = translate.translate_segments(
            segments,
            target_lang=lang_norm,
            source_lang=source_lang,
            on_line_progress=lambda done, total: report(
                "translate",
                done / total if total else 1.0,
                f"{done} / {total} lines",
            ),
        )
        report("translate", 1.0, f"{nlines} lines done")

        voice_name = tts.voice_for_lang(lang_norm, voice)
        tts_dir = work / "tts_chunks"
        nseg = len(translated)
        report("tts", 0.0, f"0 / {nseg} clips")

        mp3s = tts.synthesize_segments(
            translated,
            voice_name,
            tts_dir,
            on_segment_progress=lambda done, total: report(
                "tts",
                done / total if total else 1.0,
                f"{done} / {total} voice clips",
            ),
        )
        report("tts", 1.0, f"{nseg} clips done")

        report("mux", 0.0, "Building audio timeline…")
        dur = ffprobe_duration_seconds(src_mp4)
        mixed = compose.build_timeline_audio(translated, mp3s, dur)
        report("mux", 0.35, "Normalizing length…")
        mixed = compose.pad_or_trim_audio(mixed, dur)
        wav_path = work / "dub.wav"
        report("mux", 0.55, "Writing WAV…")
        compose.export_audio_wav(mixed, wav_path)
        audio_dest = output_dir / f"translated_{lang_norm}.mp3"
        report("mux", 0.62, "Exporting translated audio…")
        compose.export_audio_mp3(mixed, audio_dest)
        temp_out = work / f"video_{lang_norm}.mp4"
        report("mux", 0.7, "Muxing video + audio (ffmpeg)…")
        compose.mux_video_audio(src_mp4, wav_path, temp_out)
        srt_work = work / f"subtitles_{lang_norm}.srt"
        report("mux", 0.9, "Writing subtitles…")
        compose.write_srt(translated, srt_work)
        report("mux", 1.0, "Mux complete")

        video_dest = output_dir / f"translated_{lang_norm}.mp4"
        srt_dest = output_dir / f"subtitles_{lang_norm}.srt"
        shutil.copy2(temp_out, video_dest)
        shutil.copy2(srt_work, srt_dest)

        return PipelineResult(
            video_out=video_dest,
            subtitles_srt=srt_dest,
            audio_out=audio_dest,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
