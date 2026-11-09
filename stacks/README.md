# Stack specs

One YAML file per system under test. The filename (without `.yaml`) is the stack id on the CLI.
`bench list` shows each stack's readiness; `bench doctor` shows which keys are missing.

```yaml
name: Full name (report, leaderboard)
display: Short name on charts and in videos
display_sub: "one line under it: models, voice"
provider: tag(s), e.g. "speechmatics + openai + elevenlabs"
kind: pipeline            # pipeline | realtime | phone | bridge
disabled: false           # true = skipped by `-s all`
requires: [SOME_ENV]      # extra env vars that must be set
notes: anything a reader of the results should know (and any non-default setting)
```

## `kind: pipeline` / `kind: realtime`: our own agent, built from provider components

Runs in our worker (`bench/sut_agent.py`), so we also see inside it (STT error rate, TTS intelligibility).

```yaml
stt: {plugin: speechmatics, language: ar}
llm: {plugin: openai, model: gpt-5.4-mini}
tts: {plugin: elevenlabs, model: eleven_flash_v2_5, voice: EXAVITQu4vr4xnSDxMaL}
turn_detection: turn-detector   # turn-detector (LiveKit, local, supports ar) | vad | stt | realtime_llm
endpointing: {min_delay: 0.5, max_delay: 3.0}      # optional
interruption: {enabled: true, min_duration: 0.5}  # optional
preemptive_generation: true                       # optional
# kind: realtime instead has
realtime: {plugin: openai, model: gpt-realtime-2.1, voice: marin}
```

Each component's `plugin:` says where it comes from:

| `plugin:` | What it builds | Keys |
|---|---|---|
| any installed LiveKit plugin (`openai`, `google`, `azure`, `deepgram`, `speechmatics`, `soniox`, `gladia`, `assemblyai`, `cartesia`, `elevenlabs`, `hume`, `aws`, `groq`, `anthropic`, `mistralai`, `rime`, `lmnt`, `neuphonic`, `inworld`, `sarvam`) | `livekit.plugins.<name>.STT/LLM/TTS` (or `realtime.RealtimeModel`); `model`, `voice`, `language` are mapped to the plugin's own parameter names, `kwargs:` passes anything else verbatim, `class:` overrides the class | that provider's key (see `PLUGIN_KEYS` in `bench/stacks.py`) |
| `openai-compatible` | `openai.LLM` with `base_url`, `api_key_env`, `model` (ALLaM, Jais, Fanar, any OpenAI-style API) | `api_key_env` |
| `ollama` | a local open model (`model: qwen3:8b`, `hf.co/<repo>:<quant>`); `max_tokens`, `think: true` | none |
| `localspeech` | free local STT (Whisper turbo) / TTS (macOS voices), `bench/localspeech.py`, auto-started | none |
| `custom` | `factory: "package.module:function"`, `options: {...}` returning any STT/LLM/TTS/RealtimeModel | whatever it needs |
| *(omitted)* | LiveKit Inference gateway (`model: deepgram/nova-3` style ids); out of credits since 2026-11-07 | LiveKit only |

To isolate one provider, copy a stack and change only that provider's component.

## `kind: phone`: a hosted voice agent, dialled like a customer would

```yaml
kind: phone
phone:
  number_env: MAQSAM_AGENT_NUMBER     # the agent's number (E.164) in .env
  trunk_env: BENCH_SIP_TRUNK_ID       # scripts/setup_sip.py
```

Black box: scored only on what the caller hears. Set the agent up with `bench brief <scenario>` (the business
facts and instructions every system gets). Latency includes the phone network.

## `kind: bridge`: a hosted agent reached over its web/WebSocket API

```yaml
kind: bridge
bridge:
  factory: "bench.bridges.acme:run"   # see bench/bridges/README.md
  requires: [ACME_API_KEY, ACME_AGENT_ID]
  options: {...}
```
