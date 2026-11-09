# Gulf voice AI providers: benchmark shortlist (snapshot 2026-11-10)

Full data: `gulf_providers.json` in this folder (44 providers, 21 local models, per-provider sources).
Vendor accuracy claims are self-reported. Our benchmark is the independent check.

## Top 20 for the LinkedIn comparison

Ranked on two things: how popular the provider is with Gulf businesses, and whether we can test it through an API or a phone line.

| # | Provider (HQ) | Type | What to test | How we'd test it | Conf. |
|---|---|---|---|---|---|
| 1 | OpenAI (US) | S2S | `gpt-realtime-2.1`, `-mini`; STT `gpt-live-transcribe` | Already in repo; add mini + STT-only variant | high |
| 2 | Google (US) | S2S/STT/TTS | `gemini-3.8-live`; `gemini-3.5-transcribe-live`; Cloud `chirp_3` ar-SA | Already in repo; add 3.8 Live + Chirp 3 ar-SA | high |
| 3 | ElevenLabs (US/UK) | STT/TTS/agents/S2S | `scribe_v2_realtime`, `eleven_flash_v2_5`, `eleven_v3_conversational`, `eleven_v4_turbo`, `eleven_realtime_v1_mini` | Already in repo; add v4/v3-conv TTS; Eleven Realtime via OpenAI-compatible WS (unverified) | high |
| 4 | Microsoft Azure (US) | STT/TTS/Voice Live | STT ar-SA/ar-AE; TTS `ar-SA-HamedNeural`, `ar-AE-FatimaNeural`, `ar-QA-MoazNeural`, `ar-KW-FahedNeural`... | `livekit-plugins-azure` pipeline, UAE/Qatar region | high |
| 5 | Deepgram (US) | STT | `nova-3` ar-SA / ar-AE / multi | Already in repo; add ar-SA vs multi | high |
| 6 | Speechmatics (UK) | STT | `linden-1` with `ar` and `ar_en` | STT-only swap; best-placed for code-switch scenarios | high |
| 7 | Soniox (US) | STT(+TTS) | `stt-rt-v6`, hints ar+en | STT-only swap | high |
| 8 | AssemblyAI (US) | STT | `universal-3-6-pro` (ar, native code-switch) | STT-only swap | high |
| 9 | Cartesia (US) | TTS | `sonic-3.6` ar (Ink-2 STT has no Arabic) | TTS-only swap | high |
| 10 | AWS (US) | STT/TTS | Transcribe `ar-AE` (Gulf); Polly `Zayd`/`Hala` (ar-AE neural) | `livekit-plugins-aws`, me-central-1 | high |
| 11 | HUMAIN Voice (KSA) | STT/TTS | ASR `bayan_cs_ar_en_v2`, `bayan_ar`, `nida_8k_ar`; TTS `nebula` | Custom factory around `humain-voice` SDK (Socket.IO realtime) | medium |
| 12 | Munsit + Faseeh / CNTXT (UAE) | STT/TTS | STT `munsit-en-ar`; TTS `faseeh-v1-preview`, voices `ar-najdi-male-2`, `ar-uae-male-1` | `pip install livekit-plugins-munsit` (`MUNSIT_API_KEY`) | high |
| 13 | Nabrah (KSA) | STT/TTS/agents | STT `eot_nabrah` ar-SA; TTS `nabrah_tts_v2` | Official `livekit-plugins-nabrah` (STT) + custom TTS; agent via SIP | high |
| 14 | Sarj (KSA) | STT/TTS/outbound agent | `sarj-stt`; `sarj-tts` voices `ars_male`, `ars_female`, `nourah` | `openai.TTS(base_url=...)`; agent calls a Twilio number into LiveKit SIP | high |
| 15 | Hamsa (MENA) | STT/TTS/agents | Realtime STT/TTS over `wss://api.tryhamsa.com/v1/realtime/ws` | Custom WS factory; agent by phone | medium |
| 16 | Fanar / QCRI (Qatar) | LLM/STT/TTS | `Fanar-C-2-27B`; `Fanar-3.0-Aura-Transcribe`; `Fanar-Aura-TTS-2` (Hamad, Huda) | OpenAI-compatible LLM swap; TTS capped at 20 req/day | high |
| 17 | CAMB.AI (Dubai) | TTS | `mars-flash`, `mars-pro` (Saudi Arabic) | `livekit-plugins-cambai` TTS swap | medium |
| 18 | Maqsam (KSA) | Phone agent | Maqsam Voice AI Agent | Dial a pilot number over SIP (sales-only) | medium |
| 19 | Vapi (US) | Platform | Azure ar-SA or Deepgram ar + ElevenLabs | Phone bracket via SIP | medium |
| 20 | Retell (US) | Platform | ar-SA agent | Phone bracket via SIP | medium |

