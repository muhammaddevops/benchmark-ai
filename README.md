# Gulf Voice AI Benchmark

Benchmark any voice AI provider on a **live mock call** with a simulated Saudi/Gulf caller who speaks English, Gulf
Arabic, MSA and code-switched Arabic + English. Each call becomes a **captioned video**, and the results become
**comparison charts** and a **comparison video** for LinkedIn.

```
bench run      the caller places a real call over LiveKit to:
                 - our own agent built from any provider's STT / LLM / TTS or speech-to-speech model, or
                 - a hosted voice agent, dialled on its phone number (Maqsam, Nabrah, Vapi, Retell...), or
                 - a hosted agent's web/WebSocket API through a bridge
               → call.wav (caller left, agent right), timings, transcripts
bench analyze  response time from the recording, language handling, LLM judge (quality, Gulf dialect fit, task
               success), STT/TTS accuracy for our own pipelines → metrics.json, report.html, caller score /100
bench video    the call as a video: speaker panels, live waveforms, captions (Arabic right-to-left), a
               response-time stopwatch, results card. Landscape, square or vertical
bench charts   leaderboard charts (PNG for posts, interactive HTML + table, animated MP4)
bench montage  the comparison video: title card, each provider answering the same caller lines, animated charts,
               method card
```

## Quick start

```bash
scripts/setup.sh
```

```bash
.venv/bin/python -m bench doctor
```

```bash
.venv/bin/python -m bench providers --group domestic
```

```bash
.venv/bin/python -m bench run -s local-all_whisper_qwen3-8b_macvoice -c clinic_booking_codeswitch
```

```bash
.venv/bin/python -m bench video latest --format square --turns 0-1
```

```bash
.venv/bin/python -m bench charts --name first-look
```

