"""Text LLMs the benchmark itself uses (the judge, and the caller in dynamic mode).

Chosen with an env var, ``<backend>:<model>``:

  BENCH_JUDGE=ollama:qwen3:14b          local, free (default when nothing else is configured)
  BENCH_JUDGE=openai:gpt-5.5            OPENAI_API_KEY
  BENCH_JUDGE=gemini:gemini-3-flash     GEMINI_API_KEY (Google's OpenAI-compatible endpoint)
  BENCH_JUDGE=inference:openai/gpt-5.5  LiveKit Inference (needs gateway credits)
  BENCH_JUDGE=compat:<model>            any OpenAI-compatible server: BENCH_COMPAT_BASE_URL + BENCH_COMPAT_API_KEY

BENCH_TESTER_LLM works the same way for the dynamic caller. ``auto`` (the default) picks the first that is usable:
OpenAI, Gemini, then local Ollama.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import openai

OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


@dataclass
class Backend:
    client: openai.AsyncOpenAI
    model: str
    label: str
    extra: dict[str, Any]


def _auto(default_openai: str, default_local: str) -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return f"openai:{default_openai}"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini:gemini-3-flash"
    return f"ollama:{default_local}"


def backend(var: str, default_openai: str = "gpt-5.5", default_local: str = "qwen3:14b") -> Backend:
    spec = os.environ.get(var, "auto").strip()
    if spec == "auto":
        spec = _auto(default_openai, default_local)
    kind, _, model = spec.partition(":")
    extra: dict[str, Any] = {}
    if kind == "openai":
        client = openai.AsyncOpenAI()
    elif kind == "gemini":
        client = openai.AsyncOpenAI(
            api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"), base_url=GEMINI_URL
        )
    elif kind == "ollama":
        client = openai.AsyncOpenAI(api_key="ollama", base_url=OLLAMA_URL, timeout=600)
        extra = {"reasoning_effort": "none"}  # qwen3: answer directly, no thinking trace
    elif kind == "inference":
        from livekit.agents.inference._utils import create_access_token, get_default_inference_url

        client = openai.AsyncOpenAI(
            api_key=create_access_token(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]),
            base_url=get_default_inference_url(),
        )
    elif kind == "compat":
        client = openai.AsyncOpenAI(
            api_key=os.environ.get("BENCH_COMPAT_API_KEY", "none"), base_url=os.environ["BENCH_COMPAT_BASE_URL"]
        )
    else:
        raise ValueError(f"{var}={spec!r}: unknown backend {kind!r} (use openai, gemini, ollama, inference, compat)")
    return Backend(client=client, model=model, label=spec, extra=extra)


async def chat(b: Backend, system: str, user: str, json_mode: bool = False) -> str:
    kw: dict[str, Any] = {}
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    if b.extra:
        kw["extra_body"] = b.extra
    r = await b.client.chat.completions.create(
        model=b.model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kw
    )
    return r.choices[0].message.content or ""


def parse_json(raw: str) -> dict[str, Any]:
    raw = raw[raw.find("{") : raw.rfind("}") + 1]
    return json.loads(raw) if raw else {}
