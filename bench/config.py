from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# BENCH_LOCAL_ONLY=1: spend nothing with any vendor. Every key from .env (and any *_API_KEY/SECRET/TOKEN in the
# shell) is dropped, so a vendor call fails instead of using credits; calls go through a LiveKit server on this
# machine (`livekit-server --dev`, or BENCH_LOCAL_LIVEKIT_URL); the agent's audio is transcribed with local
# Whisper and the judge is a local Ollama model. Cached caller audio is still replayed (it is read from disk), and
# a line that isn't cached stops the call. Inherited by the worker subprocesses.
LOCAL_ONLY = os.environ.get("BENCH_LOCAL_ONLY", "").lower() in ("1", "true", "yes")
if LOCAL_ONLY:
    import re
    from dotenv import dotenv_values

    _secret = re.compile(r"(API_KEY|SECRET|TOKEN|PASS|_SID$|^ELEVEN|^OPENAI|^GEMINI|^GOOGLE_|^AZURE_|^AWS_|^TWILIO)", re.I)
    for _k in set(dotenv_values(ROOT / ".env")) | {k for k in os.environ if _secret.search(k)}:
        os.environ.pop(_k, None)
    os.environ["LIVEKIT_URL"] = os.environ.get("BENCH_LOCAL_LIVEKIT_URL", "ws://127.0.0.1:7880")
    os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"] = "devkey", "secret"  # livekit-server --dev
    os.environ["BENCH_TRANSCRIBER"] = "whisper"
    for _k in ("BENCH_JUDGE", "BENCH_TESTER_LLM"):
        if not os.environ.get(_k, "").startswith("ollama:"):
            os.environ[_k] = "ollama:qwen3:14b"

# The plugins read ELEVEN_API_KEY; the project's .env names it ELEVEN_LABS.
if os.environ.get("ELEVEN_LABS") and not os.environ.get("ELEVEN_API_KEY"):
    os.environ["ELEVEN_API_KEY"] = os.environ["ELEVEN_LABS"]

STACKS_DIR = ROOT / "stacks"
SCENARIOS_DIR = ROOT / "scenarios"
RESULTS_DIR = ROOT / "results"
RUNS_DIR = RESULTS_DIR / "runs"
CACHE_DIR = RESULTS_DIR / ".tts_cache"

SUT_AGENT_NAME = "bench-sut"
CALLER_IDENTITY = "caller"
SAMPLE_RATE = 24000  # caller + recording sample rate

# The judge and the dynamic caller: see llmclient.py (BENCH_JUDGE, BENCH_TESTER_LLM; local Ollama by default).

# Conventional key names some SDKs read, filled in from the names people commonly put in .env
for _src, _dst in (("GEMINI_API_KEY", "GOOGLE_API_KEY"), ("AZURE_SPEECH_KEY", "AZURE_SPEECH_KEY")):
    if os.environ.get(_src) and not os.environ.get(_dst):
        os.environ[_dst] = os.environ[_src]


def eleven_key() -> str:
    key = os.environ.get("ELEVEN_API_KEY") or os.environ.get("ELEVEN_LABS")
    if not key:
        raise RuntimeError("ElevenLabs key missing: set ELEVEN_LABS in .env")
    return key