Needs: Python 3.12, ffmpeg and a LiveKit Cloud project. ElevenLabs (for the caller's voice) is optional: the
scripted caller lines are cached. Ollama gives the free local judge and local open models. On Apple silicon,
`bench/localspeech.py` adds free local STT (Whisper turbo) and TTS (macOS voices), so a full call runs with no
provider keys at all. Twilio is only for phone tests.

## Testing a provider

`providers.yaml` is the registry: 44 providers (22 Gulf/regional, 22 global), what each offers for Gulf Arabic,
how it's reached, its key names and its stacks. Every provider is tested one of four ways:

| Provider offers | How it's tested | What you add |
|---|---|---|
| STT, TTS, LLM or speech-to-speech with a LiveKit plugin | our agent with that component swapped into the reference pipeline | its key in `.env` (the stack exists) |
| An OpenAI-compatible API (Fanar, Sarj, Gulf LLMs) | the `openai` plugin pointed at its `base_url` | its key |
| A hosted voice-agent platform (Maqsam, Nabrah, Hamsa, Vapi, Retell, ElevenLabs Agents...) | dial its agent's number (`kind: phone`) | the agent set up with `bench brief <scenario>`, its number in `.env`, the one-time SIP trunk (`scripts/setup_sip.py --apply`) |
| A WebSocket/web API only | a bridge (`bench/bridges/`) | a small adapter |

Stack families in `stacks/` (`bench list` shows which are ready; `bench new stt <x> --plugin <x> --model ...` writes one for a provider that isn't there yet):

| Prefix | What varies | Held constant |
|---|---|---|
| `ref-pipeline` | the control: ElevenLabs Scribe v2 RT · GPT-5.4 mini · ElevenLabs Flash v2.5 | |
| `stt-*` | the STT (HUMAIN, Munsit, Nabrah, Sarj, Fanar, Speechmatics, Soniox, Deepgram, Azure, Google, AWS...) | ref LLM + TTS |
| `tts-*` | the TTS (HUMAIN, Munsit/Faseeh, Sarj, Fanar, CAMB.AI, Azure Gulf voices, Polly, Cartesia, ElevenLabs v3/v4...) | ref STT + LLM |
| `llm-*` | the LLM (Fanar, GPT-5.5, Gemini, Claude, local ALLaM / Jais / Falcon / Fanar) | ref STT + TTS |
| `full-*` | a vendor's own speech in and out (HUMAIN, Munsit, Sarj, Fanar) | ref LLM |
| `s2s-*` | speech-to-speech models (OpenAI Realtime, Gemini Live, xAI Grok Voice) | |
| `agent-*` | hosted agents by phone (15 platforms) | |
| `local-all_*` | the LLM, everything on this Mac (Whisper turbo + macOS voices) | local STT + TTS |

### Gulf providers at a glance

| Provider | HQ | Tested here | Stacks |
|---|---|---|---|
| Munsit + Faseeh (CNTXT AI) | Abu Dhabi | STT, TTS (Najdi, Emirati voices) | `stt-munsit`, `tts-munsit-*`, `full-munsit` |
| Nabrah | Riyadh | STT; voice agent by phone | `stt-nabrah`, `agent-nabrah` |
| Sarj | Riyadh | STT, TTS (OpenAI-compatible) | `stt-sarj`, `tts-sarj`, `full-sarj` |
| Fanar (QCRI) | Doha | LLM, STT, TTS; open 9B model locally | `full-fanar`, `llm-fanar`, `stt/tts-fanar`, `local-all_whisper_fanar-1-9b_macvoice` |
| CAMB.AI | Dubai | TTS (MARS) | `tts-cambai` |
| HUMAIN (ALLaM) | Riyadh | ALLaM 7B locally (no public LLM API yet) | `local-all_whisper_allam-7b_macvoice`, `llm-allam-7b-local` |
| MBZUAI IFM (Jais 3) | Abu Dhabi | Jais 3 7B locally | `local-all_whisper_jais-3-7b_macvoice` |
| TII (Falcon) | Abu Dhabi | Falcon-H1 7B, Falcon 3 7B locally | `local-all_whisper_falcon-*` |
| Maqsam, Hamsa, Unifonic, Hams.AI, Dayl, ZIWO, Wittify, Sawt, Arabic.AI | KSA / UAE | voice agent by phone (pilot number) | `agent-*` |
| HUMAIN Voice | Riyadh | STT (Arabic-English code-switch), TTS, via `bench/adapters/humain.py` | `stt-humain`, `tts-humain`, `full-humain` |

`docs/providers-research.md` has the research summary and sources. Vendor claims are unverified until benchmarked.

## First results (2026-11-10): Gulf open LLMs on a Mac

Bracket A of `docs/linkedin-playbook.md`: same caller, same three scenarios, same local speech (Whisper turbo +
macOS voices) on an M4 Pro; only the LLM changes (Q4_K_M via Ollama). Judge: local Qwen3 14B (rejudge with a
hosted judge before publishing). Charts: `results/charts/gulf-open-llms/`; video: `results/videos/gulf-open-llms/`.

| Model | Caller score | Calls | Typical / slow reply | Right language | Quality | Task done |
|---|---|---|---|---|---|---|
| ALLaM 7B · Saudi | 61.6 | 3 | 3.85 / 6.57 s | 56% | 8/10 | 100% |
| Falcon-H1 7B · UAE | 57.8 | 3 | 4.10 / 6.97 s | 69% | 6/10 | 97% |
| Fanar 1 9B · Qatar | 53.3 | 3 | 4.00 / 4.71 s | 50% | 7.2/10 | 80% |
| Qwen3 8B · global reference | 50.5 | 3 | 4.49 / 8.73 s | 44% | 6.5/10 | 83% |
| Falcon 3 7B · UAE | 43.1 | 3 | 4.17 / 5.59 s | 56% | 4.3/10 | 53% |
| Jais 3 7B · UAE (reasoning) | 29.2 | 1 | 13.0 / 14.3 s | 33% | 5/10 | 50% |

All replies take ~4 s here because the speech runs locally (batch Whisper, system voices); the hosted stacks measured
on 2026-11-07 answered in 1.5-3 s. Every model often answered English questions in Arabic once the call was in Arabic.

## Scenarios

| Scenario | What it tests |
|---|---|
| `clinic_booking_codeswitch` | Riyadh clinic booking with heavy intra-sentence Arabic-English code-switching |
| `telecom_billing_gulf` | Telecom billing dispute in Gulf Arabic with switches to English |
| `bank_card_msa` | Declined card: formal MSA ↔ English, with a barge-in |

Each turn has a language (`en`, `ar-gulf`, `ar-msa`, `mixed`) and the language the reply should be in. The agent's
business facts are in `sut_instructions` (what `bench brief` prints).

## The numbers

- **Caller score /100** (the headline): speed 25%, replying in the caller's language 20%, answer quality 25%,
  task success 20%, reliability 10%. Only what the caller experiences, so hosted platforms and component stacks
  compare like for like.
- **Response time**: end of the caller's speech to the agent's first audio, from the recording; median and slow
  end (90th percentile). Includes the network to the provider (and the phone network for `kind: phone`).
- **Right language**: share of turns answered in the expected language, judged from what the caller heard.
- **Quality / task success**: LLM judge over the transcript and the agent's instructions (default: local
  `qwen3:14b`; set `BENCH_JUDGE` for a hosted judge, and use one judge per published comparison).
- Our own pipelines also get STT error (vs the caller's ground-truth script) and TTS intelligibility.

See `CLAUDE.md` for the full workflow and the fairness rules for published comparisons.
