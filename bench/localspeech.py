"""A free, local, OpenAI-compatible speech server, so calls run without any cloud speech credits.

    .venv/bin/python -m bench speech            # serves http://127.0.0.1:8770/v1 (bench run starts it when needed)

  POST /v1/audio/transcriptions   Whisper large-v3-turbo on Apple silicon (mlx-whisper), OpenAI response shape
  POST /v1/audio/speech           macOS voices: Arabic runs read by Majed (ar_001), Latin runs by Samantha (en_US),
                                  so code-switched replies are read by the right voice per phrase; returns WAV
  GET  /health

Stacks use it through the openai plugin (`stt: {plugin: openai, base_url: http://127.0.0.1:8770/v1, model: whisper-1}`,
`services: [localspeech]`). It is a baseline, not a product: published comparisons should label it "local".
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
from aiohttp import web

PORT = int(os.environ.get("BENCH_LOCALSPEECH_PORT", "8770"))
URL = f"http://127.0.0.1:{PORT}/v1"
WHISPER = os.environ.get("BENCH_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
VOICES = {"ar": os.environ.get("BENCH_SAY_AR", "Majed"), "en": os.environ.get("BENCH_SAY_EN", "Samantha")}
SR = 24000
_AR = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LAT = re.compile(r"[A-Za-z]")
_lock = asyncio.Lock()  # mlx is not re-entrant: one transcription at a time


# --------------------------------------------------------------------------- speech-to-text


def _decode(raw: bytes) -> np.ndarray:
    """Any audio container -> float32 mono 16 kHz (ffmpeg)."""
    p = subprocess.run(["ffmpeg", "-v", "quiet", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"],
                       input=raw, capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0


LANGS = [x for x in os.environ.get("BENCH_WHISPER_LANGS", "ar,en").split(",") if x]


def detect(audio: np.ndarray) -> str:
    """Whisper's language ID restricted to LANGS (unrestricted, it often picks English and translates Arabic)."""
    import mlx.core as mx
    from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim
    from mlx_whisper.transcribe import ModelHolder

    model = ModelHolder.get_model(WHISPER, mx.float16)
    mel = log_mel_spectrogram(audio, n_mels=model.dims.n_mels, padding=N_SAMPLES)
    seg = pad_or_trim(mel[:N_FRAMES], N_FRAMES, axis=-2).astype(mx.float16)
    _, probs = model.detect_language(seg)
    return max(LANGS, key=lambda k: probs.get(k, 0.0))


def transcribe_array(audio: np.ndarray, language: str | None = None, prompt: str | None = None) -> dict:
    """Blocking Whisper call on float32 16 kHz audio -> {'text', 'language'}."""
    import mlx_whisper

    if audio.size < 1600:
        return {"text": "", "language": language or "en"}
    if not language and LANGS:
        language = detect(audio)
    out = mlx_whisper.transcribe(audio, path_or_hf_repo=WHISPER, language=language or None,
                                 initial_prompt=prompt or None, condition_on_previous_text=False,
                                 temperature=0.0, no_speech_threshold=0.6, verbose=None)
    return {"text": (out.get("text") or "").strip(), "language": out.get("language") or language or ""}


async def _stt(request: web.Request) -> web.Response:
    form = await request.post()
    f = form.get("file")
    raw = f.file.read() if hasattr(f, "file") else bytes(f or b"")
    language = (form.get("language") or "").split("-")[0] or None
    audio = await asyncio.to_thread(_decode, raw)
    async with _lock:
        res = await asyncio.to_thread(transcribe_array, audio, language, form.get("prompt") or None)
    fmt = form.get("response_format") or "json"
    if fmt == "text":
        return web.Response(text=res["text"])
    body = {"text": res["text"]}
    if fmt == "verbose_json":
        body.update(language=res["language"], duration=round(audio.size / 16000, 3), segments=[])
    return web.json_response(body)


# --------------------------------------------------------------------------- text-to-speech


def runs(text: str) -> list[tuple[str, str]]:
    """Split text into (lang, phrase) runs by script; digits/punctuation stay with the run they sit in."""
    out: list[tuple[str, str]] = []
    cur, buf = None, ""
    for word in re.split(r"(\s+)", text):
        na, nl = len(_AR.findall(word)), len(_LAT.findall(word))
        lang = "ar" if na > nl else "en" if nl else None
        if lang and cur and lang != cur and buf.strip():
            out.append((cur, buf.strip()))
            buf = ""
        cur = lang or cur
        buf += word
    if buf.strip():
        out.append((cur or "en", buf.strip()))
    return out


def _say(lang: str, phrase: str, rate: int | None) -> np.ndarray:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "s.wav"
        cmd = ["say", "-v", VOICES[lang], "--file-format=WAVE", f"--data-format=LEI16@{SR}", "-o", str(out)]
        if rate:
            cmd += ["-r", str(rate)]
        subprocess.run([*cmd, phrase], check=True, capture_output=True)
        with wave.open(str(out)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def synthesize(text: str, speed: float = 1.0) -> bytes:
    rate = int(185 * speed) if speed and speed != 1.0 else None
    gap = np.zeros(int(0.06 * SR), dtype=np.int16)
    parts: list[np.ndarray] = []
    for lang, phrase in runs(text):
        parts += [_say(lang, phrase, rate), gap]
    pcm = np.concatenate(parts) if parts else np.zeros(int(0.1 * SR), dtype=np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


async def _tts(request: web.Request) -> web.Response:
    body = await request.json()
    wav = await asyncio.to_thread(synthesize, body.get("input", ""), float(body.get("speed") or 1.0))
    return web.Response(body=wav, content_type="audio/wav")


async def _health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True, "whisper": WHISPER, "voices": VOICES})


def serve(port: int = PORT) -> None:
    print(f"warming up {WHISPER} ...", flush=True)
    transcribe_array(np.zeros(16000 * 2, dtype=np.float32) + 1e-4, "en")
    app = web.Application(client_max_size=50 * 1024 * 1024)
    app.add_routes([web.post("/v1/audio/transcriptions", _stt), web.post("/v1/audio/speech", _tts),
                    web.get("/health", _health), web.get("/v1/health", _health)])
    print(f"local speech ready on http://127.0.0.1:{port}/v1", flush=True)
    web.run_app(app, host="127.0.0.1", port=port, print=None)


if __name__ == "__main__":
    serve()
