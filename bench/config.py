from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

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
