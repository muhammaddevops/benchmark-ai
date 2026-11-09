"""Static HTML: one report per run (results/runs/<id>/report.html) and a leaderboard
(results/index.html) aggregating every run. Open directly in a browser or serve with
`python -m bench serve`."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .config import RESULTS_DIR, RUNS_DIR

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e4e4df;--good:#1f8a4c;--bad:#c2410c;--mid:#a16207;--acc:#2f5bea}
@media (prefers-color-scheme:dark){:root{--bg:#121211;--card:#1c1c1a;--ink:#ecece8;--mute:#9a9a93;--line:#2c2c29;--good:#4ade80;--bad:#fb923c;--mid:#facc15;--acc:#7c9cff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,"Noto Naskh Arabic",sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 10px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}
.sub{color:var(--mute)}a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.tile .k{font-size:12px;color:var(--mute)}.tile .v{font-size:22px;font-weight:650;margin-top:2px;font-variant-numeric:tabular-nums}
.tile .h{font-size:11px;color:var(--mute)}
.score{font-size:44px;font-weight:700;line-height:1}
.head{display:flex;gap:24px;align-items:flex-end;flex-wrap:wrap;margin-bottom:8px}
.chips span{display:inline-block;border:1px solid var(--line);background:var(--card);border-radius:999px;padding:2px 9px;margin:2px 4px 2px 0;font-size:12px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}
th{font-size:12px;color:var(--mute);font-weight:600;background:var(--card);position:sticky;top:0;cursor:pointer;white-space:nowrap}
td.n{font-variant-numeric:tabular-nums;white-space:nowrap}
.ar{direction:rtl;unicode-bidi:plaintext;text-align:start}
.txt{unicode-bidi:plaintext;max-width:330px}
.ok{color:var(--good);font-weight:600}.no{color:var(--bad);font-weight:600}.mid{color:var(--mid);font-weight:600}
.tag{font-size:11px;border-radius:4px;padding:1px 6px;background:var(--line);white-space:nowrap}
.small{font-size:12px;color:var(--mute)}
button.play{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:6px;padding:2px 8px;cursor:pointer}
audio{width:100%;margin:6px 0 2px}
.scroll{overflow-x:auto}
ul{margin:6px 0 0 18px;padding:0}
.bar{height:6px;border-radius:3px;background:var(--line);overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:var(--acc)}
"""

SORT_JS = """
document.querySelectorAll('table.sortable th').forEach((th,i)=>th.addEventListener('click',()=>{
 const t=th.closest('table'),b=t.tBodies[0],rows=[...b.rows],asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
 const v=r=>{const c=r.cells[i];const d=c.dataset.v;return d!==undefined?parseFloat(d):c.innerText.toLowerCase()};
 rows.sort((a,b)=>{const x=v(a),y=v(b);if(typeof x==='number'&&typeof y==='number'){if(isNaN(x))return 1;if(isNaN(y))return -1;return asc?x-y:y-x}return asc?(''+x).localeCompare(''+y):(''+y).localeCompare(''+x)});
 rows.forEach(r=>b.appendChild(r))}));
const f=document.getElementById('scen');if(f){f.addEventListener('change',()=>{document.querySelectorAll('tr[data-scen]').forEach(r=>{r.style.display=(f.value===''||r.dataset.scen===f.value)?'':'none'})})}
"""


