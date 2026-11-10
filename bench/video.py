"""Render a benchmark call as a video: two speaker panels with live waveforms, captions as each side speaks, a
response-time stopwatch, and a results card at the end. For LinkedIn posts (landscape, square or vertical).

  python -m bench video <run|latest> [--format landscape|square|vertical] [--turns 0-2] [--gap 0.8] [--fps 25]

Honesty rules: the agent's response gaps (caller stops -> agent starts) are never shortened. Only the caller's own
"thinking" pauses (agent finished -> caller's next line) and the wait before the greeting are trimmed to ``--gap``
seconds, so a clip moves along without changing anything the agent did.
"""

from __future__ import annotations

import json
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .config import RESULTS_DIR, SAMPLE_RATE

TEMPLATE = Path(__file__).parent / "templates" / "call.html"
SIZES = {"landscape": (1920, 1080), "square": (1080, 1080), "vertical": (1080, 1920)}
LANG_LABEL = {"en": "English", "ar": "Arabic", "mixed": "Arabic + English", "none": "No reply"}


@dataclass
class Cut:
    """Keep [start, end) of the original call; segments are played back to back."""

    start: float
    end: float


def _load(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    m = json.loads((run_dir / "metrics.json").read_text())
    meta = json.loads((run_dir / "meta.json").read_text())
    call = json.loads((run_dir / "caller_turns.json").read_text()) if (run_dir / "caller_turns.json").exists() else {}
    return m, meta, call


def _audio(run_dir: Path) -> np.ndarray:
    with wave.open(str(run_dir / "call.wav")) as w:
        assert w.getframerate() == SAMPLE_RATE and w.getnchannels() == 2
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, 2)


