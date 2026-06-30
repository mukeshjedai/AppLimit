from __future__ import annotations

import logging
import os
from typing import Callable

from applimit.captions import CaptionSegment
from deep_translator import GoogleTranslator

log = logging.getLogger(__name__)

LineProgress = Callable[[int, int], None]

# deep-translator uses ISO-ish codes (e.g. hi, en, ja)
LANG_ALIASES = {
    "hindi": "hi",
    "english": "en",
    "japanese": "ja",
    "korean": "ko",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "chinese": "zh-CN",
    "arabic": "ar",
    "portuguese": "pt",
    "russian": "ru",
}


def normalize_lang(code: str) -> str:
    c = code.strip().lower()
    return LANG_ALIASES.get(c, c)


def _translate_chunk(translator: GoogleTranslator, chunk: list[str]) -> list[str]:
    try:
        return translator.translate_batch(chunk)
    except Exception as e:
        log.warning("translate_batch failed (%s), falling back line-by-line", e)
        out: list[str] = []
        for line in chunk:
            try:
                out.append(translator.translate(line))
            except Exception as e2:
                log.warning("translate line failed: %s", e2)
                out.append(line)
        return out


def translate_segments(
    segments: list[CaptionSegment],
    target_lang: str,
    source_lang: str = "auto",
    on_line_progress: LineProgress | None = None,
) -> list[CaptionSegment]:
    tgt = normalize_lang(target_lang)
    src = "auto" if source_lang in ("auto", "") else normalize_lang(source_lang)
    translator = GoogleTranslator(source=src, target=tgt)
    texts = [s.text for s in segments]
    n = len(texts)
    log.info("Translating %d lines to %s...", n, tgt)
    batch_size = max(1, int(os.environ.get("APPLIMIT_TRANSLATE_BATCH", "8")))
    translated: list[str] = []
    for i in range(0, n, batch_size):
        chunk = texts[i : i + batch_size]
        translated.extend(_translate_chunk(translator, chunk))
        if on_line_progress:
            on_line_progress(min(i + len(chunk), n), n)
    out: list[CaptionSegment] = []
    for a, b in zip(segments, translated, strict=True):
        t = (b or "").strip() or "…"
        out.append(CaptionSegment(start=a.start, end=a.end, text=t))
    return out
