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
2. **Pick the stack** (most providers already have one: `stacks/<family>-<x>.yaml`, see `stacks/README.md`).
   For a new one, `bench new <stt|tts|llm|s2s|agent> <x> --plugin ... --model ... [--voice/--language/--base-url/--key]`
   writes it with everything else held at the reference (`--local`: at the all-local baseline):
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
     OK**: it changes their Twilio and LiveKit accounts; the user approved it on 2026-11-14) and Twilio geo permissions for the country dialled. Created 2026-11-14 (Twilio trunk `lk-bench`, credential list `lk-bench-34b3`,
     LiveKit trunk `lk-bench (Twilio)`). The Twilio key in .env is restricted: it can't link a credential list to a
     trunk (no such permission for restricted keys), so a re-run prints that one console step. TWILIO_FROM_NUMBER's incoming calls go to an ElevenLabs
     agent, so the script uses it as caller ID only and never moves it onto the trunk unless `--attach-number`.
     Prefer a vendor's SIP address to its phone number (a LiveKit outbound trunk pointed at it, named in the stack's
     `phone.trunk_env`); never mix SIP-dialled and phone-dialled agents on one chart. Twilio to +966/+971 is
     documented but untested (2026-11-15). Pilot requests: `docs/vendor-outreach.md`. The buyer is a Gulf business
     choosing a vendor (`docs/linkedin-playbook.md`, "Who it's for").
   - **SDK or WebSocket API only** (no LiveKit plugin): a `plugin: custom` adapter in `bench/adapters/`
     (`humain.py` wraps HUMAIN's SDK as a LiveKit STT/TTS: copy it for Hamsa etc.), or, for a whole hosted agent, a
     bridge in `bench/bridges/`.
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
   With many systems or wordy local models, `--turns 0-0 --max-reply 6` keeps it near 4 min for 8 systems (only the
   first 6 s of each long reply plays; the caption says how long it ran; response gaps are never cut).
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
- **Spend nothing** (user, 2026-11-25: no ElevenLabs or other vendor credits unless they say so): start
  `livekit-server --dev --bind 127.0.0.1 --node-ip 127.0.0.1` and `ollama serve`, then prefix commands with
  `BENCH_LOCAL_ONLY=1`. It drops every vendor key from the environment (a vendor call fails instead of spending),
  points LiveKit at the local server (devkey/secret), forces local Whisper and the local Ollama judge, and marks the
  runs `local_only` (montage and fullreport then say "on one Mac"). Latency then has no internet round trip, so
  don't mix these runs with Cloud runs in one chart (`--since`).
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
- Keep the Mac awake: `bench run` holds `caffeinate` on macOS (a sleep on 2026-11-10 stalled a call for 4 h).
  Invalid runs go to `results/runs_excluded/` (not charted) with a note in its README. A call where the agent
  greeted, logged no errors and then never answered within the caller's 12 s wait counts (score 0: the agent was
  too slow, e.g. Jais 3 reasoning); one whose agent logged errors and never answered doesn't (`charts.valid`).
- The judge checks its own answer's format and asks again (3 tries; `schema_ok` in judge.json): small local judges
  sometimes invent their own keys, which used to leave a call without quality or task scores.
- Local Gulf models (2026-11-10): ALLaM 7B, Fanar 1 9B, Falcon-H1 7B, Falcon 3 7B run fine in Ollama; Jais 3 7B is a
  reasoning model (template always thinks; ~8-23 s per reply on the Mac); `think: true` + a big `max_tokens`.
  The local `qwen3:14b` judge is lenient on broken Arabic (it rated Falcon 3's garbled replies "natural"): use a
  hosted judge for anything published.
- Ask before: running `scripts/setup_sip.py --apply`, creating accounts or agents on a provider, dialling numbers
  the user didn't give, posting anything.
