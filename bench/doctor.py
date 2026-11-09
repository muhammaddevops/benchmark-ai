"""`bench doctor`: what can run right now. Prints key names only, never values."""

from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request

from .llmclient import backend
from .stacks import PLUGIN_KEYS, list_stacks, requirements


def _get(url: str, headers: dict[str, str] | None = None, timeout: float = 5) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def _inference() -> str:
    """One cheap request to the LiveKit Inference gateway; the answer is cached for `requirements()`."""
    import time

    import openai

    from .config import RESULTS_DIR

    try:
        from livekit.agents.inference._utils import create_access_token, get_default_inference_url

        client = openai.OpenAI(
            api_key=create_access_token(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]),
            base_url=get_default_inference_url(), max_retries=0, timeout=15,
        )
        client.chat.completions.create(model="openai/gpt-4.1-mini", messages=[{"role": "user", "content": "ok"}], max_tokens=1)
        exhausted, msg = False, "✓ LiveKit Inference gateway answering"
    except Exception as e:  # noqa: BLE001
        exhausted = "429" in str(e) or "quota" in str(e).lower()
        msg = ("✗ LiveKit Inference out of credits: stacks without plugin: are skipped" if exhausted
               else f"? LiveKit Inference check failed: {str(e)[:120]}")
    (RESULTS_DIR / ".inference_status.json").write_text(json.dumps({"exhausted": exhausted, "checked": time.time()}))
    return msg


def _eleven() -> str:
    """Quota from the subscription endpoint, or (scoped keys) a 1-character TTS probe; cached for requirements()."""
    import time

    from .config import RESULTS_DIR

    key = os.environ.get("ELEVEN_API_KEY", "")
    if not key:
        return "✗ ElevenLabs: no key (ELEVEN_LABS); the caller can only replay cached lines"
    sub = _get("https://api.elevenlabs.io/v1/user/subscription", {"xi-api-key": key})
    exhausted, msg = False, ""
    if sub:
        used, limit = sub.get("character_count", 0), sub.get("character_limit", 0)
        exhausted = limit > 0 and used >= limit
        msg = f"{'✗' if exhausted else '✓'} ElevenLabs quota: {used:,} of {limit:,} characters used ({sub.get('tier', '?')} tier)"
    else:
        try:
            req = urllib.request.Request(
                "https://api.elevenlabs.io/v1/text-to-speech/EXAVITQu4vr4xnSDxMaL?output_format=pcm_16000",
                data=json.dumps({"text": ".", "model_id": "eleven_flash_v2_5"}).encode(),
                headers={"xi-api-key": key, "Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=15).read()
            msg = "✓ ElevenLabs answering (quota not readable with this key)"
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")
            exhausted = "quota" in body.lower()
            msg = ("✗ ElevenLabs quota used up: ElevenLabs stacks are blocked, the caller replays cached lines and "
                   "re-transcription falls back to local Whisper" if exhausted else f"? ElevenLabs HTTP {e.code}")
        except Exception as e:  # noqa: BLE001
            msg = f"? ElevenLabs check failed: {str(e)[:100]}"
    (RESULTS_DIR / ".eleven_status.json").write_text(json.dumps({"exhausted": exhausted, "checked": time.time()}))
    return msg


def doctor() -> None:
    ok, no = "✓", "✗"
    print("CORE")
    for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "ELEVEN_API_KEY"):
        print(f"  {ok if os.environ.get(k) else no} {k}")
    print(f"  {ok if shutil.which('ffmpeg') else no} ffmpeg (videos)")
    try:
        import playwright  # noqa: F401

        print(f"  {ok} playwright + chromium (videos, charts)")
    except ImportError:
        print(f"  {no} playwright: .venv/bin/pip install playwright && .venv/bin/python -m playwright install chromium")

    print(f"  {_eleven()}")

    print(f"  {_inference()}")

    print("\nJUDGE + DYNAMIC CALLER")
    for var in ("BENCH_JUDGE", "BENCH_TESTER_LLM"):
        try:
            print(f"  {var} = {backend(var).label}")
        except Exception as e:  # noqa: BLE001
            print(f"  {no} {var}: {e}")

    print("\nLOCAL MODELS (Ollama)")
    tags = _get(os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").replace("/v1", "") + "/api/tags")
    if tags is None:
        print(f"  {no} Ollama not running (`ollama serve`); local LLM stacks and the free judge need it")
    else:
        names = [m["name"] for m in tags.get("models", [])]
        print(f"  {ok} Ollama running: {', '.join(names) or 'no models pulled'}")

    print("\nPHONE CALLS (hosted agents reached by number)")
    trunk = os.environ.get("BENCH_SIP_TRUNK_ID")
    print(f"  {ok if trunk else no} BENCH_SIP_TRUNK_ID {'set' if trunk else 'not set: see scripts/setup_sip.py (one-time, needs your OK)'}")

    print("\nPROVIDER KEYS PRESENT")
    have = [p for p, groups in PLUGIN_KEYS.items() if any(g and all(os.environ.get(k) for k in g) for g in groups)]
    print("  " + (", ".join(sorted(have)) or "none"))

    print("\nSTACKS")
    ready, waiting = [], []
    for st in list_stacks():
        if st.get("error"):
            waiting.append((st["id"], st["error"]))
            continue
        miss = requirements(st)
        (waiting if miss else ready).append((st["id"], ", ".join(miss)))
    print(f"  ready now ({len(ready)}): " + (", ".join(s for s, _ in ready) or "none"))
    print(f"  waiting on keys ({len(waiting)}):")
    for s, m in waiting:
        print(f"    {s:<46} {m}")
