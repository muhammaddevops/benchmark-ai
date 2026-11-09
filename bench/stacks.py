"""Stack specs: one YAML file per system under test.

Kinds:
  pipeline   STT -> LLM -> TTS, run by our own LiveKit agent (bench-sut); we see its internals
  realtime   a speech-to-speech model, run by our agent
  phone      a hosted voice agent reached by dialling its phone number (LiveKit SIP outbound); black box
  bridge     a hosted voice agent reached over its web/WebSocket API by a relay participant; black box

Each component names where it comes from with ``plugin:``:
  (omitted)            LiveKit Inference (needs gateway credits)
  <plugin name>        any installed ``livekit-plugins-<name>``: openai, google, azure, deepgram, speechmatics,
                       cartesia, soniox, gladia, assemblyai, hume, anthropic, groq, aws, elevenlabs, neuphonic, rime,
                       inworld, lmnt, sarvam, mistralai. ``model``, ``voice`` and ``language`` are mapped onto the
                       plugin's own parameter names; ``kwargs:`` is passed through as is.
  ollama               a local model served by Ollama (``model: qwen3:8b``)
  openai-compatible    any OpenAI-compatible chat API (``base_url``, ``api_key_env``, ``model``): Gulf LLM APIs, Groq...
  custom               ``factory: "package.module:function"``, ``options: {...}``

See stacks/README.md for the schema and PROVIDERS.md for what each Gulf provider needs.
"""

from __future__ import annotations

import importlib
import inspect
import os
from pathlib import Path
from typing import Any

import yaml

from .config import STACKS_DIR

BLACKBOX_KINDS = ("phone", "bridge")

