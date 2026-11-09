"""ElevenLabs helpers for the caller: TTS (with an on-disk cache so every stack hears
byte-identical audio in scripted mode) and Scribe batch speech-to-text (used to check
what the agent-under-test actually *said* out loud)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import wave
from pathlib import Path

import aiohttp
import numpy as np

from .config import CACHE_DIR, SAMPLE_RATE, eleven_key

API = "https://api.elevenlabs.io/v1"
# The account allows 3 concurrent requests; keep 1 free for a stack under test that uses ElevenLabs.
_SEM = asyncio.Semaphore(2)
FALLBACKS: list[str] = []  # caller lines spoken by the local fallback voice this process


async def _request(session: aiohttp.ClientSession, method: str, url: str, **kw):  # noqa: ANN201
    """POST with retry on 429 (concurrency / rate limit) and 5xx."""
    for attempt in range(6):
        async with _SEM:
            async with session.request(method, url, **kw) as r:
                if r.status == 429 or r.status >= 500:
                    body = await r.text()
                    if attempt < 5:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    raise RuntimeError(f"ElevenLabs {r.status}: {body[:300]}")
                return r.status, await r.read()
    raise RuntimeError("unreachable")


def _cache_path(voice: str, model: str, text: str, settings: dict | None) -> Path:
    h = hashlib.sha1(json.dumps([voice, model, text, settings or {}], ensure_ascii=False).encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.pcm"


async def tts_pcm(
    text: str,
    *,
    voice: str,
    model: str = "eleven_multilingual_v2",
    settings: dict | None = None,
    use_cache: bool = True,
    session: aiohttp.ClientSession | None = None,
) -> np.ndarray:
    """Synthesize text to int16 mono PCM at SAMPLE_RATE."""
    path = _cache_path(voice, model, text, settings)
    if use_cache and path.exists():
        return np.frombuffer(path.read_bytes(), dtype=np.int16)
    body: dict = {"text": text, "model_id": model}
    if settings:
        body["voice_settings"] = settings
    own = session is None
    session = session or aiohttp.ClientSession()
    try:
        status, raw = await _request(
            session,
            "POST",
            f"{API}/text-to-speech/{voice}?output_format=pcm_{SAMPLE_RATE}",
            headers={"xi-api-key": eleven_key(), "Content-Type": "application/json"},
            json=body,
            timeout=aiohttp.ClientTimeout(total=60),
        )
        if status != 200:
            raise RuntimeError(f"ElevenLabs TTS {status}: {raw[:300]!r}")
        pcm = np.frombuffer(raw, dtype=np.int16)
    except Exception as e:  # noqa: BLE001
        if os.environ.get("BENCH_CALLER_TTS_FALLBACK", "1") == "0":
            raise
        # quota/key problems: fall back to the local macOS voices so the call still runs (logged; not cached)
        logging.getLogger("bench.eleven").warning("caller TTS via ElevenLabs failed (%s); using local voice", str(e)[:120])
        from .localspeech import synthesize

        with wave.open(io.BytesIO(await asyncio.to_thread(synthesize, text))) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        FALLBACKS.append(text)
        use_cache = False
    finally:
        if own:
            await session.close()
    # Trim leading/trailing digital silence so utterance timing is exact.
    nz = np.flatnonzero(np.abs(pcm) > 200)
    if len(nz):
        pad = int(0.03 * SAMPLE_RATE)
        pcm = pcm[max(0, nz[0] - pad) : min(len(pcm), nz[-1] + pad)]
    if use_cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pcm.tobytes())
    return pcm


def pcm_to_wav_bytes(pcm: np.ndarray, sr: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.astype(np.int16).tobytes())
    return buf.getvalue()


async def scribe(
    pcm: np.ndarray,
    *,
    model: str = "scribe_v2",
    language: str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> dict:
    """Batch transcription. Returns {'text', 'language_code', ...}."""
    wav = pcm_to_wav_bytes(pcm)

    def form() -> aiohttp.FormData:
        f = aiohttp.FormData()
        f.add_field("model_id", model)
        f.add_field("tag_audio_events", "false")
        if language:
            f.add_field("language_code", language)
        f.add_field("file", wav, filename="seg.wav", content_type="audio/wav")
        return f

    own = session is None
    session = session or aiohttp.ClientSession()
    try:
        for attempt in range(6):
            async with _SEM:
                async with session.post(
                    f"{API}/speech-to-text",
                    headers={"xi-api-key": eleven_key()},
                    data=form(),
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as r:
                    data = await r.json(content_type=None)
                    if (r.status == 429 or r.status >= 500) and attempt < 5:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    if r.status != 200:
                        raise RuntimeError(f"Scribe {r.status}: {str(data)[:300]}")
                    return data
        raise RuntimeError("Scribe: retries exhausted")
    finally:
        if own:
            await session.close()
