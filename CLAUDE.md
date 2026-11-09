# Gulf Voice AI Benchmark

Live mock calls between a scripted Saudi/Gulf caller (English, Gulf Arabic, MSA, code-switched) and a voice AI
system, scored from the recording, turned into captioned call videos and comparison charts for LinkedIn.

Python: `.venv` (`scripts/setup.sh`). Secrets in `.env` (template `.env.example`): never print, commit or upload it.
Outputs in `results/` (git-ignored): `runs/<run>/` (call.wav, metrics.json, report.html, video/), `charts/<name>/`,
`videos/<name>/`.

## When the user says "benchmark provider X"

1. **Look it up**: `providers.yaml` (44 Gulf + global providers: what X offers for Gulf Arabic, how it's reached,
   its key names, its stacks) and `.venv/bin/python -m bench providers`. Then `.venv/bin/python -m bench doctor`.
   If X isn't there, research it (docs, PyPI `livekit-plugins-<x>`, OpenAI-compatible endpoints, phone agents) and
   add an entry.
2. **Pick the stack** (most providers already have one: `stacks/<family>-<x>.yaml`, see `stacks/README.md`):
   - **Component** (STT / TTS / LLM): the `stt-*`, `tts-*`, `llm-*` files are the reference pipeline
     (`ref-pipeline.yaml`: Scribe v2 RT · GPT-5.4 mini · Flash v2.5) with exactly one part swapped. New provider:
     copy the closest one and change only that part. `plugin: <x>` for any installed LiveKit plugin (openai,
     google, azure, aws, deepgram, speechmatics, soniox, gladia, assemblyai, cartesia, elevenlabs, mistralai, xai,
     telnyx, anthropic, groq, and the Gulf ones: `munsit`, `nabrah`, `cambai`); `pip install
     livekit-plugins-<x>==1.8.11` for others and add its key to `PLUGIN_KEYS` in `bench/stacks.py`.
   - **OpenAI-style API from another vendor** (Fanar, Sarj): `plugin: openai` (STT/TTS) or `openai-compatible`
     (LLM) with `base_url` + `api_key_env`.
   - **Speech-to-speech**: `kind: realtime`, `realtime: {plugin: <x>, model: ...}` (`s2s-*`).
   - **Hosted voice-agent platform**: black box, by phone (`agent-*`). Print the brief with `bench brief
     <scenario>` for the user to paste into the platform; they give you the agent's number; it goes in `.env` as
     `<X>_AGENT_NUMBER`. Needs `BENCH_SIP_TRUNK_ID` once (`scripts/setup_sip.py --apply`, **only with the user's
     OK**: it changes their Twilio and LiveKit accounts) and Twilio geo permissions for the country dialled.
   - **WebSocket/web API only** (HUMAIN Voice, Hamsa STT/TTS): a bridge in `bench/bridges/` or a `plugin: custom`
     factory (`bench/factories.py`).
   - **Open model on this Mac**: `plugin: ollama` (`ollama pull hf.co/<repo>:<quant>`); the `local-all_*` family
     holds the local speech constant so only the LLM changes.
3. **Smoke-build**: `.venv/bin/python -m bench list` shows the stack as ready. For our own agent's stacks also
   `.venv/bin/python -c "import bench.config; from bench.stacks import *; print(build_session_kwargs(load_stack('<id>')))"`.
4. **Run** every scenario (about 4-5 min per call; run batches in the background, one at a time):
   `.venv/bin/python -m bench run -s <id> -c all`. Don't run heavy work (video renders, model pulls) during
   calls: it slows local stacks and skews response times.
5. **Video** of a call: `.venv/bin/python -m bench video latest --format square --turns 0-1`
   (`landscape` 1920x1080, `square` 1080x1080, `vertical` 1080x1920; `--label` sets the on-screen name).
6. **Charts**: `.venv/bin/python -m bench charts -s <a> -s <b> ... --name <name>` → PNGs (landscape, square,
   4:5 portrait), interactive `index.html` with a table, `leaderboard.csv`, `charts_landscape.mp4`.
   **Comparison video**: `.venv/bin/python -m bench montage -s <a> -s <b> ... -c clinic_booking_codeswitch --format square`.
7. **Report back**: what X is good or bad at, with numbers (caller score, typical and slow-end response time,
   right-language rate, quality, task success) and an example turn, plus the video/chart paths.

## Fair comparisons (published numbers)

- Same scenarios, same caller voices, same network (this Mac → each provider). Compare within a bracket:
  WebRTC stacks with WebRTC stacks, phone agents with phone agents (the PSTN adds ~0.3-0.6 s and narrowband
  audio), local models with local models.
- **One judge per comparison**: `bench charts` warns when runs were judged by different models; fix with
  `bench rejudge -s ...` before publishing. The default judge is local `qwen3:14b`; a stronger hosted judge
  (`BENCH_JUDGE=openai:gpt-5.5`) is better for a public post.
- The headline is the **caller score** (summary.caller_score): only what the caller experiences (speed,
  replying in their language, quality, task success, reliability), so black-box platforms and our own pipelines
  compare like for like. STT/TTS accuracy exist only for our own pipelines.
- At least 3 calls (all scenarios) per system before ranking it; label smaller samples.
- Hosted platforms: use the brief as written and the platform's default Arabic voice/model unless the plan says
  otherwise; note any change in the stack's `notes:`.
- Local models are quantised (Q4_K_M) on a laptop: say "on a Mac" and never present them as the vendor's hosted
  quality or speed.

## Things to know

- **No-credit fallbacks**: LiveKit Inference has been out of credits since 2026-11-07 and the ElevenLabs quota ran
  out on 2026-11-10. `bench doctor` probes both (cached 12 h) and `bench list` marks the affected stacks. Then:
  the caller replays its cached lines (`results/.tts_cache`; new lines fall back to a macOS voice, logged),
  re-transcription of the agent uses local Whisper (`BENCH_TRANSCRIBER`, recorded as `summary.transcriber`), and
  the `local-all_*` stacks run entirely on this Mac.
- **Local speech server** (`bench/localspeech.py`, `plugin: localspeech`, auto-started by `bench run`, log
  `results/localspeech.log`): OpenAI-compatible on 127.0.0.1:8770. STT = mlx-whisper large-v3-turbo with language
  ID restricted to ar/en (unrestricted it translates Arabic to English); TTS = macOS `say`, Majed for Arabic
  runs and Samantha for Latin runs within one reply.
- ElevenLabs: 3 concurrent requests; the key is scoped (no quota read, so doctor probes with a 1-character TTS).
- The agent-under-test worker (`bench/sut_agent.py`, agent_name `bench-sut`) is started by `bench run` only when a
  stack needs it; log in `results/worker.log`. Local Ollama models are prewarmed before dialling.
- Latency is caller-perceived (end of caller audio → first agent audio), measured from the recording.
- Videos never shorten the agent's response gaps; only the caller's own pauses are trimmed (`--gap`).
- Costs: ElevenLabs characters, provider usage, Twilio per minute. Fanar's default TTS quota is ~20 requests/day.
- Hume shuts down its TTS/agent APIs on 2026-11-13: not included.
- Ask before: running `scripts/setup_sip.py --apply`, creating accounts or agents on a provider, dialling numbers
  the user didn't give, posting anything.
