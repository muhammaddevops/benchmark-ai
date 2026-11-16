# LinkedIn comparison playbook

How to turn this repo into a "Gulf voice AI, compared" post: which comparisons are fair, what each needs from
you, and the commands. Each bracket is its own chart (and ideally its own post); never mix brackets on one chart.

## Who it's for, and the order

The buyer is a Gulf business choosing a voice AI vendor for its customer calls (decided 2026-11-15), not the
vendors. So:

1. **E. Hosted voice agents** first: it's what a business actually buys ("we called 10 voice agents with the same
   Saudi customer"). It needs a pilot from each vendor: `docs/vendor-outreach.md`.
2. **B. Arabic speech-to-text** next: one component changes and everything else is held constant, so it shows the
   method is rigorous.
3. C, D and A support them. A (open models on a Mac) is done; label it "on a laptop".

The caller stays Saudi for now (decided 2026-11-16); add an Emirati caller later if UAE buyers ask for one.

Besides the scores, a buyer will ask each vendor's price per minute, where calls and data are processed, and which
dialects and channels it covers. Collect those during the pilot and quote them as the vendor's own figures.

**How the call reaches a hosted agent (E).** Our caller dials out through Twilio in the US with a US caller ID, so a
Gulf number is an international call. Twilio's docs list +966 and +971 as reachable, but no call has tested it, and
international routes into the Gulf can replace the caller ID, degrade the audio or fail. (Calls placed *from*
inside the UAE or from UAE numbers must go through du or e&, usually via an SBC; that's the vendor's side, not
ours.) Where a vendor offers a SIP address, call that instead: a LiveKit outbound trunk pointed at it, set as the
stack's `phone.trunk_env`. No phone network, no Gulf carrier, wideband audio. Use one path for every agent in a
chart and name it on the method card.

## Brackets

| Bracket | Systems | What you need to provide | Cost / effort |
|---|---|---|---|
| **A. Gulf open LLMs on a Mac** (runs today) | ALLaM 7B (KSA), Fanar 1 9B (QA), Falcon-H1 7B and Falcon 3 7B (UAE), Jais 3 7B (UAE) vs Qwen3 8B | nothing (local speech + Ollama) | free; ~5 min per call |
| **B. Arabic speech-to-text** | Munsit, Nabrah, Sarj, Fanar vs Speechmatics, Soniox, Deepgram, Azure, Google, AssemblyAI, AWS, ElevenLabs | each vendor's key + `OPENAI_API_KEY` (reference LLM) + ElevenLabs quota (reference TTS) | vendor trials; cents per call |
| **C. Arabic text-to-speech** | Munsit/Faseeh (Najdi, Emirati), Sarj, Fanar, CAMB.AI vs ElevenLabs, Azure Gulf voices, Polly, Cartesia, OpenAI | as B | as B |
| **D. Speech-to-speech** | OpenAI Realtime (+ mini), Gemini Live, xAI Grok Voice | `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY` | ~$0.10-0.30 per call |
| **E. Hosted voice agents by phone** | Maqsam, Nabrah, Hamsa, Unifonic, Hams.AI, Dayl, ZIWO, Wittify, Sawt, Arabic.AI vs Vapi, Retell, ElevenLabs Agents, Synthflow, Bland | a pilot agent per platform with the brief pasted in, reachable at a SIP address (preferred) or a phone number; for Gulf numbers, Twilio geo permissions for +966/+971 (the Twilio trunk exists since 2026-11-14) | Twilio international minutes (check rates); platform pilots via sales |

Bracket E is the most LinkedIn-friendly ("we called 10 Gulf AI agents") but needs the most from you: most domestic
platforms are sales-only. Brackets B and C are the most credible technically (one component changes, everything
else is held constant). Bracket A is free and shows the method; label it "on a laptop".

## Per bracket

1. Add the keys to `.env` (names in `.env.example`); `bench doctor` and `bench list` confirm the stacks are ready.
2. Run all three scenarios per system, one bracket at a time, in the background:

   ```bash
   .venv/bin/python -m bench run -s stt-munsit -s stt-nabrah -s stt-speechmatics -s ref-pipeline -c all
   ```

3. Use one judge for the whole bracket (a hosted one for a public post):

   ```bash
   BENCH_JUDGE=openai:gpt-5.5 .venv/bin/python -m bench rejudge -s stt-munsit -s stt-nabrah -s stt-speechmatics -s ref-pipeline
   ```

4. Charts for the post (PNG in landscape, square and 4:5, plus an animated MP4):

   ```bash
   .venv/bin/python -m bench charts -s stt-munsit -s stt-nabrah -s stt-speechmatics -s ref-pipeline --name arabic-stt --kicker "Arabic speech-to-text"
   ```

5. The comparison video (title card, each system answering the same caller lines, animated charts, method card):

   ```bash
   .venv/bin/python -m bench montage -s stt-munsit -s stt-nabrah -s stt-speechmatics -s ref-pipeline -c clinic_booking_codeswitch --format square --name arabic-stt
   ```

## Before posting

- At least 3 calls per system (all scenarios); smaller samples are labelled on the chart.
- Same judge for everyone (`bench charts` warns otherwise).
- Name the network path and hardware: "calls placed from Dubai over LiveKit Cloud", "local models on an M4 Pro".
- Hosted platforms: use the brief as written and the platform's default Arabic settings; say which voice/model.
- Send each vendor its own numbers before publishing if you want a friendlier reception; vendors often ask.
- Recordings contain the synthetic caller's voice and the vendor's voice: fine to post; don't post any real
  customer audio.
