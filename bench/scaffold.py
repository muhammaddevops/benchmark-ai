"""`bench new`: write a stack file for a new provider, isolating it against the reference pipeline.

    bench new stt acme --plugin acme --model acme-ar-2 --language ar --key ACME_API_KEY
    bench new tts acme --plugin openai --base-url https://api.acme.ai/v1 --key ACME_API_KEY --model acme-tts --voice layla
    bench new llm acme --plugin openai-compatible --base-url https://api.acme.ai/v1 --key ACME_API_KEY --model acme-chat
    bench new s2s acme --plugin acme --model acme-live
    bench new agent acme                       # hosted agent by phone: ACME_AGENT_NUMBER
    bench new llm acme-local --plugin ollama --model hf.co/acme/acme-7b-GGUF:Q4_K_M --local   # all-local speech
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import STACKS_DIR

REF = {"stt": {"plugin": "elevenlabs", "model": "scribe_v2_realtime",
               "extra": {"server_vad": {"vad_silence_threshold_secs": 0.6}}},
       "llm": {"plugin": "openai", "model": "gpt-5.4-mini"},
       "tts": {"plugin": "elevenlabs", "model": "eleven_flash_v2_5", "voice": "EXAVITQu4vr4xnSDxMaL"}}
LOCAL = {"stt": {"plugin": "localspeech"}, "llm": {"plugin": "ollama", "model": "qwen3:8b", "max_tokens": 220},
         "tts": {"plugin": "localspeech", "voice": "auto"}}


def new_stack(role: str, name: str, *, plugin: str | None = None, model: str | None = None, voice: str | None = None,
              language: str | None = None, base_url: str | None = None, key: str | None = None,
              display: str | None = None, local: bool = False, force: bool = False) -> Path:
    comp: dict[str, Any] = {"plugin": plugin or name}
    for k, v in (("model", model), ("voice", voice), ("language", language), ("base_url", base_url)):
        if v:
            comp[k] = v
    if key and (base_url or plugin in ("openai-compatible",)):
        comp["api_key_env"] = key
    disp = display or name.replace("-", " ").title()
    if role == "agent":
        env = f"{name.upper().replace('-', '_')}_AGENT_NUMBER"
        fid = f"agent-{name}"
        spec: dict[str, Any] = {
            "name": f"{disp} voice agent (phone)", "display": disp, "display_sub": "hosted agent · via phone",
            "provider": name, "kind": "phone", "phone": {"number_env": env, "trunk_env": "BENCH_SIP_TRUNK_ID"},
            "notes": "Black box over the phone network. Record the platform's voice, model and language here."}
        head = f"{disp}: set the agent up with `bench brief <scenario>`, put its number in .env as {env}."
    elif role == "s2s":
        fid = f"s2s-{name}"
        spec = {"name": f"{disp} (speech-to-speech)", "display": disp, "display_sub": f"{model or 'default model'} · speech-to-speech",
                "provider": name, "kind": "realtime", "realtime": comp}
        head = f"{disp} speech-to-speech."
    elif role in ("stt", "llm", "tts"):
        base = LOCAL if local else REF
        parts = {r: (comp if r == role else base[r]) for r in ("stt", "llm", "tts")}
        fid = f"local-all_{name}" if local else f"{role}-{name}"
        what = {"stt": "STT", "llm": "LLM", "tts": "TTS"}[role]
        spec = {"name": f"{disp} {what} test", "display": disp,
                "display_sub": f"{model or disp} · {'local speech' if local else 'ref ' + ' + '.join(x.upper() for x in parts if x != role)}",
                "provider": name, "kind": "pipeline", **parts, "turn_detection": "turn-detector",
                "notes": f"{what} test: only the {what} differs from {'local-all_whisper_qwen3-8b_macvoice' if local else 'ref-pipeline'}."}
        head = f"{disp} {what} swap of the {'all-local baseline' if local else 'reference pipeline'}."
    else:
        raise SystemExit("role must be stt, tts, llm, s2s or agent")
    if key and not comp.get("api_key_env") and role != "agent":
        spec["requires"] = [key]
    path = STACKS_DIR / f"{fid}.yaml"
    if path.exists() and not force:
        raise SystemExit(f"{path} exists (use --force to overwrite)")
    path.write_text(f"# {head}\n" + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=118,
                                                   default_flow_style=None))
    return path
