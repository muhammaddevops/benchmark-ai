# Draft post: "Can the Gulf's own AI models hold a Saudi phone call?"

Status: draft for the user to edit. Numbers are from the runs of 2026-11-10 (bracket A, local open models, judged by
local Qwen3 14B: rejudge with a hosted judge before posting, see the playbook);
re-check them against `results/charts/gulf-open-llms/leaderboard.csv` before posting.

---

We put the Gulf's own open AI models on a real phone-style call with a Saudi customer who switches between
Arabic and English mid-sentence, the way people actually talk in Riyadh.

Same caller, same three calls (clinic booking, a telecom bill dispute, a declined bank card), same speech
recognition and voice, on one laptop. The only thing that changed was the model doing the thinking:

- ALLaM 7B (Saudi Arabia) — 62/100
- Falcon-H1 7B (UAE) — 58/100
- Fanar 1 9B (Qatar) — 53/100
- Qwen3 8B (global reference) — 51/100
- Falcon 3 7B (UAE) — 43/100
- Jais 3 7B (UAE) — 29/100 (1 call; it reasons before every reply: 13 s waits on a laptop)

What stood out:
- The Saudi model, ALLaM, completed every task and had the best answers (8/10 from the judge), replying in
  colloquial Arabic: "وعليكم السلام، أهلاً بك. شو نوع الحجز اللي تبغى تعمله مع الدكتور؟" (Gulf "تبغى", though "شو"
  is more Levantine than Saudi: a Riyadh caller would expect "وش").
- Falcon-H1 (UAE) was best at replying in the caller's language (69% of turns); the global reference, Qwen3,
  repeated itself and slipped a Chinese word into an Arabic reply.
- Every model struggled to answer English questions in English once the call had started in Arabic.

How it's scored: a "caller score" built only from what the caller experiences: response time, replying in the
caller's language, answer quality and task success (judged against the business's own facts), reliability.

Caveats: small open models (7-9B), quantised, running on a MacBook, with local speech recognition and system
voices, so absolute speed and voice quality are not what these vendors offer in production. This compares the
models' Arabic conversation skills under identical conditions, nothing more. 3 calls per model; one automated judge.

Next: the hosted versions, Arabic speech-to-text (HUMAIN, Munsit, Nabrah, Sarj vs global), and the Gulf's voice-agent
platforms by phone. Which provider should we call next?

[video: comparison montage] [image: caller score chart]