Also worth adding: Gladia `solaria-3`, xAI `grok-voice-3.0`, Mistral `voxtral-mini-tts-3` / `voxtral-mini-transcribe-realtime-3`, Telnyx (Arabic `Telnyx.Bayan` TTS + GCC SIP), and Cohere Transcribe Arabic (batch only).
Sales-only phone agents (Unifonic, Dayl, Hams.AI, ZIWO, Arabic.AI/HeyBreez) are only worth adding if we get a pilot line.

## Local models (Mac, Ollama / MLX)

| Model | Licence | GGUF / pull |
|---|---|---|
| ALLaM-7B-Instruct-preview (HUMAIN) | Apache-2.0 | `ollama pull hf.co/bartowski/ALLaM-AI_ALLaM-7B-Instruct-preview-GGUF:Q4_K_M` |
| Jais-3-7B / 3.7B / 32B / MoVA-36B-A4B (Inception42, Oct 2026) | Apache-2.0 | `hf.co/IFM/Jais-3-7B-GGUF:Q4_K_M` (official). Needs llama.cpp with K2 Horizon support; Ollama compatibility not verified, so fall back to `llama-server -hf ... --jinja` |
| Jais-2-8B-Chat | Apache-2.0 (gated) | `hf.co/inception42/Jais-2-8B-Chat-GGUF:Q4_K_M` |
| Fanar-1-9B-Instruct (QCRI) | Apache-2.0 | `hf.co/mradermacher/Fanar-1-9B-Instruct-GGUF:Q4_K_M` |
| Fanar-2-27B-Instruct | Apache-2.0 tag (Gemma-3 base) | `hf.co/mradermacher/Fanar-2-27B-Instruct-i1-GGUF:i1-Q4_K_M` (~16.5 GB, tight on 24 GB) |
| Falcon-H1-7B-Instruct (TII, multilingual) | Falcon LLM licence | `hf.co/tiiuae/Falcon-H1-7B-Instruct-GGUF:Q4_K_M` (Falcon-H1-Arabic repos not public when checked) |
| SILMA-9B-Instruct | Gemma | `hf.co/bartowski/SILMA-9B-Instruct-v1.0-GGUF:Q4_K_M` |
| Command R7B Arabic | CC-BY-NC | `hf.co/matrixportalx/c4ai-command-r7b-arabic-02-2025-GGUF` |
| STT: IFM/Jais-ASR | Apache-2.0 | MLX `IFM/Jais-ASR-MLX-4bit` (patched mlx-vlm), GGUF `IFM/Jais-ASR-GGUF`; 19 dialects incl. SA/AE/QA/KW/BH/OM |
| STT: Cohere Transcribe Arabic | Apache-2.0 (gated) | GGUF `handy-computer/cohere-transcribe-arabic-07-2026-gguf` |
| STT: NAMAA-Saudi-ASR-V1 | Apache-2.0 | LoRA on Cohere Transcribe Arabic |
| TTS: NAMAA-Saudi-TTS | MIT | Chatterbox fine-tune (Najdi) |
| TTS: silma-tts | Apache-2.0 | ar/en |
| TTS: Habibi-TTS, NAMAA-Saudi-TTS-V2 | CC-BY-NC-SA | dialectal; benchmark only |

## Key caveats

- Hume's TTS and EVI APIs shut down on 13 Nov 2026, so leave Hume out.
- Deepgram has no Arabic in Aura TTS or Flux. Cartesia has no Arabic in Ink-2 STT. AWS has no Arabic in Nova Sonic. Azure Voice Live's automatic multilingual mode doesn't cover Arabic, so set ar-SA explicitly.
- Fanar's default quotas are 20 TTS and 50 STT requests a day, which is too few for full runs without a quota raise.
- Score phone-only platforms in a separate bracket. PSTN adds latency and narrows audio to 8 kHz.
- Dropped after checking: Mozn, Presight and Core42 (no voice product found), NeuralSpace (no 2026 activity found), Falcon-ASR (no weights yet). Intella's old domain intella.ai is for sale, and no current site was found.
- Project memory says LiveKit Inference credits are exhausted, so use direct `livekit-plugins-*` with vendor keys.
