"""Benchmark charts across stacks: PNGs for LinkedIn, interactive HTML with a table view, and an animated MP4.

  python -m bench charts [--stack ID ...] [--scenario ID ...] [--since 2026-11-10] [--name gulf-2026-11]

Every valid call of each stack is pooled: response times are medians over all turns, language and task figures are
shares over all turns or calls, quality is the mean judge score. Calls that failed to connect are left out.
"""

from __future__ import annotations

import csv
import json
import statistics
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import RESULTS_DIR, RUNS_DIR
from .stacks import load_stack

TEMPLATE = Path(__file__).parent / "templates" / "charts.html"
FORMATS = {"landscape": (1920, 1080), "square": (1080, 1080), "portrait": (1080, 1350), "vertical": (1080, 1920)}
LANGS = [("en", "English", "var(--series-1)"), ("ar-gulf", "Gulf Arabic", "var(--series-2)"),
         ("ar-msa", "MSA Arabic", "var(--series-3)"), ("mixed", "Arabic + English", "var(--series-4)")]


def _pct(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def valid(m: dict[str, Any]) -> bool:
    """A call counts if the agent answered at least once, or if it was up (it greeted, no errors logged) and simply
    never answered in time: that is the agent's failure (score 0), not a broken recording. A call whose agent logged
    errors and never answered (credits out, a crash) doesn't count."""
    s = m.get("summary", {})
    if (s.get("caller_score") or {}).get("score") is None:
        return False
    answered = [t for t in m.get("turns", []) if t.get("onset") is not None]
    up = s.get("greeting_onset_s") is not None and not s.get("errors")
    return bool(answered) or up


def collect(stacks: list[str] | None = None, scenarios: list[str] | None = None, since: str | None = None) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = {}
    for f in sorted(RUNS_DIR.glob("*/metrics.json")):
        m = json.loads(f.read_text())
        if not valid(m):
            continue
        if stacks and m.get("stack_id") not in stacks:
            continue
        if scenarios and m.get("scenario_id") not in scenarios:
            continue
        if since and (m.get("date") or "") < since:
            continue
        by.setdefault(m["stack_id"], []).append(m)
    rows = []
    for sid, ms in by.items():
        turns = [t for m in ms for t in m["turns"]]
        lat = [t["latency_ms"] for t in turns if t.get("latency_ms") is not None and not t.get("interrupt") and not t.get("talk_over")]
        scored = [t for t in turns if t.get("expect") != "any"]
        lang_ok = [bool(t.get("spoken_lang_ok") if t.get("spoken_text") else t.get("lang_ok")) for t in scored]
        judge = [m["summary"]["judge_overall"] for m in ms if m["summary"].get("judge_overall") is not None]
        task = [m["summary"]["judge_task_success"] for m in ms if m["summary"].get("judge_task_success") is not None]
        try:
            spec = load_stack(sid)
        except FileNotFoundError:
            spec = {"id": sid, "name": ms[0].get("stack_name", sid)}
        judges = sorted({(m.get("judge") or {}).get("model", "") for m in ms if m.get("judge")} - {""})
        sub = spec.get("display_sub") or spec.get("provider", "")
        row = {
            "id": sid,
            "label": spec.get("display") or spec.get("name", sid),
            "sub": f"{sub} · {len(ms)} call{'s' if len(ms) != 1 else ''}" if sub else f"{len(ms)} calls",
            "judges": judges,
            "complete": len(judge) == len(ms) and len(task) == len(ms),
            "n": len(ms),
            "scenarios": sorted({m["scenario_id"] for m in ms}),
            "score": round(statistics.mean(m["summary"]["caller_score"]["score"] for m in ms), 1),
            "p50": round(_pct(lat, 0.5) / 1000, 2) if lat else None,
            "p90": round(_pct(lat, 0.9) / 1000, 2) if lat else None,
            "language": round(100 * sum(lang_ok) / len(lang_ok)) if lang_ok else None,
            "quality": round(statistics.mean(judge), 1) if judge else None,
            "task": round(100 * statistics.mean(task)) if task else None,
            "path": ms[0]["summary"].get("path", "LiveKit WebRTC"),
            "blackbox": bool(ms[0]["summary"].get("blackbox")),
            "local": all(m.get("local_only") for m in ms),
        }
        for code, _, _ in LANGS:
            lv = [t["latency_ms"] for t in turns if t.get("lang") == code and t.get("latency_ms") is not None
                  and not t.get("interrupt") and not t.get("talk_over")]
            row[f"lat_{code}"] = round(_pct(lv, 0.5) / 1000, 2) if lv else None
        rows.append(row)
    return rows


def chart_specs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def ranked(key: str, reverse: bool = True) -> list[dict[str, Any]]:
        have = [r for r in rows if r.get(key) is not None]
        return sorted(have, key=lambda r: r[key], reverse=reverse)

    langs_present = [x for x in LANGS if any(r.get(f"lat_{x[0]}") is not None for r in rows)]
    return [
        {"id": "score", "key": "score", "title": "Caller experience score", "measure": "Score",
         "sub": "Out of 100: speed, replying in the caller's language, answer quality, task success and reliability",
         "rows": [r for r in ranked("score") if r["complete"]], "fmt": "Math.round(v) + ''", "tickFmt": "v", "max": 100},
        {"id": "latency", "key": "p50", "title": "How fast the agent replies", "measure": "Typical response time",
         "sub": "Seconds from the caller finishing to the agent starting to speak. Lower is better",
         "rows": ranked("p50", reverse=False), "fmt": "v.toFixed(2) + ' s'", "tickFmt": "v + ' s'",
         "tickKey": "p90", "tickName": "Slow end (9 in 10 replies are faster)"},
        {"id": "language", "key": "language", "title": "Replies in the caller's language", "measure": "Turns in the right language",
         "sub": "English, Gulf Arabic, MSA and code-switched turns; judged from what the caller heard",
         "rows": ranked("language"), "fmt": "v + '%'", "tickFmt": "v + '%'", "max": 100},
        {"id": "quality", "key": "quality", "title": "Answer quality", "measure": "Judge score",
         "sub": "Understanding, accuracy, Gulf dialect fit and naturalness, scored 0 to 10 by an LLM judge",
         "rows": ranked("quality"), "fmt": "v.toFixed(1)", "tickFmt": "v", "max": 10},
        {"id": "task", "key": "task", "title": "Did the caller get what they needed?", "measure": "Task success",
         "sub": "Share of each call's goals completed by the end of the call",
         "rows": ranked("task"), "fmt": "v + '%'", "tickFmt": "v + '%'", "max": 100},
        {"id": "latency_lang", "title": "Response time by the caller's language", "measure": "Typical response time",
         "sub": "Seconds, median per language. Lower is better",
         "rows": ranked("p50", reverse=False), "fmt": "v.toFixed(1) + ' s'", "tickFmt": "v + ' s'", "labelAll": True,
         "series": [{"key": f"lat_{c}", "name": n, "color": col, "fmt": "v.toFixed(1) + ' s'"} for c, n, col in langs_present]},
    ]


def _data(rows: list[dict[str, Any]], kicker: str) -> dict[str, Any]:
    calls = sum(r["n"] for r in rows)
    paths = sorted({r["path"] for r in rows})
    judges = sorted({j for r in rows for j in r.get("judges", [])})
    judge_note = ("Judge: " + ", ".join(judges)) if len(judges) == 1 else (
        "Mixed judges (" + ", ".join(judges) + "): run `bench rejudge` before publishing" if judges else "No judge scores")
    return {
        "brand": "Gulf Voice AI Benchmark",
        "kicker": kicker,
        "charts": chart_specs(rows),
        "foot1": f"<b>{calls} scripted mock calls</b> · {len(rows)} systems · Saudi/Gulf caller in English, Gulf Arabic, "
                 f"MSA and code-switched speech · connected via {', '.join(paths)}",
        "foot2": ("All calls ran on one Mac (no internet round trip)" if rows and all(r.get("local") for r in rows)
                  else "Response times include the network path to each provider")
                 + f" · {judge_note} · systems without complete judge "
                 "scores are left out of the overall score",
    }


def render_all(name: str, rows: list[dict[str, Any]], kicker: str = "", formats: tuple[str, ...] = ("landscape", "square", "portrait"),
               animate: bool = True) -> Path:
    from playwright.sync_api import sync_playwright

    out = RESULTS_DIR / "charts" / name
    out.mkdir(parents=True, exist_ok=True)
    data = _data(rows, kicker or datetime.now().strftime("%B %Y"))
    (out / "data.json").write_text(json.dumps({"rows": rows, **data}, ensure_ascii=False, indent=1))
    _write_csv(out / "leaderboard.csv", rows)
    _write_pages(out, data, rows)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for fmt in formats:
            w, h = FORMATS[fmt]
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(TEMPLATE.as_uri())
            for c in data["charts"]:
                if not c["rows"]:
                    continue
                page.evaluate("([d, id, f]) => setup(d, id, f)", [data, c["id"], fmt])
                page.wait_for_timeout(150)
                page.screenshot(path=str(out / f"{c['id']}_{fmt}.png"))
            page.close()
        if animate:
            _animate(browser, data, out / "charts_landscape.mp4", "landscape")
        browser.close()
    return out


def _animate(browser: Any, data: dict[str, Any], path: Path, fmt: str, fps: int = 25, grow: float = 1.4, hold: float = 3.4) -> None:
    w, h = FORMATS[fmt]
    page = browser.new_page(viewport={"width": w, "height": h})
    page.goto(TEMPLATE.as_uri())
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps),
         "-c:a", "aac", "-movflags", "+faststart", str(path)],
        stdin=subprocess.PIPE,
    )
    assert ff.stdin is not None
    for c in data["charts"]:
        if not c["rows"]:
            continue
        page.evaluate("([d, id, f]) => setup(d, id, f)", [data, c["id"], fmt])
        page.wait_for_timeout(100)
        for i in range(int((grow + hold) * fps)):
            page.evaluate("p => render(p)", min(1.0, i / (grow * fps)))
            ff.stdin.write(page.screenshot(type="jpeg", quality=92))
    ff.stdin.close()
    ff.wait()
    page.close()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    cols = ["label", "sub", "n", "score", "p50", "p90", "language", "quality", "task", "path", "id"] + [f"lat_{c}" for c, _, _ in LANGS]
    with path.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        for r in sorted(rows, key=lambda r: -r["score"]):
            wr.writerow(r)


