"""Re-transcription of what the agent said out loud (captions, spoken-language check, TTS intelligibility).

BENCH_TRANSCRIBER:
  auto     (default) ElevenLabs Scribe; if it fails (quota, no key) the rest of the process uses local Whisper
  eleven   Scribe only
  whisper  local Whisper large-v3-turbo (mlx-whisper, Apple silicon), free

Whisper is run per phrase (split on pauses) with its language ID restricted to Arabic/English, so a reply that
switches language between sentences is transcribed in both scripts instead of being translated.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess

import aiohttp
import numpy as np

from . import eleven
from .config import SAMPLE_RATE as SR

log = logging.getLogger("bench.transcribe")
_mode = os.environ.get("BENCH_TRANSCRIBER", "auto")
_lock = asyncio.Lock()
used: set[str] = set()  # which backends this process actually used (recorded in metrics)


def _to16k(pcm: np.ndarray) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-v", "quiet", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0",
                        "-f", "s16le", "-ar", "16000", "pipe:1"], input=pcm.astype(np.int16).tobytes(),
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def phrases(a: np.ndarray, sr: int = 16000, min_gap: float = 0.3, min_len: float = 1.2) -> list[np.ndarray]:
    """Split audio on pauses >= min_gap; merge pieces shorter than min_len into their neighbour."""
    hop = int(0.02 * sr)
    n = len(a) // hop
    if n < 10:
        return [a]
    rms = np.sqrt(np.mean(a[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    silent = db < max(-50.0, float(np.percentile(db, 95)) - 30)
    cuts, run = [], 0
    for i, s in enumerate(silent):
        run = run + 1 if s else 0
        if run == int(min_gap / 0.02):
            cuts.append((i - run // 2) * hop)
    bounds = [0, *cuts, len(a)]
    pieces = [a[x:y] for x, y in zip(bounds, bounds[1:]) if y > x]
    merged: list[np.ndarray] = []
    for p in pieces:
        if merged and (len(p) < min_len * sr or len(merged[-1]) < min_len * sr):
            merged[-1] = np.concatenate([merged[-1], p])
        else:
            merged.append(p)
    return merged


def whisper_blocking(pcm: np.ndarray) -> dict:
    from .localspeech import transcribe_array

    texts, dur = [], {}
    for p in phrases(_to16k(pcm)):
        r = transcribe_array(p)
        if r["text"]:
            texts.append(r["text"])
            dur[r["language"]] = dur.get(r["language"], 0) + len(p)
    return {"text": " ".join(texts), "language_code": max(dur, key=dur.get) if dur else None}


async def transcribe(pcm: np.ndarray, http: aiohttp.ClientSession | None = None) -> dict:
    """int16 mono at SAMPLE_RATE -> {'text', 'language_code', 'engine'}."""
    global _mode
    if _mode in ("auto", "eleven"):
        try:
            d = await eleven.scribe(pcm, session=http)
            used.add("elevenlabs-scribe")
            return {"text": d.get("text", ""), "language_code": d.get("language_code"), "engine": "elevenlabs-scribe"}
        except Exception as e:  # noqa: BLE001
            if _mode == "eleven":
                raise
            log.warning("ElevenLabs Scribe failed (%s); using local Whisper for the rest of this run", str(e)[:120])
            _mode = "whisper"
    async with _lock:
        d = await asyncio.to_thread(whisper_blocking, pcm)
    used.add("whisper-large-v3-turbo")
    return {**d, "engine": "whisper-large-v3-turbo"}
