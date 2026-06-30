from __future__ import annotations

import logging
from dataclasses import dataclass

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import CouldNotRetrieveTranscript

log = logging.getLogger(__name__)


@dataclass
class CaptionSegment:
    start: float
    end: float
    text: str


def _to_segments_from_fetched(ft) -> list[CaptionSegment]:
    out: list[CaptionSegment] = []
    for sn in ft:
        text = (sn.text or "").replace("\n", " ").strip()
        if not text:
            continue
        start = float(sn.start)
        dur = float(getattr(sn, "duration", 0.0) or 0.0)
        end = start + dur if dur > 0 else start + 2.0
        out.append(CaptionSegment(start=start, end=end, text=text))
    return out


def try_fetch_transcript(
    video_id: str,
    preferred_langs: tuple[str, ...] = (
        "en",
        "en-US",
        "en-GB",
        "hi",
    ),
) -> list[CaptionSegment] | None:
    """
    Return timed segments from YouTube captions when available (fast path).
    """
    try:
        api = YouTubeTranscriptApi()
        ft = api.fetch(video_id, languages=list(preferred_langs))
    except CouldNotRetrieveTranscript as e:
        log.info("No usable transcript: %s", e)
        return None
    except Exception as e:
        log.info("Transcript fetch failed: %s", e)
        return None

    segs = _to_segments_from_fetched(ft)
    return segs if segs else None
