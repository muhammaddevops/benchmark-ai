"""LLM judge (any backend, see llmclient.py; local qwen3:14b by default): understanding, factual accuracy, dialect fit,
naturalness of code-switching, and task success, scored per turn and overall."""

from __future__ import annotations

import json
from typing import Any

from .llmclient import backend, chat, parse_json

SYSTEM = """You are an expert evaluator of bilingual (English / Arabic) voice AI agents for the Saudi and wider Gulf market.
You are fluent in English, Modern Standard Arabic (MSA/Fusha) and Gulf/Saudi colloquial Arabic (Khaleeji), and you know how bilingual Saudis code-switch.

You get: the agent's system instructions (the ground-truth business facts it was given), and a call transcript, turn by turn:
- caller_said: exactly what the simulated caller said (ground truth), with its language tag (en, ar-gulf, ar-msa, mixed)
- agent_heard: what the agent's speech recognition produced
- agent_reply: the text the agent generated
- agent_spoken: an independent transcription of the agent's audio (what the caller actually heard)
- expected_reply_language: en | ar | any

Score strictly and concretely. Return ONLY JSON:
{
 "turns": [
  {"idx": <int>,
   "understood": 0|1|2,          // 2 = fully understood the caller's intent and any details (numbers, names, dates); 0 = misunderstood
   "correct": 0|1|2,             // 2 = accurate and consistent with the business facts; 0 = wrong / hallucinated
   "reply_language": "en"|"ar"|"mixed"|"none",
   "dialect": "gulf"|"msa"|"egyptian"|"levantine"|"maghrebi"|"other"|"n/a",   // dialect of the agent's Arabic, n/a if no Arabic
   "dialect_ok": true|false|null, // does the agent's language/dialect fit the caller's turn and the instructions? null if not applicable
   "naturalness": 1-5,           // how natural it would sound to a bilingual Saudi caller on the phone (brevity, register, code-switching)
   "issue": "<short note of the main problem, or empty>"}
 ],
 "task_success": 0.0-1.0,        // how completely the caller's goals were achieved by the end of the call
 "overall_score": 0-10,          // overall quality of the agent as a bilingual phone agent (ignore latency)
 "strengths": ["..."],
 "weaknesses": ["..."],
 "summary": "<two sentences>"
}"""


async def judge_run(scenario: dict[str, Any], rows: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    transcript = [
        {
            "idx": r["idx"],
            "caller_lang": r["lang"],
            "caller_said": r["caller_text"],
            "agent_heard": r["heard"],
            "agent_reply": r["reply_text"],
            "agent_spoken": r.get("spoken_text", ""),
            "expected_reply_language": r["expect"],
            "no_response": r["no_response"],
        }
        for r in rows
    ]
    user = (
        f"AGENT SYSTEM INSTRUCTIONS:\n{scenario.get('sut_instructions', '')}\n\n"
        f"CALLER GOAL: {scenario.get('caller_goal', '')}\n\n"
        f"TRANSCRIPT:\n{json.dumps(transcript, ensure_ascii=False, indent=1)}"
    )
    if meta.get("blackbox"):
        user += ("\n\nNOTE: this agent is a black box (a hosted platform reached by phone or web). agent_heard and "
                 "agent_reply are unavailable; judge from caller_said and agent_spoken only.")
    b = backend("BENCH_JUDGE")
    data = parse_json(await chat(b, SYSTEM, user, json_mode=True))
    dia = [t.get("dialect_ok") for t in data.get("turns", []) if t.get("dialect_ok") is not None]
    data["dialect_accuracy"] = round(sum(bool(x) for x in dia) / len(dia), 3) if dia else None
    data["model"] = b.label
    return data