def _envelope(ch: np.ndarray, fps: int) -> list[float]:
    hop = SAMPLE_RATE // fps
    n = len(ch) // hop
    x = ch[: n * hop].astype(np.float32).reshape(n, hop) / 32768.0
    rms = np.sqrt((x**2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    v = np.clip((db + 50) / 44, 0, 1)  # -50 dBFS -> 0, -6 dBFS -> 1
    return [round(float(a), 3) for a in v]


def timeline(run_dir: Path, turns: tuple[int, int] | None = None) -> dict[str, Any]:
    """Speech events on the original call clock."""
    m, meta, call = _load(run_dir)
    rows = m["turns"]
    if turns:
        rows = [r for r in rows if turns[0] <= r["idx"] <= turns[1]]
    caller, agent, gaps = [], [], []
    greet_on, greet_end = call.get("greeting_onset"), call.get("greeting_end")
    if greet_on is not None and (not turns or turns[0] == 0):
        g_text = m["summary"].get("greeting_spoken") or ""
        agent.append({"start": greet_on, "end": greet_end or greet_on + 3, "text": g_text, "lang_ok": None,
                      "reply_lang_label": "Greeting"})
    for r in rows:
        caller.append({"start": r["t_start"], "end": r["t_end"], "text": r["caller_text"], "lang": r["lang"]})
        if r.get("onset") is not None:
            text = r.get("spoken_text") or r.get("reply_text") or ""
            ok = None if r.get("expect") == "any" else bool(r.get("spoken_lang_ok") if r.get("spoken_text") else r.get("lang_ok"))
            agent.append({"start": r["onset"], "end": r.get("reply_end") or r["onset"] + 2, "text": text, "lang_ok": ok,
                          "reply_lang_label": "Replied in " + LANG_LABEL.get(r.get("reply_lang") or "", "?")})
        if not r.get("interrupt") and not r.get("talk_over"):  # an agent talking over the caller has no gap to time
            gaps.append({"start": r["t_end"], "end": r["onset"] if r.get("onset") is not None else r["t_end"] + 8,
                         "latency_ms": r.get("latency_ms"), "no_response": bool(r.get("no_response"))})
    end = max([e["end"] for e in caller + agent] + [g["end"] for g in gaps]) + 0.8
    start = 0.0 if not turns or turns[0] == 0 else max(0.0, caller[0]["start"] - 0.8)
    return {"caller": caller, "agent": agent, "gaps": gaps, "start": start, "end": end, "metrics": m, "meta": meta}


def plan_cuts(tl: dict[str, Any], gap: float) -> list[Cut]:
    """Kept segments of the original call. Silences longer than `gap` are shortened to `gap`, except inside the
    agent's response gaps, which are treated as protected spans and always kept whole."""
    spans = sorted(
        [(e["start"], e["end"]) for e in tl["caller"] + tl["agent"]] + [(g["start"], g["end"]) for g in tl["gaps"]]
    )
    segs: list[Cut] = []
    seg_from = cur = tl["start"]
    for a, b in spans:
        if a > cur + gap:  # a long silence nobody is waiting through: keep gap/2 either side of it
            segs.append(Cut(seg_from, cur + gap / 2))
            seg_from = a - gap / 2
        cur = max(cur, b)
    segs.append(Cut(seg_from, tl["end"]))
    return [c for c in segs if c.end > c.start]


def _result_card(m: dict[str, Any]) -> dict[str, Any]:
    s = m["summary"]
    cs = (s.get("caller_score") or {}).get("score")
    cells = []
    p50 = s.get("latency_p50_ms")
    cells.append((f"{p50 / 1000:.2f} s" if p50 else "–", "Typical response time"))
    la = s.get("spoken_lang_accuracy")
    cells.append((f"{round(la * 100)}%" if la is not None else "–", "Replied in the caller's language"))
    jq = s.get("judge_overall")
    cells.append((f"{jq}/10" if jq is not None else "–", "Answer quality (judge)"))
    ts = s.get("judge_task_success")
    cells.append((f"{round(ts * 100)}%" if ts is not None else "–", "Task completed"))
    judge = (m.get("judge") or {}).get("model", "")
    note = f"Scripted mock call · scores from the recording" + (f" · judge {judge}" if judge else "")
    return {"score": round(cs) if cs is not None else None, "cells": cells, "note": note}


def build_data(run_dir: Path, turns: tuple[int, int] | None, gap: float, fps: int, label: str | None) -> tuple[dict[str, Any], list[Cut], np.ndarray]:
    tl = timeline(run_dir, turns)
    m, meta = tl["metrics"], tl["meta"]
    stack = meta.get("stack", {})
    audio = _audio(run_dir)
    cuts = plan_cuts(tl, gap)
    # remap every time onto the output clock
    offsets = []
    out_t = 0.0
    for c in cuts:
        offsets.append((c.start, c.end, out_t))
        out_t += c.end - c.start

    def remap(t: float) -> float:
        for a, b, o in offsets:
            if t < a:
                return o
            if t <= b:
                return o + (t - a)
        return out_t

    def remap_ev(e: dict[str, Any]) -> dict[str, Any]:
        return {**e, "start": round(remap(e["start"]), 3), "end": round(remap(e["end"]), 3)}

    pieces = [audio[int(c.start * SAMPLE_RATE) : int(c.end * SAMPLE_RATE)] for c in cuts]
    clip = np.concatenate(pieces) if pieces else audio[:0]
    provider = label or stack.get("display") or stack.get("name", stack.get("id", "Voice agent"))
    chips = [meta.get("scenario_title") or m.get("scenario_id", ""), "Via " + meta.get("path", "LiveKit WebRTC")]
    data = {
        "provider": provider,
        "agent_label": stack.get("short") or provider.split(" · ")[0],
        "agent_sub": stack.get("provider", "System under test"),
        "chips": [c for c in chips if c],
        "caller": [remap_ev(e) for e in tl["caller"]],
        "agent": [remap_ev(e) for e in tl["agent"]],
        "gaps": [{**remap_ev(g), "latency_ms": g["latency_ms"], "no_response": g["no_response"]} for g in tl["gaps"]],
        "end": round(out_t, 3),
        "env_fps": fps,
        "env_caller": _envelope(clip[:, 0], fps),
        "env_agent": _envelope(clip[:, 1], fps),
        "result": _result_card(m),
    }
    return data, cuts, clip


def render(run_dir: Path, fmt: str = "landscape", turns: tuple[int, int] | None = None, gap: float = 0.8,
           fps: int = 25, end_card: float = 4.0, out: Path | None = None, label: str | None = None) -> Path:
    from playwright.sync_api import sync_playwright

    data, cuts, clip = build_data(run_dir, turns, gap, fps, label)
    w, h = SIZES[fmt]
    videos = run_dir / "video"
    videos.mkdir(exist_ok=True)
    suffix = f"_t{turns[0]}-{turns[1]}" if turns else ""
    out = out or videos / f"call_{fmt}{suffix}.mp4"
    wav = videos / "_clip.wav"
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(clip.astype(np.int16).tobytes())
    total = data["end"] + end_card
    n = int(total * fps)
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
         "-i", str(wav), "-map", "0:v", "-map", "1:a",
         # both sides to both ears (caller is left, agent right in the recording), social-media loudness
         "-af", "pan=stereo|c0<c0+c1|c1<c0+c1,apad,loudnorm=I=-16:TP=-1.5:LRA=11",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps),
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", f"{total:.2f}", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        page.goto(TEMPLATE.as_uri())
        page.evaluate("([d, f]) => setup(d, f)", [data, fmt])
        page.wait_for_timeout(300)
        for i in range(n):
            t = i / fps
            end_p = max(0.0, (t - data["end"]) / end_card) if t > data["end"] else 0.0
            page.evaluate("([t, e]) => render(t, e)", [min(t, data["end"]), end_p])
            assert ff.stdin is not None
            ff.stdin.write(page.screenshot(type="jpeg", quality=90))
        browser.close()
    assert ff.stdin is not None
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    wav.unlink(missing_ok=True)
    (videos / "cuts.json").write_text(json.dumps([c.__dict__ for c in cuts], indent=1))
    return out


def still(run_dir: Path, t: float, fmt: str = "landscape", out: Path | None = None, end_p: float = 0.0,
          turns: tuple[int, int] | None = None) -> Path:
    """One frame as PNG (for checking the layout or a thumbnail)."""
    from playwright.sync_api import sync_playwright

    data, _, _ = build_data(run_dir, turns, 0.8, 25, None)
    w, h = SIZES[fmt]
    out = out or run_dir / "video" / f"still_{fmt}_{t:.0f}.png"
    out.parent.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h})
        page.goto(TEMPLATE.as_uri())
        page.evaluate("([d, f]) => setup(d, f)", [data, fmt])
        page.wait_for_timeout(300)
        page.evaluate("([t, e]) => render(t, e)", [t, end_p])
        page.screenshot(path=str(out))
        browser.close()
    return out


def parse_turns(s: str | None) -> tuple[int, int] | None:
    if not s:
        return None
    a, _, b = s.partition("-")
    return int(a), int(b or a)


def latest_run() -> Path:
    return sorted((RESULTS_DIR / "runs").iterdir())[-1]
