"""Turn the raw call artefacts of a run into metrics.json (+ judge.json, report.html).

Measured from the recording (what a caller actually experiences):
  response latency    end of caller speech -> first agent audio, per turn
  talk-over           agent started speaking while the caller was still talking
  barge-in            how long the agent keeps talking after the caller interrupts
Measured from the agent's own logs:
  STT accuracy        CER/WER of what the agent heard vs the caller's ground-truth text
  language switching  did each reply come back in the expected language
  internal latency    end-of-turn delay, LLM TTFT, TTS TTFB (LiveKit metrics)
Measured by re-transcribing the agent's audio (ElevenLabs Scribe):
  TTS intelligibility CER of the spoken reply vs the text the LLM produced
  spoken language     language the caller actually heard
"""

from __future__ import annotations

import asyncio
import json
import statistics
import wave
from pathlib import Path
from typing import Any

import aiohttp
import numpy as np

from . import transcribe
from .config import SAMPLE_RATE as SR
from .textnorm import cer, detect_lang, lang_matches, wer

VOICE_RMS = 350
MERGE_GAP = 0.5
MIN_SEG = 0.12


def _load_json(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return default


def _read_events(p: Path) -> list[dict[str, Any]]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            pass
    return out


def load_wav(p: Path) -> np.ndarray:
    with wave.open(str(p), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        return data.reshape(-1, w.getnchannels())


def speech_segments(ch: np.ndarray) -> list[tuple[float, float]]:
    n = SR // 100
    frames = len(ch) // n
    if frames == 0:
        return []
    x = ch[: frames * n].astype(np.float32).reshape(frames, n)
    voiced = np.sqrt((x**2).mean(axis=1)) > VOICE_RMS
    segs: list[list[float]] = []
    for i, v in enumerate(voiced):
        if not v:
            continue
        t = i / 100
        if segs and t - segs[-1][1] <= MERGE_GAP:
            segs[-1][1] = t + 0.01
        else:
            segs.append([t, t + 0.01])
    return [(round(a, 3), round(b, 3)) for a, b in segs if b - a >= MIN_SEG]


def _pct(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    vals = sorted(vals)
    k = (len(vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 1)


def _mean(vals: list[float | None]) -> float | None:
    v = [x for x in vals if x is not None]
    return round(statistics.mean(v), 4) if v else None


def _family(lang: str) -> str:
    return "ar" if lang.startswith("ar") else lang


def composite(s: dict[str, Any]) -> dict[str, Any]:
    parts: dict[str, tuple[float, float]] = {}
    p50 = s.get("latency_p50_ms")
    if p50 is not None:
        parts["latency"] = (max(0.0, min(100.0, (3000 - p50) / (3000 - 700) * 100)), 0.20)
    if s.get("lang_accuracy") is not None:
        parts["switching"] = (s["lang_accuracy"] * 100, 0.25)
    if s.get("stt_error") is not None:
        parts["stt"] = ((1 - s["stt_error"]) * 100, 0.15)
    if s.get("tts_cer") is not None:
        parts["tts"] = ((1 - s["tts_cer"]) * 100, 0.10)
    if s.get("judge_overall") is not None:
        parts["quality"] = (s["judge_overall"] * 10, 0.25)
    rel = 100 - 25 * (s.get("no_response", 0) + s.get("errors", 0))
    parts["reliability"] = (max(0, rel), 0.05)
    w = sum(x[1] for x in parts.values())
    score = sum(v * wt for v, wt in parts.values()) / w if w else None
    return {"score": round(score, 1) if score is not None else None, "parts": {k: round(v[0], 1) for k, v in parts.items()}}


def caller_score(s: dict[str, Any]) -> dict[str, Any]:
    """Score from what the caller experiences only, so hosted black-box agents (phone, web) and our own pipelines
    compare like for like: response time, replying in the caller's language (as heard), answer quality, task
    success and reliability. This is the headline number for cross-provider comparisons."""
    parts: dict[str, tuple[float, float]] = {}
    p50 = s.get("latency_p50_ms")
    if p50 is not None:
        parts["speed"] = (max(0.0, min(100.0, (3000 - p50) / (3000 - 700) * 100)), 0.25)
    if s.get("spoken_lang_accuracy") is not None:
        parts["language"] = (s["spoken_lang_accuracy"] * 100, 0.20)
    if s.get("judge_overall") is not None:
        parts["quality"] = (s["judge_overall"] * 10, 0.25)
    if s.get("judge_task_success") is not None:
        parts["task"] = (s["judge_task_success"] * 100, 0.20)
    rel = 100 - 25 * (s.get("no_response", 0) + s.get("errors", 0) + s.get("turns_not_reached", 0))
    parts["reliability"] = (max(0, rel), 0.10)
    w = sum(x[1] for x in parts.values())
    score = sum(v * wt for v, wt in parts.values()) / w if w else None
    return {"score": round(score, 1) if score is not None else None, "parts": {k: round(v[0], 1) for k, v in parts.items()}}


async def analyze_run(run_dir: Path, judge: bool = True, rescribe: bool = False) -> dict[str, Any]:
    meta = _load_json(run_dir / "meta.json", {})
    scenario = _load_json(run_dir / "scenario.json", {})
    call = _load_json(run_dir / "caller_turns.json", {})
    history = _load_json(run_dir / "sut_history.json", [])
    events = _read_events(run_dir / "sut_events.jsonl")
    t0 = call.get("t0", 0.0)
    turns = call.get("turns", [])

    if not (run_dir / "call.wav").exists() or not turns:
        metrics = {"run_id": meta.get("run_id"), "failed": True, "error": meta.get("call_error") or (call.get("errors") or ["no turns recorded"])[0]}
        (run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1))
        from .report import write_run_report, write_index

        write_run_report(run_dir)
        write_index()
        return metrics

    wav = load_wav(run_dir / "call.wav")
    sut_ch = wav[:, 1]
    segs = speech_segments(sut_ch)
    audio_end = len(sut_ch) / SR

    def rel(t: float | None) -> float | None:
        return None if t is None else t - t0

    # ---- map agent chat messages onto caller turns --------------------------------
    starts = [t["t_start"] for t in turns]

    def turn_for(t_rel: float, slack: float) -> int:
        idx = -1
        for i, s in enumerate(starts):
            if t_rel >= s + slack:
                idx = i
        return idx

    heard: dict[int, list[str]] = {}
    replies: dict[int, list[dict[str, Any]]] = {}
    user_msgs: dict[int, list[dict[str, Any]]] = {}
    for m in history:
        mt = m.get("metrics") or {}
        t_started = mt.get("started_speaking_at") or m.get("created_at")
        tr = rel(t_started)
        if tr is None:
            continue
        if m["role"] == "user":
            i = turn_for(tr, -0.5)
            heard.setdefault(i, []).append(m.get("text", ""))
            user_msgs.setdefault(i, []).append(m)
        elif m["role"] == "assistant":
            i = turn_for(tr, 0.3)
            replies.setdefault(i, []).append(m)

    # ---- per-turn timing from the recording --------------------------------------
    rows: list[dict[str, Any]] = []
    for i, t in enumerate(turns):
        nxt = turns[i + 1]["t_start"] if i + 1 < len(turns) else audio_end
        win = [s for s in segs if s[0] >= t["t_start"] + 0.3 and s[0] < nxt]
        onset = win[0][0] if win else None
        end = min(win[-1][1], nxt) if win else None
        lat = round((onset - t["t_end"]) * 1000) if onset is not None else None
        talk_over = onset is not None and onset < t["t_end"] - 0.15
        row: dict[str, Any] = {
            "idx": i,
            "lang": t["lang"],
            "expect": t["expect"],
            "caller_text": t["text"],
            "generated": t.get("generated", False),
            "t_start": t["t_start"],
            "t_end": t["t_end"],
            "interrupt": t.get("interrupt", False),
            "onset": onset,
            "reply_end": end,
            "latency_ms": lat,
            "talk_over": talk_over,
            "no_response": onset is None,
            "heard": " ".join(heard.get(i, [])).strip(),
            "reply_text": " ".join(r.get("text", "") for r in replies.get(i, [])).strip(),
            "reply_interrupted": any(r.get("interrupted") for r in replies.get(i, [])),
        }
        # barge-in: this caller line started while the agent was still talking
        if t.get("interrupt"):
            covering = [s for s in segs if s[0] < t["t_start"] < s[1] + 0.05]
            if covering:
                row["barge_in_stop_ms"] = round((covering[-1][1] - t["t_start"]) * 1000)
                row["barge_in_yielded"] = covering[-1][1] < t["t_end"]
            else:
                row["barge_in_stop_ms"] = 0
                row["barge_in_yielded"] = True
        # agent-internal latency breakdown (LiveKit metrics)
        um = (user_msgs.get(i) or [{}])[-1].get("metrics") or {}
        am = (replies.get(i) or [{}])[0].get("metrics") or {}
        row["internal"] = {
            k: round(v * 1000) if isinstance(v, (int, float)) else None
            for k, v in {
                "end_of_turn_delay": um.get("end_of_turn_delay"),
                "transcription_delay": um.get("transcription_delay"),
                "llm_ttft": am.get("llm_node_ttft"),
                "tts_ttfb": am.get("tts_node_ttfb"),
                "agent_e2e": (am.get("started_speaking_at") - um.get("stopped_speaking_at"))
                if am.get("started_speaking_at") and um.get("stopped_speaking_at")
                else None,
            }.items()
        }
        rows.append(row)

    # ---- what the agent actually said out loud (Scribe) ---------------------------
    cache_p = run_dir / "spoken.json"
    spoken: dict[str, Any] = {} if rescribe else _load_json(cache_p, {})
    sem = asyncio.Semaphore(2)

    async def _scribe(key: str, a: float, b: float, http: aiohttp.ClientSession) -> None:
        if key in spoken and not spoken[key].get("error"):
            return
        seg = sut_ch[int(max(0, a - 0.1) * SR) : int((b + 0.2) * SR)]
        if len(seg) < SR * 0.2:
            return
        async with sem:
            try:
                d = await transcribe.transcribe(seg, http)
                spoken[key] = {"text": d.get("text", ""), "language_code": d.get("language_code"), "engine": d["engine"]}
            except Exception as e:  # noqa: BLE001
                spoken[key] = {"text": "", "error": str(e)}

    async with aiohttp.ClientSession() as http:
        jobs = [_scribe(str(r["idx"]), r["onset"], r["reply_end"], http) for r in rows if r["onset"] is not None]
        g_on, g_end = call.get("greeting_onset"), call.get("greeting_end")
        if g_on is not None and g_end is not None:
            jobs.append(_scribe("greeting", g_on, g_end, http))
        await asyncio.gather(*jobs)
    cache_p.write_text(json.dumps(spoken, ensure_ascii=False, indent=1))

    # alternative references (numbers written as digits etc.), from the live scenario file and the run copy
    alt_refs: dict[str, list[str]] = {}
    live = Path(__file__).resolve().parent.parent / "scenarios" / f"{meta.get('scenario_id', '')}.yaml"
    sources = [scenario]
    if live.exists():
        import yaml

        sources.append(yaml.safe_load(live.read_text()))
    for sc in sources:
        for t in sc.get("turns", []):
            if t.get("text") and t.get("alt"):
                alt_refs.setdefault(t["text"], []).extend(t["alt"])

    def best(fn, ref: str, hyp: str) -> float | None:  # noqa: ANN001
        """Closest of: the reference, its written-number alternatives, and a number-agnostic
        comparison (number formatting is not an STT error; the judge checks numbers)."""
        vals = [fn(x, hyp) for x in [ref, *alt_refs.get(ref, [])]] + [fn(ref, hyp, numbers=False)]
        vals = [v for v in vals if v is not None]
        return min(vals) if vals else None

    prev_family = None
    for r in rows:
        sp = spoken.get(str(r["idx"]), {})
        r["spoken_text"] = sp.get("text", "")
        r["spoken_lang_code"] = sp.get("language_code")
        reply = r["reply_text"] or r["spoken_text"]
        r["reply_lang"] = detect_lang(reply)
        r["lang_ok"] = lang_matches(r["expect"], reply) if not r["no_response"] else False
        r["spoken_lang_ok"] = lang_matches(r["expect"], r["spoken_text"]) if r["spoken_text"] else False
        fam = _family(r["lang"])
        r["is_switch"] = prev_family is not None and fam != prev_family
        prev_family = fam
        has_heard = not meta.get("blackbox") and (r["heard"] or not r["no_response"])
        r["stt_cer"] = best(cer, r["caller_text"], r["heard"]) if has_heard else None
        r["stt_wer"] = best(wer, r["caller_text"], r["heard"]) if has_heard else None
        r["stt_error"] = r["stt_wer"] if r["lang"] == "en" else r["stt_cer"]
        if r["reply_text"] and r["spoken_text"]:
            # strict = numbers included (catches "230" spoken as "130"); the score uses the
            # number-agnostic value so LLM digit-vs-word formatting doesn't count against the TTS
            r["tts_cer_strict"] = cer(r["reply_text"], r["spoken_text"])
            r["tts_cer"] = min(r["tts_cer_strict"], cer(r["reply_text"], r["spoken_text"], numbers=False) or 0.0)
        else:
            r["tts_cer_strict"] = r["tts_cer"] = None

    # ---- summary -----------------------------------------------------------------
    def lat_of(rs: list[dict[str, Any]]) -> list[float]:
        return [r["latency_ms"] for r in rs if r["latency_ms"] is not None and not r["interrupt"] and not r["talk_over"]]

    lats = lat_of(rows)
    groups = sorted({r["lang"] for r in rows})
    sut_errors = [e for e in events if e.get("kind") == "error"]
    rtts = call.get("rtt_ms") or []
    scored = [r for r in rows if r["expect"] != "any"]
    switch_rows = [r for r in scored if r["is_switch"]]
    barge = [r for r in rows if r["interrupt"]]

    def internal(k: str) -> float | None:
        v = [r["internal"][k] for r in rows if r["internal"].get(k) is not None]
        return _pct(v, 0.5)

    summary: dict[str, Any] = {
        "turns": len(rows),
        "latency_p50_ms": _pct(lats, 0.5),
        "latency_p90_ms": _pct(lats, 0.9),
        "latency_mean_ms": round(statistics.mean(lats)) if lats else None,
        "latency_by_lang": {g: _pct(lat_of([r for r in rows if r["lang"] == g]), 0.5) for g in groups},
        "network_rtt_ms": _pct(rtts, 0.5),
        "internal_p50_ms": {k: internal(k) for k in ("end_of_turn_delay", "transcription_delay", "llm_ttft", "tts_ttfb", "agent_e2e")},
        "stt_error": _mean([r["stt_error"] for r in rows]),
        "stt_error_by_lang": {g: _mean([r["stt_error"] for r in rows if r["lang"] == g]) for g in groups},
        "lang_accuracy": round(sum(r["lang_ok"] for r in scored) / len(scored), 3) if scored else None,
        "switch_accuracy": round(sum(r["lang_ok"] for r in switch_rows) / len(switch_rows), 3) if switch_rows else None,
        "spoken_lang_accuracy": round(sum(r["spoken_lang_ok"] for r in scored) / len(scored), 3) if scored else None,
        "tts_cer": _mean([r["tts_cer"] for r in rows]),
        "no_response": sum(r["no_response"] for r in rows),
        "talk_over": sum(r["talk_over"] for r in rows if not r["interrupt"]),
        "barge_in_stop_ms": _pct([r["barge_in_stop_ms"] for r in barge], 0.5) if barge else None,
        "barge_in_yield_rate": round(sum(r["barge_in_yielded"] for r in barge) / len(barge), 3) if barge else None,
        "errors": len(sut_errors),
        "greeting_spoken": spoken.get("greeting", {}).get("text"),
        "greeting_onset_s": call.get("greeting_onset"),
        "blackbox": bool(meta.get("blackbox")),
        "path": meta.get("path", "LiveKit WebRTC"),
    }

    metrics: dict[str, Any] = {
        "run_id": meta.get("run_id"),
        "stack_id": meta.get("stack", {}).get("id"),
        "stack_name": meta.get("stack", {}).get("name"),
        "scenario_id": meta.get("scenario_id"),
        "mode": meta.get("mode"),
        "date": meta.get("date"),
        "summary": summary,
        "turns": rows,
        "sut_errors": [e.get("error") for e in sut_errors][:20],
        "caller_errors": call.get("errors", []),
    }

    if judge:
        from .judge import judge_run

        try:
            j = await judge_run(scenario, rows, meta)
            (run_dir / "judge.json").write_text(json.dumps(j, ensure_ascii=False, indent=1))
        except Exception as e:  # noqa: BLE001
            j = {"error": repr(e)}
    else:
        j = _load_json(run_dir / "judge.json", {})
    if j and not j.get("error"):
        summary["judge_overall"] = j.get("overall_score")
        summary["judge_task_success"] = j.get("task_success")
        summary["dialect_accuracy"] = j.get("dialect_accuracy")
        metrics["judge"] = j
        for jt in j.get("turns", []):
            for r in rows:
                if r["idx"] == jt.get("idx"):
                    r["judge"] = jt
    summary["composite"] = composite(summary)
    inc = meta.get("incomplete") or {}
    summary["incomplete"] = bool(inc)
    summary["turns_not_reached"] = max(0, inc.get("turns_total", 0) - inc.get("turns_done", 0)) if inc else 0
    summary["caller_score"] = caller_score(summary)
    summary["transcriber"] = sorted({v.get("engine", "elevenlabs-scribe") for v in spoken.values() if v.get("text")})

    (run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1))
    from .report import write_index, write_run_report

    write_run_report(run_dir)
    write_index()
    return metrics
