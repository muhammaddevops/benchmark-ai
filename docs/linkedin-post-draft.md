# Draft post: "Can the Gulf's own AI models hold a Saudi phone call?"

Status: draft for the user to edit. Numbers are from the runs of 2026-11-10 (bracket A, local open models);
re-check them against `results/charts/gulf-open-llms/leaderboard.csv` before posting.

---

We put the Gulf's own open AI models on a real phone-style call with a Saudi customer who switches between
Arabic and English mid-sentence, the way people actually talk in Riyadh.

Same caller, same three calls (clinic booking, a telecom bill dispute, a declined bank card), same speech
recognition and voice, on one laptop. The only thing that changed was the model doing the thinking:

- ALLaM 7B (Saudi Arabia) — {allam_score}/100
- Falcon-H1 7B (UAE) — {falconh1_score}/100
- Fanar 1 9B (Qatar) — {fanar_score}/100
- Qwen3 8B (global reference) — {qwen_score}/100
- Falcon 3 7B (UAE) — {falcon3_score}/100

What stood out:
- {finding_1}
- {finding_2}
- Every model struggled to answer English questions in English once the call had started in Arabic.

How it's scored: a "caller score" built only from what the caller experiences: response time, replying in the
caller's language, answer quality and task success (judged against the business's own facts), reliability.

Caveats: small open models (7-9B), quantised, running on a MacBook, with local speech recognition and system
voices, so absolute speed and voice quality are not what these vendors offer in production. This compares the
models' Arabic conversation skills under identical conditions, nothing more. 3 calls per model; one automated judge.

Next: the hosted versions, Arabic speech-to-text (HUMAIN, Munsit, Nabrah, Sarj vs global), and the Gulf's voice-agent
platforms by phone. Which provider should we call next?

[video: comparison montage] [image: caller score chart]
