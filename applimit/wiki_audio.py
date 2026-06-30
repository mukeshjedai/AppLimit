from __future__ import annotations

import asyncio
import os
from pathlib import Path

import edge_tts
from openai import OpenAI


def _chunk_text(text: str, max_chars: int = 1800) -> list[str]:
    base = " ".join((text or "").split()).strip()
    if not base:
        return []
    words = base.split(" ")
    out: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for w in words:
        add = len(w) + (1 if cur else 0)
        if cur and cur_len + add > max_chars:
            out.append(" ".join(cur))
            cur = [w]
            cur_len = len(w)
        else:
            cur.append(w)
            cur_len += add
    if cur:
        out.append(" ".join(cur))
    return out


def translate_text_to_hindi_openai(text: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    chunks = _chunk_text(text, max_chars=1800)
    if not chunks:
        raise RuntimeError("No transcript text available for Hindi translation.")

    model = os.environ.get("APPLIMIT_OPENAI_MODEL", "gpt-4.1-mini")
    client = OpenAI(api_key=api_key)
    out: list[str] = []
    for c in chunks:
        resp = client.chat.completions.create(
            model=model,
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": "Translate to natural Hindi only. Keep meaning accurate. Return plain Hindi text only.",
                },
                {"role": "user", "content": c},
            ],
        )
        out.append((resp.choices[0].message.content or "").strip())
    return "\n".join(x for x in out if x)


async def _edge_tts_to_mp3_bytes(text: str, voice: str) -> bytes:
    """Edge TTS only — no ffmpeg/pydub (required for Azure Functions Linux images)."""
    communicate = edge_tts.Communicate(text or "...", voice)
    out = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            out.extend(chunk["data"])
    return bytes(out)


def synthesize_hindi_mp3(translated_hindi_text: str, out_mp3: Path) -> Path:
    """Merge Hindi TTS chunks via Edge stream bytes only (no ffmpeg/pydub — works on Azure Functions)."""
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    voice = os.environ.get("APPLIMIT_EDGE_VOICE_HINDI", "hi-IN-SwaraNeural")
    chunks = _chunk_text(translated_hindi_text, max_chars=900)
    if not chunks:
        raise RuntimeError("Translated Hindi text is empty.")

    async def _build() -> bytes:
        parts: list[bytes] = []
        for c in chunks:
            parts.append(await _edge_tts_to_mp3_bytes(c, voice))
        return b"".join(parts)

    out_mp3.write_bytes(asyncio.run(_build()))
    return out_mp3


def synthesize_read_aloud_mp3(
    text: str,
    out_mp3: Path,
    *,
    voice: str,
) -> Path:
    """Speak plain text with Edge TTS only (chunked); repeat playback is done in the browser."""
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    base = " ".join((text or "").split()).strip() or "..."
    chunks = _chunk_text(base, max_chars=900)
    if not chunks:
        raise RuntimeError("No text to speak.")

    async def _build() -> bytes:
        parts: list[bytes] = []
        for c in chunks:
            parts.append(await _edge_tts_to_mp3_bytes(c, voice))
        return b"".join(parts)

    out_mp3.write_bytes(asyncio.run(_build()))
    return out_mp3