def _write_pages(out: Path, data: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """index.html: every chart, interactive (hover tooltips), plus the full table."""
    tpl = TEMPLATE.read_text()
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    for c in data["charts"]:
        html = tpl.replace("</body>", f"<script>window.addEventListener('load',()=>setup({blob},{json.dumps(c['id'])},'landscape'));</script></body>")
        (out / f"{c['id']}.html").write_text(html)
    head = "".join(f"<th>{h}</th>" for h in ["System", "Calls", "Score /100", "Typical reply", "Slow end", "Right language", "Quality /10", "Task success"])
    body = "".join(
        f"<tr><td>{r['label']}</td><td>{r['n']}</td><td>{r['score']}</td><td>{_s(r['p50'])}</td><td>{_s(r['p90'])}</td>"
        f"<td>{_p(r['language'])}</td><td>{r['quality'] if r['quality'] is not None else '–'}</td><td>{_p(r['task'])}</td></tr>"
        for r in sorted(rows, key=lambda r: -r["score"])
    )
    frames = "".join(f'<iframe src="{c["id"]}.html" style="width:100%;aspect-ratio:16/9;border:0;border-radius:16px;margin-bottom:20px"></iframe>' for c in data["charts"])
    (out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Gulf Voice AI Benchmark</title>"
        "<body style='background:#0b1220;color:#eef2f7;font-family:Inter,system-ui,sans-serif'>"
        f"<div style='max-width:1200px;margin:0 auto;padding:24px'><h1 style='font-size:28px'>Gulf Voice AI Benchmark</h1>"
        f"<p style='color:#a8b4c7'>{data['foot1']}</p>{frames}<h2 style='font-size:22px'>Table</h2>"
        f"<table style='width:100%;border-collapse:collapse;font-size:14px'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        "<style>td,th{padding:8px 10px;border-bottom:1px solid #22304a;text-align:right}td:first-child,th:first-child{text-align:left}th{color:#a8b4c7}</style>"
        "</div></body>"
    )


def _s(v: float | None) -> str:
    return f"{v:.2f} s" if v is not None else "–"


def _p(v: float | None) -> str:
    return f"{v}%" if v is not None else "–"