def e(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def fmt_ms(v: Any) -> str:
    return "–" if v is None else f"{int(v):,} ms"


def fmt_pct(v: Any) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def cls_good(v: float | None, good: float, bad: float, higher_better: bool = True) -> str:
    if v is None:
        return ""
    if not higher_better:
        v, good, bad = -v, -good, -bad
    return "ok" if v >= good else ("no" if v <= bad else "mid")


def _tile(k: str, v: str, hint: str = "", c: str = "") -> str:
    return f'<div class="tile"><div class="k">{e(k)}</div><div class="v {c}">{v}</div><div class="h">{e(hint)}</div></div>'


def write_run_report(run_dir: Path) -> None:
    m = json.loads((run_dir / "metrics.json").read_text())
    meta = json.loads((run_dir / "meta.json").read_text())
    stack = meta.get("stack", {})
    labels = meta.get("stack_labels", {})
    title = f"{stack.get('name', '?')} × {meta.get('scenario_title', '')}"
    if m.get("failed"):
        body = f'<h1>{e(title)}</h1><p class="no">Run failed: {e(m.get("error"))}</p><p><a href="../../index.html">← leaderboard</a></p>'
        (run_dir / "report.html").write_text(_page(title, body))
        return
    s = m["summary"]
    comp = s.get("composite", {})
    ip = s.get("internal_p50_ms", {})
    j = m.get("judge", {})

    tiles = [
        _tile("Response latency p50", fmt_ms(s.get("latency_p50_ms")), f"p90 {fmt_ms(s.get('latency_p90_ms'))} · caller-perceived", cls_good(s.get("latency_p50_ms"), 1000, 2000, False)),
        _tile("Language accuracy", fmt_pct(s.get("lang_accuracy")), "reply in expected language", cls_good(s.get("lang_accuracy"), 0.9, 0.7)),
        _tile("On switch turns", fmt_pct(s.get("switch_accuracy")), "turns where the caller changed language", cls_good(s.get("switch_accuracy"), 0.9, 0.7)),
        _tile("STT error", fmt_pct(s.get("stt_error")), "WER (en) / CER (ar, mixed)", cls_good(s.get("stt_error"), 0.1, 0.3, False)),
        _tile("TTS intelligibility err", fmt_pct(s.get("tts_cer")), "CER of spoken vs intended reply", cls_good(s.get("tts_cer"), 0.1, 0.3, False)),
        _tile("Quality (judge)", "–" if s.get("judge_overall") is None else f"{s['judge_overall']}/10", "understanding, accuracy, naturalness", cls_good(s.get("judge_overall"), 7.5, 5)),
        _tile("Dialect fit", fmt_pct(s.get("dialect_accuracy")), "Gulf ↔ MSA register matched", cls_good(s.get("dialect_accuracy"), 0.85, 0.6)),
        _tile("Task success", fmt_pct(s.get("judge_task_success")), "caller goals met", cls_good(s.get("judge_task_success"), 0.85, 0.5)),
        _tile("Barge-in stop", fmt_ms(s.get("barge_in_stop_ms")), f"yield rate {fmt_pct(s.get('barge_in_yield_rate'))}", cls_good(s.get("barge_in_stop_ms"), 700, 1500, False)),
        _tile("No response / talk-over", f"{s.get('no_response', 0)} / {s.get('talk_over', 0)}", f"{s.get('errors', 0)} agent errors", "ok" if not (s.get("no_response") or s.get("talk_over") or s.get("errors")) else "no"),
    ]
    breakdown = [
        _tile("Network RTT", fmt_ms(s.get("network_rtt_ms")), "caller ↔ agent media path"),
        _tile("End-of-turn delay", fmt_ms(ip.get("end_of_turn_delay")), "speech end → turn committed"),
        _tile("STT final delay", fmt_ms(ip.get("transcription_delay")), "speech end → final transcript"),
        _tile("LLM TTFT", fmt_ms(ip.get("llm_ttft")), "first token"),
        _tile("TTS TTFB", fmt_ms(ip.get("tts_ttfb")), "first audio byte"),
        _tile("Agent e2e (internal)", fmt_ms(ip.get("agent_e2e")), "user stop → agent start, self-reported"),
    ]
    by_lang = "".join(
        f"<span>{e(g)}: {fmt_ms(v)} · err {fmt_pct(s.get('stt_error_by_lang', {}).get(g))}</span>"
        for g, v in s.get("latency_by_lang", {}).items()
    )

    trs = []
    for r in m["turns"]:
        jt = r.get("judge", {})
        lang_c = "ok" if r["lang_ok"] else "no"
        lat = r["latency_ms"]
        lat_txt = "no reply" if r["no_response"] else (f"{lat:,} ms" + (" ⚠ talk-over" if r["talk_over"] else ""))
        if r["interrupt"]:
            lat_txt = f"barge-in: stopped in {fmt_ms(r.get('barge_in_stop_ms'))}"
        trs.append(
            f"""<tr>
<td class="n">{r['idx']}<br><button class="play" onclick="seek({r['t_start']})">▶</button></td>
<td><span class="tag">{e(r['lang'])}</span>{' <span class="tag">switch</span>' if r['is_switch'] else ''}{' <span class="tag">gen</span>' if r.get('generated') else ''}</td>
<td class="txt">{e(r['caller_text'])}</td>
<td class="txt">{e(r['heard'])}<div class="small">err {fmt_pct(r['stt_error'])}</div></td>
<td class="txt">{e(r['reply_text'])}<div class="small"><span class="{lang_c}">{e(r['reply_lang'] or 'none')} {'✓' if r['lang_ok'] else '✗'}</span> expected {e(r['expect'])}{' · ' + e(jt.get('dialect')) if jt.get('dialect') not in (None, 'n/a') else ''}</div></td>
<td class="txt">{e(r.get('spoken_text'))}<div class="small">TTS err {fmt_pct(r.get('tts_cer'))}</div></td>
<td class="n">{lat_txt}<div class="small">EOT {fmt_ms(r['internal'].get('end_of_turn_delay'))} · LLM {fmt_ms(r['internal'].get('llm_ttft'))} · TTS {fmt_ms(r['internal'].get('tts_ttfb'))}</div></td>
<td class="txt small">{('U' + str(jt.get('understood')) + ' C' + str(jt.get('correct')) + ' N' + str(jt.get('naturalness')) + ' · ') if jt else ''}{e(jt.get('issue'))}</td>
</tr>"""
        )
    chips = "".join(f"<span>{e(k)}: {e(v)}</span>" for k, v in labels.items())
    parts = "".join(f"<span>{e(k)} {v}</span>" for k, v in comp.get("parts", {}).items())
    judge_html = ""
    if j:
        judge_html = (
            f"<h2>Judge ({e(j.get('model'))})</h2><div class='tile'><p>{e(j.get('summary'))}</p>"
            f"<div class='grid' style='grid-template-columns:1fr 1fr'><div><b>Strengths</b><ul>{''.join('<li>' + e(x) + '</li>' for x in j.get('strengths', []))}</ul></div>"
            f"<div><b>Weaknesses</b><ul>{''.join('<li>' + e(x) + '</li>' for x in j.get('weaknesses', []))}</ul></div></div></div>"
        )
    errs = m.get("sut_errors", []) + m.get("caller_errors", [])
    err_html = f"<h2>Errors</h2><div class='tile small'>{'<br>'.join(e(x) for x in errs)}</div>" if errs else ""
    greet = s.get("greeting_spoken")
    body = f"""
<p><a href="../../index.html">← leaderboard</a></p>
<div class="head"><div><div class="score">{e(comp.get('score'))}</div><div class="small">composite / 100</div></div>
<div><h1>{e(title)}</h1><div class="sub">{e(meta.get('date'))} · {e(meta.get('mode'))} mode · run {e(meta.get('run_id'))}</div>
<div class="chips">{chips}</div><div class="chips small">{parts}</div></div></div>
<h2>Scorecard</h2><div class="grid">{''.join(tiles)}</div>
<h2>Latency breakdown (p50)</h2><div class="grid">{''.join(breakdown)}</div>
<div class="chips small" style="margin-top:8px">{by_lang}</div>
<h2>Call recording</h2><div class="tile"><audio id="au" controls preload="metadata" src="call.wav"></audio>
<div class="small">Stereo: left = caller, right = agent under test.{(' Greeting heard: ' + e(greet)) if greet else ''}</div></div>
<h2>Turns</h2><div class="scroll"><table><thead><tr><th>#</th><th>Lang</th><th>Caller said (truth)</th><th>Agent heard (STT)</th><th>Agent reply (LLM)</th><th>Caller heard (TTS → Scribe)</th><th>Latency</th><th>Judge</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table></div>
{judge_html}{err_html}
<script>function seek(t){{const a=document.getElementById('au');a.currentTime=Math.max(0,t-0.2);a.play()}}</script>
"""
    (run_dir / "report.html").write_text(_page(title, body))


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head><body><div class="wrap">{body}</div><script>{SORT_JS}</script></body></html>"""


def collect_runs() -> list[dict[str, Any]]:
    out = []
    for d in sorted(RUNS_DIR.glob("*/metrics.json")):
        try:
            m = json.loads(d.read_text())
            meta = json.loads((d.parent / "meta.json").read_text())
        except Exception:  # noqa: BLE001
            continue
        m["_dir"] = d.parent.name
        m["_meta"] = meta
        out.append(m)
    return out


def write_index() -> None:
    runs = collect_runs()
    scen = sorted({r.get("scenario_id") or r["_meta"].get("scenario_id", "") for r in runs})
    rows = []
    for r in sorted(runs, key=lambda x: x["_dir"], reverse=True):
        meta = r["_meta"]
        st = meta.get("stack", {})
        sc = meta.get("scenario_id", "")
        if r.get("failed"):
            rows.append(
                f'<tr data-scen="{e(sc)}"><td data-v="-1">–</td><td><a href="runs/{e(r["_dir"])}/report.html">{e(st.get("name"))}</a></td><td>{e(sc)}</td>'
                f'<td colspan="8" class="no">failed: {e(str(r.get("error"))[:120])}</td><td>{e(meta.get("date"))}</td></tr>'
            )
            continue
        s = r["summary"]
        comp = s.get("composite", {}).get("score")

        def num(v: Any) -> str:
            return "NaN" if v is None else str(v)

        rows.append(
            f"""<tr data-scen="{e(sc)}">
<td data-v="{num(comp)}" class="n"><b>{e(comp)}</b></td>
<td><a href="runs/{e(r['_dir'])}/report.html">{e(st.get('name'))}</a><div class="small">{e(' · '.join(f'{k}: {v}' for k, v in meta.get('stack_labels', {}).items()))}</div></td>
<td>{e(sc)}<div class="small">{e(meta.get('mode'))}</div></td>
<td data-v="{num(s.get('latency_p50_ms'))}" class="n {cls_good(s.get('latency_p50_ms'), 1000, 2000, False)}">{fmt_ms(s.get('latency_p50_ms'))}</td>
<td data-v="{num(s.get('lang_accuracy'))}" class="n {cls_good(s.get('lang_accuracy'), 0.9, 0.7)}">{fmt_pct(s.get('lang_accuracy'))}</td>
<td data-v="{num(s.get('switch_accuracy'))}" class="n {cls_good(s.get('switch_accuracy'), 0.9, 0.7)}">{fmt_pct(s.get('switch_accuracy'))}</td>
<td data-v="{num(s.get('stt_error'))}" class="n {cls_good(s.get('stt_error'), 0.1, 0.3, False)}">{fmt_pct(s.get('stt_error'))}</td>
<td data-v="{num(s.get('tts_cer'))}" class="n {cls_good(s.get('tts_cer'), 0.1, 0.3, False)}">{fmt_pct(s.get('tts_cer'))}</td>
<td data-v="{num(s.get('judge_overall'))}" class="n {cls_good(s.get('judge_overall'), 7.5, 5)}">{e(s.get('judge_overall'))}</td>
<td data-v="{num(s.get('dialect_accuracy'))}" class="n {cls_good(s.get('dialect_accuracy'), 0.85, 0.6)}">{fmt_pct(s.get('dialect_accuracy'))}</td>
<td data-v="{num(s.get('barge_in_stop_ms'))}" class="n">{fmt_ms(s.get('barge_in_stop_ms'))}</td>
<td class="n small">{e(meta.get('date', '').replace('T', ' '))}</td></tr>"""
        )
    opts = "".join(f'<option value="{e(x)}">{e(x)}</option>' for x in scen)
    body = f"""
<h1>Voice AI stack benchmark — English · Gulf Arabic · MSA</h1>
<div class="sub">{len(runs)} runs. Live LiveKit calls between a bilingual caller and each stack. Click a column to sort, a stack to open its call report.</div>
<p><label class="small">Scenario <select id="scen"><option value="">all</option>{opts}</select></label></p>
<div class="scroll"><table class="sortable"><thead><tr>
<th>Score</th><th>Stack</th><th>Scenario</th><th>Latency p50</th><th>Lang acc.</th><th>Switch acc.</th><th>STT err</th><th>TTS err</th><th>Quality</th><th>Dialect</th><th>Barge-in</th><th>Date</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>How to read this</h2><div class="tile small">
<b>Score</b> = 20% latency (p50 ≤700 ms → 100, ≥3 s → 0) + 25% language accuracy + 15% STT accuracy + 10% TTS intelligibility + 25% judge quality + 5% reliability.
<b>Latency</b> is what the caller hears: end of caller speech → first agent audio, including the network path (agent runs on the benchmark machine).
<b>STT err</b> = WER on English turns, CER on Arabic and mixed turns, against the exact text the caller spoke. <b>TTS err</b> = CER between the agent's reply text and an independent Scribe transcription of its audio.
<b>Dialect</b> = share of Arabic replies whose register (Gulf vs MSA) fit the caller, per the LLM judge.</div>
"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "index.html").write_text(_page("Voice AI benchmark leaderboard", body))
