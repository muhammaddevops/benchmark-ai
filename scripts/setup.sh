#!/usr/bin/env bash
# One-time setup: Python env, provider plugins, headless Chromium for videos and charts, and the local judge model.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3.12}
[[ -d .venv ]] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m playwright install chromium
command -v ffmpeg >/dev/null || { echo "install ffmpeg: brew install ffmpeg"; exit 1; }
if command -v ollama >/dev/null; then
  ollama list | grep -q "qwen3:14b" || ollama pull qwen3:14b   # free local judge
  ollama list | grep -q "qwen3:8b" || ollama pull qwen3:8b     # reference stack's LLM
else
  echo "optional: brew install ollama (free local judge and local LLM stacks)"
fi
[[ -f .env ]] || { cp .env.example .env; echo "fill in .env (LiveKit + ElevenLabs at least)"; }
.venv/bin/python -m bench doctor
