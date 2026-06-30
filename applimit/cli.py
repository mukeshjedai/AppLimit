from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from applimit.pipeline import run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Download a YouTube video, translate speech to a target language, "
        "synthesize dubbed audio (Edge TTS), mux to MP4, and export SRT subtitles."
    )
    p.add_argument("url", help="YouTube URL or 11-character video id")
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("out"),
        help="Directory for translated MP4 and SRT (default: ./out)",
    )
    p.add_argument(
        "-l",
        "--lang",
        default="hi",
        help="Target language code (default: hi). Examples: hi, en, ja, es",
    )
    p.add_argument(
        "--source-lang",
        default="auto",
        help="Source language for translation (default: auto)",
    )
    p.add_argument(
        "--voice",
        default=None,
        help="Edge TTS voice name, e.g. hi-IN-MadhurNeural (default: language default)",
    )
    p.add_argument(
        "--whisper-model",
        default=None,
        help="faster-whisper model when captions are unavailable (tiny, base, small, ...)",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    def on_progress(
        stage: str, phase: float, overall: float, detail: str
    ) -> None:
        extra = f" — {detail}" if detail else ""
        logging.info(
            "[%s] phase %5.1f%% | overall %5.1f%%%s",
            stage,
            100 * phase,
            100 * overall,
            extra,
        )

    try:
        res = run(
            args.url,
            output_dir=args.output_dir,
            target_lang=args.lang,
            source_lang=args.source_lang,
            voice=args.voice,
            whisper_model=args.whisper_model,
            on_progress=on_progress,
        )
    except Exception as e:
        logging.error("%s", e)
        return 1

    print("Done.")
    print("Video:", res.video_out)
    print("Subtitles:", res.subtitles_srt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