# keys each plugin reads from the environment (first group that is fully set counts as configured)
PLUGIN_KEYS: dict[str, list[list[str]]] = {
    "openai": [["OPENAI_API_KEY"]],
    "google": [["GOOGLE_API_KEY"], ["GOOGLE_APPLICATION_CREDENTIALS"]],
    "azure": [["AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"]],
    "deepgram": [["DEEPGRAM_API_KEY"]],
    "speechmatics": [["SPEECHMATICS_API_KEY"]],
    "cartesia": [["CARTESIA_API_KEY"]],
    "soniox": [["SONIOX_API_KEY"]],
    "gladia": [["GLADIA_API_KEY"]],
    "assemblyai": [["ASSEMBLYAI_API_KEY"]],
    "hume": [["HUME_API_KEY"]],
    "anthropic": [["ANTHROPIC_API_KEY"]],
    "groq": [["GROQ_API_KEY"]],
    "aws": [["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]],
    "elevenlabs": [["ELEVEN_API_KEY"]],
    "neuphonic": [["NEUPHONIC_API_KEY"]],
    "rime": [["RIME_API_KEY"]],
    "inworld": [["INWORLD_API_KEY"]],
    "lmnt": [["LMNT_API_KEY"]],
    "sarvam": [["SARVAM_API_KEY"]],
    "mistralai": [["MISTRAL_API_KEY"]],
    "nabrah": [["NABRAH_API_KEY"]],
    "munsit": [["MUNSIT_API_KEY"], ["FASEEH_API_KEY"]],
    "cambai": [["CAMB_API_KEY"]],
    "xai": [["XAI_API_KEY"]],
    "telnyx": [["TELNYX_API_KEY"]],
    "inference": [["LIVEKIT_API_KEY"]],
    "ollama": [[]],
    "localspeech": [[]],
}

# a spec's generic field -> the names plugins use for it
ALIASES = {
    "model": ["model", "model_name", "model_version"],
    "voice": ["voice", "voice_id", "voice_name", "speaker"],
    "language": ["language", "language_code", "languages", "lang", "lang_code", "target_language_code"],
}
ROLE_CLASS = {"stt": "STT", "llm": "LLM", "tts": "TTS", "realtime": "realtime.RealtimeModel"}


def load_stack(stack_id: str) -> dict[str, Any]:
    path = Path(stack_id)
    if path.suffix not in (".yaml", ".yml"):
        path = STACKS_DIR / f"{stack_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"stack not found: {path}")
    spec = yaml.safe_load(path.read_text())
    spec.setdefault("id", path.stem)
    spec.setdefault("name", spec["id"])
    spec.setdefault("kind", "pipeline")
    spec["blackbox"] = spec["kind"] in BLACKBOX_KINDS or bool(spec.get("blackbox"))
    return spec


def list_stacks() -> list[dict[str, Any]]:
    out = []
    for p in sorted(STACKS_DIR.glob("*.yaml")):
        try:
            out.append(load_stack(str(p)))
        except Exception as e:  # noqa: BLE001
            out.append({"id": p.stem, "name": p.stem, "error": str(e)})
    return out


def describe(spec: dict[str, Any]) -> dict[str, str]:
    """Short human labels for each component (used in reports)."""

    def label(c: dict[str, Any] | None) -> str:
        if not c:
            return "-"
        parts = [c.get("plugin", "inference") + ":" if c.get("plugin") else "", str(c.get("model", ""))]
        if c.get("language"):
            parts.append(f" [{c['language']}]")
        return "".join(parts)

    kind = spec.get("kind")
    if kind == "realtime":
        return {"realtime": label(spec.get("realtime")), "tts": label(spec.get("tts"))}
    if kind == "phone":
        return {"phone": str((spec.get("phone") or {}).get("number_env") or (spec.get("phone") or {}).get("number", "?"))}
    if kind == "bridge":
        return {"bridge": str((spec.get("bridge") or {}).get("factory", "?"))}
    return {
        "stt": label(spec.get("stt")),
        "llm": label(spec.get("llm")),
        "tts": label(spec.get("tts")),
        "turn": str(spec.get("turn_detection", "auto")),
    }


# --------------------------------------------------------------------------- readiness


def _components(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in (spec.get(k) for k in ("stt", "llm", "tts", "realtime")) if isinstance(c, dict)]


def _exhausted(name: str) -> bool:
    import json
    import time

    from .config import RESULTS_DIR

    try:
        d = json.loads((RESULTS_DIR / f".{name}_status.json").read_text())
        return d.get("exhausted", False) and time.time() - d.get("checked", 0) < 12 * 3600
    except Exception:  # noqa: BLE001
        return False


_OLLAMA: dict[str, Any] = {}


def ollama_models() -> set[str] | None:
    """Models pulled into the local Ollama (lower-cased names, with and without :latest); None if it isn't running."""
    import json
    import time
    import urllib.request

    if _OLLAMA and time.time() - _OLLAMA["t"] < 30:
        return _OLLAMA["tags"]
    url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").replace("/v1", "") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            names = [m["name"].lower() for m in json.loads(r.read()).get("models", [])]
        tags: set[str] | None = set(names) | {n.removesuffix(":latest") for n in names}
    except Exception:  # noqa: BLE001
        tags = None
    _OLLAMA.update(t=time.time(), tags=tags)
    return tags


def inference_exhausted() -> bool:
    """True when `bench doctor` last found the LiveKit Inference gateway out of credits (checked within 12 h)."""
    return _exhausted("inference")


def eleven_exhausted() -> bool:
    """True when `bench doctor` last found the ElevenLabs quota used up (checked within 12 h)."""
    return _exhausted("eleven")


def requirements(spec: dict[str, Any]) -> list[str]:
    """Missing environment variables or services (empty = ready to run)."""
    missing: list[str] = []
    for c in _components(spec):
        plugin = c.get("plugin", "inference")
        if plugin == "inference" and inference_exhausted():
            missing.append("LiveKit Inference credits")
            continue
        if plugin == "openai-compatible":
            if c.get("api_key_env") and not os.environ.get(c["api_key_env"]):
                missing.append(c["api_key_env"])
            continue
        if plugin == "ollama":
            tags = ollama_models()
            if tags is None:
                missing.append("Ollama running (ollama serve)")
            elif c.get("model", "").lower() not in tags:
                missing.append(f"ollama pull {c.get('model')}")
            continue
        if plugin in ("custom", "localspeech"):
            continue
        if c.get("api_key_env"):  # vendor API through a generic plugin: its own key, not the plugin's
            if not os.environ.get(c["api_key_env"]):
                missing.append(c["api_key_env"])
            continue
        groups = PLUGIN_KEYS.get(plugin, [[]])
        if any(k in spec.get("requires", []) for g in groups for k in g):
            continue  # the stack names the exact key it needs
        if not any(all(os.environ.get(k) for k in g) for g in groups):
            missing.append(" or ".join("+".join(g) for g in groups))
        elif plugin == "elevenlabs" and eleven_exhausted():
            missing.append("ElevenLabs quota")
    if spec.get("kind") == "phone":
        ph = spec.get("phone") or {}
        for var in (ph.get("number_env"), ph.get("trunk_env", "BENCH_SIP_TRUNK_ID")):
            if var and not os.environ.get(var):
                missing.append(var)
    if spec.get("kind") == "bridge":
        for var in (spec.get("bridge") or {}).get("requires", []):
            if not os.environ.get(var):
                missing.append(var)
    for var in spec.get("requires", []):
        if not os.environ.get(var):
            missing.append(var)
    return sorted(set(missing))


# --------------------------------------------------------------------------- builders


def _custom(c: dict[str, Any]) -> Any:
    mod, _, fn = c["factory"].partition(":")
    return getattr(importlib.import_module(mod), fn)(**c.get("options", {}))


def _resolve(obj: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


def _plugin(role: str, c: dict[str, Any]) -> Any:
    """Build any livekit-plugins-<name> component from a spec, mapping model/voice/language to its parameters."""
    name = c["plugin"]
    mod = importlib.import_module(f"livekit.plugins.{name}")
    cls = _resolve(mod, c.get("class") or ROLE_CLASS[role])
    params = inspect.signature(cls).parameters
    kw: dict[str, Any] = dict(c.get("kwargs") or {})
    for field, names in ALIASES.items():
        if field not in c or any(n in kw for n in names):
            continue
        target = next((n for n in names if n in params), None)
        if target is None:
            raise ValueError(f"{name}.{cls.__name__} has no parameter for {field!r}; use kwargs:")
        value = c[field]
        if target == "languages" and isinstance(value, str):
            value = [value]
        kw[target] = value
    if name == "elevenlabs" and c.get("extra"):  # older stack files put Scribe/Flash options under extra:
        kw.update(c["extra"])
    # an OpenAI-style API from another vendor through the openai plugin (e.g. Fanar's /v1/audio/*)
    if c.get("base_url") and "base_url" in params:
        kw.setdefault("base_url", c["base_url"])
    if c.get("api_key_env") and "api_key" in params:
        kw.setdefault("api_key", os.environ.get(c["api_key_env"], ""))
    return cls(**kw)


def _localspeech(role: str, c: dict[str, Any]) -> Any:
    """Free local speech (bench/localspeech.py): Whisper STT, macOS voices TTS, via the openai plugin."""
    from livekit.plugins import openai

    from .localspeech import URL

    if role == "stt":
        kw: dict[str, Any] = {"model": "whisper-1", "base_url": URL, "api_key": "local"}
        kw.update({"language": c["language"]} if c.get("language") else {"detect_language": True})
        return openai.STT(**{**kw, **(c.get("kwargs") or {})})
    if role == "tts":
        return openai.TTS(**{"model": "tts-1", "voice": c.get("voice", "auto"), "base_url": URL, "api_key": "local",
                             "response_format": "wav", **(c.get("kwargs") or {})})
    raise ValueError("localspeech provides stt and tts only")


def uses_localspeech(spec: dict[str, Any]) -> bool:
    return any(c.get("plugin") == "localspeech" for c in _components(spec))


def _openai_compatible(c: dict[str, Any]) -> Any:
    from livekit.plugins import openai

    key = os.environ.get(c["api_key_env"], "") if c.get("api_key_env") else "none"
    kw: dict[str, Any] = {"model": c["model"], "base_url": c["base_url"], "api_key": key}
    kw.update(c.get("kwargs") or {})
    return openai.LLM(**kw)


def _ollama(c: dict[str, Any]) -> Any:
    from livekit.plugins import openai

    kw: dict[str, Any] = {
        "model": c["model"],
        "base_url": os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        "api_key": "ollama",
        "temperature": c.get("temperature", 0.6),
    }
    extra = dict(c.get("extra_body") or {})
    if c.get("think") is False or c.get("think") is None:
        extra.setdefault("reasoning_effort", "none")  # qwen3 and similar: reply directly
    if extra:
        kw["extra_body"] = extra
    if c.get("max_tokens"):
        kw["max_completion_tokens"] = c["max_tokens"]
    kw.update(c.get("kwargs") or {})
    return openai.LLM(**kw)


def _build(role: str, c: dict[str, Any]) -> Any:
    plugin = c.get("plugin", "inference")
    if plugin == "custom":
        return _custom(c)
    if plugin == "openai-compatible":
        return _openai_compatible(c)
    if plugin == "ollama":
        return _ollama(c)
    if plugin == "localspeech":
        return _localspeech(role, c)
    if plugin != "inference":
        return _plugin(role, c)

    from livekit.agents import inference

    if role == "realtime":
        from livekit.agents.inference.realtime import RealtimeModel

        kw = {"model": c["model"], **({"voice": c["voice"]} if c.get("voice") else {}), **c.get("extra", {})}
        return RealtimeModel(**kw)
    kw = {"model": c["model"]}
    if c.get("voice") and role == "tts":
        kw["voice"] = c["voice"]
    if c.get("language") and role in ("stt", "tts"):
        kw["language"] = c["language"]
    if c.get("extra"):
        kw["extra_kwargs"] = c["extra"]
    return {"stt": inference.STT, "llm": inference.LLM, "tts": inference.TTS}[role](**kw)


def _turn_detection(value: Any) -> Any:
    if value in (None, "auto"):
        return None
    if value == "turn-detector":
        from livekit.agents import inference

        return inference.TurnDetector()  # runs locally, no gateway credits needed
    if value == "multilingual":
        from livekit.plugins.turn_detector.multilingual import MultilingualModel

        return MultilingualModel()
    return value  # "vad" | "stt" | "realtime_llm" | "manual"


def build_session_kwargs(spec: dict[str, Any], vad: Any = None) -> dict[str, Any]:
    """Translate a stack spec into ``AgentSession(**kwargs)``."""
    if spec["kind"] in BLACKBOX_KINDS:
        raise ValueError(f"{spec['id']} is a {spec['kind']} stack: it is not run by our agent")
    kw: dict[str, Any] = {}
    turn: dict[str, Any] = {}

    if spec["kind"] == "realtime":
        kw["llm"] = _build("realtime", spec["realtime"])
        if spec.get("tts"):
            kw["tts"] = _build("tts", spec["tts"])
        if spec.get("stt"):
            kw["stt"] = _build("stt", spec["stt"])
    else:
        kw["stt"] = _build("stt", spec["stt"])
        kw["llm"] = _build("llm", spec["llm"])
        kw["tts"] = _build("tts", spec["tts"])
        if vad is not None:
            kw["vad"] = vad

    td = _turn_detection(spec.get("turn_detection"))
    if td is not None:
        turn["turn_detection"] = td
    if spec.get("endpointing"):
        turn["endpointing"] = spec["endpointing"]
    if spec.get("interruption"):
        turn["interruption"] = spec["interruption"]
    if "preemptive_generation" in spec:
        pg = spec["preemptive_generation"]
        turn["preemptive_generation"] = pg if isinstance(pg, dict) else {"enabled": bool(pg)}
    if turn:
        kw["turn_handling"] = turn
    return kw
