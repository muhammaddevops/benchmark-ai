"""A full written evaluation report across several systems: ranking, method, per-call comparison, a profile of each
system with real example turns, and an appendix of every call. HTML plus a print-ready PDF (A4).

  python -m bench fullreport -s <stack> -s <stack> ... [--since 2026-11-25] [--title ...] [--subtitle ...]
                             [--prepared-for "Client name"] [--notes notes.md] [--sample] [--name NAME]

It uses each system's latest valid run of each scenario (from --since on). --notes inserts your own written
recommendation (Markdown-ish: paragraphs, "- " bullets, "## " headings) at the top. --sample stamps every page
"Sample". Written to results/fullreports/<name>/.
"""

from __future__ import annotations

import html
import json
import re
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from .charts import _pct
from .config import RESULTS_DIR, SCENARIOS_DIR
from .montage import latest_run
from .stacks import load_stack

WEIGHTS = [("speed", "Speed", 25), ("language", "Language", 20), ("quality", "Quality", 25), ("task", "Task", 20),
           ("reliability", "Reliability", 10)]
LANG_NAMES = {"en": "English", "ar-gulf": "Gulf Arabic", "ar-msa": "MSA", "mixed": "Code-switched"}


def e(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def _num(v: Any, unit: str = "", nd: int = 0) -> str:
    if v is None:
        return "–"
    return f"{v:.{nd}f}{unit}" if isinstance(v, (int, float)) else e(v)


def _md(text: str) -> str:
    """Tiny Markdown subset for the evaluator's notes: ## headings, - bullets, **bold**, paragraphs."""
    out, items = [], []

    def inline(s: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", e(s))

    def flush() -> None:
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for block in re.split(r"\n\s*\n", text.strip()):
        for line in block.splitlines():
            if line.startswith("- "):
                items.append(line[2:])
            elif line.startswith("## "):
                flush()
                out.append(f"<h3>{inline(line[3:])}</h3>")
            else:
                flush()
                out.append(f"<p>{inline(line)}</p>")
        flush()
    return "\n".join(out)


def _calls(stacks: list[str], scenarios: list[str], since: str | None) -> dict[str, dict[str, dict[str, Any]]]:
    """stack -> scenario -> {metrics, meta, scenario, dir}"""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for s in stacks:
        for c in scenarios:
            d = latest_run(s, c, since)
            if d is None:
                continue
            out.setdefault(s, {})[c] = {
                "dir": d,
                "m": json.loads((d / "metrics.json").read_text()),
                "meta": json.loads((d / "meta.json").read_text()),
                "scen": json.loads((d / "scenario.json").read_text()),
            }
    return out


def _short(title: str) -> str:
    return re.split(r" — | \(| with ", title)[0]


def _about(sc: dict[str, Any]) -> str:
    return " ".join(x for x in (sc.get("caller_persona", "").strip(), ("Goal: " + sc["caller_goal"].strip()) if sc.get("caller_goal") else "") if x)


def _turn_examples(m: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The best and the worst turn of a call, judged by the judge's per-turn marks and the measured facts."""
    scored = []
    for t in m.get("turns", []):
        j = t.get("judge") or {}
        if t.get("no_response"):
            bad = 10.0
        else:
            bad = (2 - (j.get("understood") or 0)) + (2 - (j.get("correct") or 0)) * 1.5
            bad += 0 if t.get("spoken_lang_ok", t.get("lang_ok", True)) or t.get("expect") == "any" else 2
            bad += (5 - (j.get("naturalness") or 3)) * 0.3
            bad += max(0.0, ((t.get("latency_ms") or 0) - 3000) / 2000)
        scored.append((bad, t))
    if not scored:
        return None, None
    scored.sort(key=lambda x: x[0])
    best = scored[0][1] if scored[0][1].get("spoken_text") or scored[0][1].get("reply_text") else None
    worst = scored[-1][1] if scored[-1][0] >= 2 else None
    return best, worst


def _turn_html(t: dict[str, Any], kind: str, scen_title: str) -> str:
    j = t.get("judge") or {}
    reply = t.get("spoken_text") or t.get("reply_text") or ""
    lat = t.get("latency_ms")
    facts = []
    if t.get("no_response"):
        facts.append("no reply")
    elif lat is not None:
        facts.append(f"replied after {lat / 1000:.1f} s")
    if t.get("expect") in ("en", "ar"):
        ok = t.get("spoken_lang_ok", t.get("lang_ok"))
        want = "English" if t["expect"] == "en" else "Arabic"
        facts.append(f"{want} expected: {'yes' if ok else 'no'}")
    if j.get("issue"):
        facts.append(f"judge: {j['issue']}")
    return f"""<div class="turn {kind}">
  <div class="tk">{'Best moment' if kind == 'best' else 'Weakest moment'} · {e(_short(scen_title))} · turn {t.get('idx', 0) + 1}
    ({e(LANG_NAMES.get(t.get('lang'), t.get('lang')))})</div>
  <div class="line"><span class="who">Caller</span><span dir="auto">{e(t.get('caller_text'))}</span></div>
  <div class="line"><span class="who">Agent</span><span dir="auto">{e(reply) or '<em>(silence)</em>'}</span></div>
  <div class="facts">{e(' · '.join(facts))}</div>
</div>"""


def _bars(rows: list[dict[str, Any]], key: str, unit: str, lo: float, hi: float, nd: int, better: str) -> str:
    """Horizontal bar chart, one series, values labelled (no legend needed)."""
    w_label, w_bar, h_row = 230, 430, 30
    h = h_row * len(rows) + 30
    out = [f'<svg class="chart" viewBox="0 0 {w_label + w_bar + 80} {h}" role="img">']
    for i, r in enumerate(rows):
        y = 10 + i * h_row
        v = r.get(key)
        out.append(f'<text x="{w_label - 10}" y="{y + 17}" text-anchor="end" class="lbl">{e(r["label"])}</text>')
        out.append(f'<rect x="{w_label}" y="{y + 4}" width="{w_bar}" height="18" class="track" rx="3"/>')
        if v is not None:
            frac = max(0.0, min(1.0, (v - lo) / (hi - lo)))
            out.append(f'<rect x="{w_label}" y="{y + 4}" width="{max(2, frac * w_bar):.1f}" height="18" class="bar" rx="3">'
                       f'<title>{e(r["label"])}: {v:.{nd}f}{unit}</title></rect>')
            out.append(f'<text x="{w_label + max(2, frac * w_bar) + 8:.1f}" y="{y + 18}" class="val">{v:.{nd}f}{unit}</text>')
        else:
            out.append(f'<text x="{w_label + 8}" y="{y + 18}" class="val">no data</text>')
    out.append(f'<text x="{w_label}" y="{h - 4}" class="axis">{e(better)}</text></svg>')
    return "".join(out)


def _heat(v: float | None) -> str:
    if v is None:
        return ""
    a = max(0.06, min(0.55, v / 100 * 0.55))
    return f' style="background: rgba(29, 78, 216, {a:.2f})"'


def build(stacks: list[str], since: str | None = None, title: str | None = None, subtitle: str | None = None,
          prepared_for: str | None = None, notes: Path | None = None, sample: bool = False,
          name: str | None = None) -> Path:
    name = name or f"{datetime.now():%Y%m%d}-full-report"
    out_dir = RESULTS_DIR / "fullreports" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    calls = _calls(stacks, sorted(f.stem for f in SCENARIOS_DIR.glob("*.yaml")), since)
    missing = [s for s in stacks if not calls.get(s)]
    if missing:
        raise SystemExit(f"no valid runs for: {', '.join(missing)}")
    scen_ids = sorted({c for by in calls.values() for c in by})
    # every number in the report comes from the same calls: each system's latest valid call of each scenario
    rows: dict[str, dict[str, Any]] = {}
    for s, by in calls.items():
        ms = [c["m"] for c in by.values()]
        turns = [t for m in ms for t in m["turns"]]
        lat = sorted(t["latency_ms"] for t in turns if t.get("latency_ms") is not None
                     and not t.get("interrupt") and not t.get("talk_over"))
        scored = [t for t in turns if t.get("expect") != "any"]
        lang_ok = [bool(t.get("spoken_lang_ok") if t.get("spoken_text") else t.get("lang_ok")) for t in scored]
        judge = [m["summary"]["judge_overall"] for m in ms if m["summary"].get("judge_overall") is not None]
        task = [m["summary"]["judge_task_success"] for m in ms if m["summary"].get("judge_task_success") is not None]
        spec = load_stack(s)
        row = {
            "id": s, "label": spec.get("display") or spec.get("name", s), "n": len(ms),
            "scenarios": sorted(by),
            "judges": sorted({(m.get("judge") or {}).get("model", "") for m in ms} - {""}),
            "score": round(statistics.mean(m["summary"]["caller_score"]["score"] for m in ms), 1),
            "p50": round(_pct(lat, 0.5) / 1000, 2) if lat else None,
            "p90": round(_pct(lat, 0.9) / 1000, 2) if lat else None,
            "language": round(100 * sum(lang_ok) / len(lang_ok)) if lang_ok else None,
            "quality": round(statistics.mean(judge), 1) if judge else None,
            "task": round(100 * statistics.mean(task)) if task else None,
            "reliability": round(statistics.mean(m["summary"]["caller_score"]["parts"].get("reliability", 0) for m in ms)),
        }
        for k in ("speed", "language", "quality", "task"):
            vals = [v for v in (m["summary"]["caller_score"]["parts"].get(k) for m in ms) if v is not None]
            row[f"part_{k}"] = round(statistics.mean(vals), 1) if vals else None
        rows[s] = row
    ranked = sorted((rows[s] for s in stacks), key=lambda r: -r["score"])
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
        try:
            spec = load_stack(r["id"])
        except FileNotFoundError:
            spec = {}
        r["notes"] = spec.get("notes", "")
        r["display_sub"] = spec.get("display_sub", "")

    any_call = next(iter(next(iter(calls.values())).values()))
    judges = sorted({j for r in ranked for j in r.get("judges", [])})
    local = all(c["meta"].get("local_only") for by in calls.values() for c in by.values())
    dates = sorted(c["m"].get("date") or "" for by in calls.values() for c in by.values())
    period = f"{dates[0][:10]} to {dates[-1][:10]}" if dates and dates[0][:10] != dates[-1][:10] else (dates[0][:10] if dates else "")
    title = title or "Gulf Arabic voice AI: evaluation report"
    subtitle = subtitle or f"{len(ranked)} systems · {len(scen_ids)} customer calls each · one Saudi caller"

    # ---- summary ---------------------------------------------------------------------------------------------
    fastest = min((r for r in ranked if r.get("p50") is not None), key=lambda r: r["p50"], default=None)
    best_lang = max((r for r in ranked if r.get("language") is not None), key=lambda r: r["language"], default=None)
    best_task = max((r for r in ranked if r.get("task") is not None), key=lambda r: r["task"], default=None)
    top = ranked[0]
    findings = [
        f"<strong>{e(top['label'])}</strong> has the highest caller score, {top['score']:.0f}/100"
        + (f", ahead of {e(ranked[1]['label'])} ({ranked[1]['score']:.0f})." if len(ranked) > 1 else "."),
    ]
    if fastest:
        findings.append(f"Fastest to answer: <strong>{e(fastest['label'])}</strong>, {fastest['p50']:.1f} s median "
                        f"(slowest 10% of replies: {fastest['p90']:.1f} s or more).")
    if best_lang:
        findings.append(f"Best at answering in the caller's language: <strong>{e(best_lang['label'])}</strong>, "
                        f"{best_lang['language']}% of turns.")
    if best_task:
        findings.append(f"Most complete calls: <strong>{e(best_task['label'])}</strong>, {best_task['task']}% task success.")
    slow = [r for r in ranked if r.get("p50") is not None and r["p50"] >= 3.0]
    if slow:
        findings.append(f"{len(slow)} of {len(ranked)} systems took 3 s or more to answer at the median, which callers "
                        "hear as a dead line; on speed they score zero.")

    rank_rows = "".join(
        f"<tr><td class='n'>{r['rank']}</td><td><strong>{e(r['label'])}</strong><div class='sub'>{e(r['display_sub'])}</div></td>"
        f"<td class='n big'>{r['score']:.0f}</td><td class='n'>{_num(r.get('p50'), ' s', 1)}</td>"
        f"<td class='n'>{_num(r.get('p90'), ' s', 1)}</td><td class='n'>{_num(r.get('language'), '%')}</td>"
        f"<td class='n'>{_num(r.get('quality'), '', 1)}</td><td class='n'>{_num(r.get('task'), '%')}</td>"
        f"<td class='n'>{_num(r.get('reliability'))}</td><td class='n'>{r['n']}</td></tr>"
        for r in ranked
    )

    # ---- per scenario --------------------------------------------------------------------------------------------
    scen_titles = {c: next((by[c]["scen"].get("title", c) for by in calls.values() if c in by), c) for c in scen_ids}
    heat_head = "".join(f"<th class='n'>{e(_short(scen_titles[c]))}</th>" for c in scen_ids)
    heat_rows = ""
    for r in ranked:
        cells = ""
        for c in scen_ids:
            call = calls.get(r["id"], {}).get(c)
            v = call["m"]["summary"]["caller_score"]["score"] if call else None
            cells += f"<td class='n heat'{_heat(v)}>{_num(v)}</td>"
        heat_rows += f"<tr><td>{e(r['label'])}</td>{cells}<td class='n'><strong>{r['score']:.0f}</strong></td></tr>"

    scen_sections = ""
    for c in scen_ids:
        sc = next(by[c]["scen"] for by in calls.values() if c in by)
        tags = sorted({LANG_NAMES.get(t.get("lang"), t.get("lang")) for t in sc.get("turns", [])})
        body = ""
        for r in sorted(ranked, key=lambda r: -(calls.get(r["id"], {}).get(c, {}).get("m", {}).get("summary", {})
                                               .get("caller_score", {}).get("score", -1))):
            call = calls.get(r["id"], {}).get(c)
            if not call:
                continue
            s = call["m"]["summary"]
            j = call["m"].get("judge") or {}
            body += (f"<tr><td><strong>{e(r['label'])}</strong></td><td class='n'>{s['caller_score']['score']:.0f}</td>"
                     f"<td class='n'>{_num((s.get('latency_p50_ms') or 0) / 1000 if s.get('latency_p50_ms') else None, ' s', 1)}</td>"
                     f"<td class='n'>{_num(100 * s['spoken_lang_accuracy'] if s.get('spoken_lang_accuracy') is not None else None, '%')}</td>"
                     f"<td class='n'>{_num(s.get('judge_overall'))}</td>"
                     f"<td class='n'>{_num(100 * s['judge_task_success'] if s.get('judge_task_success') is not None else None, '%')}</td>"
                     f"<td class='note'>{e(j.get('summary', ''))}</td></tr>")
        scen_sections += f"""<section class="scen">
<h3>{e(sc.get('title', c))}</h3>
<p class="muted">{e(_about(sc))} {len(sc.get('turns', []))} caller turns: {e(', '.join(tags))}.</p>
<table><thead><tr><th>System</th><th class='n'>Score</th><th class='n'>Median reply</th><th class='n'>Right language</th>
<th class='n'>Quality /10</th><th class='n'>Task</th><th>Judge's summary</th></tr></thead><tbody>{body}</tbody></table>
</section>"""

    # ---- per system profiles --------------------------------------------------------------------------------------
    profiles = ""
    for r in ranked:
        by = calls.get(r["id"], {})
        strengths, weaknesses, examples = [], [], []
        for c in scen_ids:
            call = by.get(c)
            if not call:
                continue
            j = call["m"].get("judge") or {}
            strengths += [f"{s}" for s in (j.get("strengths") or [])[:2]]
            weaknesses += [f"{s}" for s in (j.get("weaknesses") or [])[:2]]
            best, worst = _turn_examples(call["m"])
            if worst:
                examples.append(_turn_html(worst, "worst", scen_titles[c]))
            elif best and len(examples) < 1:
                examples.append(_turn_html(best, "best", scen_titles[c]))
        parts = "".join(
            f"<div class='part'><div class='pk'>{lbl} <span>{w}%</span></div><div class='pv'>{_num(r.get('part_' + k) if k != 'reliability' else r.get('reliability'))}</div></div>"
            for k, lbl, w in WEIGHTS
        )
        profiles += f"""<section class="profile">
<div class="ph"><div><div class="rank">#{r['rank']}</div><h3>{e(r['label'])}</h3><div class="sub">{e(r['display_sub'])}</div></div>
<div class="score">{r['score']:.0f}<span>/100</span></div></div>
<div class="parts">{parts}</div>
<div class="cols"><div><h4>What it did well</h4><ul>{''.join(f'<li>{e(s)}</li>' for s in strengths[:4]) or '<li>–</li>'}</ul></div>
<div><h4>Where it fell short</h4><ul>{''.join(f'<li>{e(s)}</li>' for s in weaknesses[:4]) or '<li>–</li>'}</ul></div></div>
{''.join(examples[:3])}
</section>"""

    # ---- appendix -------------------------------------------------------------------------------------------------
    app_rows = ""
    for r in ranked:
        for c in scen_ids:
            call = calls.get(r["id"], {}).get(c)
            if not call:
                continue
            s = call["m"]["summary"]
            rep = call["dir"] / "report.html"
            link = f"<a href='{e(rep.as_uri())}'>{e(call['dir'].name)}</a>" if rep.exists() else e(call["dir"].name)
            app_rows += (f"<tr><td>{e(r['label'])}</td><td>{e(scen_titles[c])}</td><td>{e((call['m'].get('date') or '')[:16])}</td>"
                         f"<td class='n'>{s['caller_score']['score']:.0f}</td><td class='n'>{s.get('turns', '')}</td>"
                         f"<td class='mono'>{link}</td></tr>")

    weights = "".join(f"<tr><td>{lbl}</td><td class='n'>{w}%</td><td>{e(how)}</td></tr>" for (k, lbl, w), how in zip(WEIGHTS, [
        "Median time from the end of the caller's speech to the agent's first audio, measured on the recording. "
        "Full marks at 0.7 s or faster, zero at 3 s or slower.",
        "Share of turns answered in the language the caller expects (Arabic or English), from what the caller heard.",
        "LLM judge, 0 to 10: understood the caller, correct against the business facts, natural for a Saudi caller.",
        "LLM judge: how completely the call got the customer what they called for.",
        "Minus 25 points for every unanswered turn, error, or turn the call never reached.",
    ]))
    scen_list = "".join(
        f"<tr><td><strong>{e(scen_titles[c])}</strong></td><td>{e(_about(next(by[c]['scen'] for by in calls.values() if c in by)))}</td></tr>"
        for c in scen_ids
    )
    where = ("All calls were placed and answered on one Apple M4 Pro laptop (24 GB), through a LiveKit server on the same "
             "machine, so response times exclude any internet round trip.") if local else (
             "Calls were placed from the test machine to each system over the internet (LiveKit WebRTC, SIP or phone, as "
             "labelled); response times include that network path.")
    notes_html = _md(Path(notes).read_text()) if notes else ""
    prepared = f"Prepared for {e(prepared_for)}" if prepared_for else ("Sample report" if sample else "")

    css = (Path(__file__).parent / "templates" / "fullreport.css").read_text()
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Sans+Arabic:wght@400;600&display=block" rel="stylesheet">
<style>{css}</style></head><body class="{'sample' if sample else ''}">
<section class="cover">
  <div class="kicker">Gulf Voice AI Benchmark</div>
  <h1>{e(title)}</h1>
  <p class="lede">{e(subtitle)}</p>
  <div class="meta"><div>{e(prepared)}</div><div>Calls placed {e(period)}</div><div>Issued {datetime.now():%d %B %Y}</div></div>
  <div class="cover-scores">{''.join(f"<div><span>{r['score']:.0f}</span>{e(r['label'])}</div>" for r in ranked[:4])}</div>
</section>

<section class="pagebreak">
<h2>Summary</h2>
{f'<div class="rec"><div class="rk">Recommendation</div>{notes_html}</div>' if notes_html else ''}
<ul class="findings">{''.join(f'<li>{f}</li>' for f in findings)}</ul>
<table class="ranking"><thead><tr><th class='n'>#</th><th>System</th><th class='n'>Caller score</th><th class='n'>Median reply</th>
<th class='n'>Slowest 10%</th><th class='n'>Right language</th><th class='n'>Quality /10</th><th class='n'>Task</th>
<th class='n'>Reliability</th><th class='n'>Calls</th></tr></thead><tbody>{rank_rows}</tbody></table>
<p class="muted small">Caller score /100 = speed 25% + language 20% + quality 25% + task 20% + reliability 10%, averaged over each
system's calls. It uses only what the caller experiences, so every system is scored the same way.</p>
</section>

<section class="pagebreak">
<h2>The scores</h2>
<h4>Caller score /100</h4>
{_bars(ranked, 'score', '', 0, 100, 0, 'Higher is better')}
<h4>Median time to answer (seconds)</h4>
{_bars(sorted(ranked, key=lambda r: r.get('p50') or 99), 'p50', ' s', 0, max(r.get('p90') or r.get('p50') or 0 for r in ranked) or 1, 1, 'Shorter is better · callers start to notice above about 1 s')}
<h4>Score on each call</h4>
<table class="heatmap"><thead><tr><th>System</th>{heat_head}<th class='n'>Average</th></tr></thead><tbody>{heat_rows}</tbody></table>
</section>

<section class="pagebreak">
<h2>How the systems were tested</h2>
<p>A simulated Saudi customer places the same scripted calls to every system. Its lines were recorded once in an Arabic
ElevenLabs voice and are replayed identically, so every system hears exactly the same audio. The caller switches between
Gulf Arabic, formal Arabic (MSA) and English, often mid-sentence. Each system gets the same business instructions (the
facts it may use and the rules it must follow); none sees the caller's lines in advance.</p>
<p>{e(where)}</p>
<h4>The calls</h4>
<table><tbody>{scen_list}</tbody></table>
<h4>The caller score</h4>
<table><thead><tr><th>Part</th><th class='n'>Weight</th><th>How it is measured</th></tr></thead><tbody>{weights}</tbody></table>
<h4>Judge and limits</h4>
<ul>
<li>Quality and task success are scored by an LLM judge ({e(', '.join(judges) or 'not recorded')}) that reads each transcript
against the business facts. A small local judge is lenient: treat quality scores as relative, not absolute.</li>
<li>One call per system per scenario: differences of a few points are within the noise of a single call.</li>
<li>Systems marked "on a Mac" are open models run quantised on a laptop. Their speed and quality are below what the
vendor's hosted service would give, and they are not presented as such.</li>
</ul>
</section>

<section class="pagebreak">
<h2>Call by call</h2>
{scen_sections}
</section>

<section class="pagebreak">
<h2>System profiles</h2>
{profiles}
</section>

<section class="pagebreak">
<h2>Appendix: every call</h2>
<p class="muted small">Each call has its own report with the recording, the full transcript and the judge's turn-by-turn notes.</p>
<table class="small"><thead><tr><th>System</th><th>Call</th><th>Placed</th><th class='n'>Score</th><th class='n'>Turns</th><th>Run</th></tr></thead>
<tbody>{app_rows}</tbody></table>
</section>
</body></html>"""
    out = out_dir / "report.html"
    out.write_text(page)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(out.as_uri(), wait_until="networkidle")
            pg.pdf(path=str(out_dir / "report.pdf"), format="A4", print_background=True,
                   margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
                   display_header_footer=True, header_template="<span></span>",
                   footer_template=f"<div style='font-size:8px;color:#8a94a6;width:100%;padding:0 14mm;display:flex;"
                                   f"justify-content:space-between'><span>{e(title)}{' · SAMPLE' if sample else ''}</span>"
                                   "<span><span class='pageNumber'></span> / <span class='totalPages'></span></span></div>")
            b.close()
    except Exception as ex:  # noqa: BLE001
        print(f"(PDF not written: {ex})")
    return out
