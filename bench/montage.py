"""The LinkedIn comparison video: title card -> the same moment of the same scripted call for each provider ->
animated benchmark charts -> method card -> optional end card.

  python -m bench montage -s <stack> -s <stack> ... -c <scenario> [--turns 0-1] [--format landscape|square|vertical]
                          [--since 2026-11-25] [--end-card card.yaml]

--since keeps only runs from that date on (clips and charts), so a re-run batch isn't mixed with older calls.
--end-card is a YAML/JSON file with the card fields (kicker, title, ar, lede, items, cta, foot, seconds): an offer or a
contact card. Keep it outside the repo (e.g. results/), since it is your own text.

Each provider's clip comes from its latest valid run of the scenario (render a call with `bench video` first if you
want to check it). Clips are cut at the same turns, so viewers hear every agent answer the same caller lines.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .charts import collect, render_all, valid
from .config import RESULTS_DIR, RUNS_DIR
from .stacks import load_stack
from .video import SIZES, render

CARD = Path(__file__).parent / "templates" / "card.html"
CHART_FMT = {"landscape": "landscape", "square": "square", "vertical": "vertical"}


def latest_run(stack_id: str, scenario_id: str, since: str | None = None) -> Path | None:
    best = None
    for f in sorted(RUNS_DIR.glob(f"*_{stack_id}_{scenario_id}_*/metrics.json")):
        m = json.loads(f.read_text())
        if since and (m.get("date") or "") < since:
            continue
        if m.get("stack_id") == stack_id and m.get("scenario_id") == scenario_id and valid(m):
            best = f.parent
    return best


def card(spec: dict[str, Any], fmt: str, seconds: float, out: Path) -> Path:
    from playwright.sync_api import sync_playwright

    w, h = SIZES[fmt]
    png = out.with_suffix(".png")
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": w, "height": h})
        page.goto(CARD.as_uri())
        page.evaluate("([c, f]) => setup(c, f)", [spec, fmt])
        page.wait_for_timeout(200)
        page.screenshot(path=str(png))
        b.close()
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "25", "-t", f"{seconds}", "-i", str(png),
         "-f", "lavfi", "-t", f"{seconds}", "-i", "anullsrc=r=48000:cl=stereo",
         "-vf", "fade=t=in:st=0:d=0.4,fade=t=out:st=" + f"{seconds - 0.4}:d=0.4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", "-c:a", "aac", "-ar", "48000", "-shortest", str(out)],
        check=True,
    )
    return out


def concat(parts: list[Path], out: Path, fmt: str) -> Path:
    w, h = SIZES[fmt]
    inputs: list[str] = []
    chains = []
    for i, p in enumerate(parts):
        inputs += ["-i", str(p)]
        chains.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x0b1220,"
            f"setsar=1,fps=25,format=yuv420p[v{i}];[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]"
        )
    joined = "".join(f"[v{i}][a{i}]" for i in range(len(parts)))
    graph = ";".join(chains) + f";{joined}concat=n={len(parts)}:v=1:a=1[v][a]"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", str(out)],
        check=True,
    )
    return out


def build(stacks: list[str], scenario: str, turns: tuple[int, int] | None = (0, 1), fmt: str = "landscape",
          name: str | None = None, title: str | None = None, since: str | None = None,
          end_card: Path | None = None) -> Path:
    name = name or f"{datetime.now():%Y%m%d}-{scenario}-{fmt}"
    out_dir = RESULTS_DIR / "videos" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    runs = {s: latest_run(s, scenario, since) for s in stacks}
    missing = [s for s, r in runs.items() if r is None]
    if missing:
        raise SystemExit(f"no valid run of {scenario} for: {', '.join(missing)} (run `bench run -s <stack> -c {scenario}`)")
    labels = {s: (load_stack(s).get("display") or load_stack(s).get("name", s)) for s in stacks}
    scen = json.loads((next(iter(runs.values())) / "scenario.json").read_text())
    local = all(json.loads((r / "meta.json").read_text()).get("local_only") for r in runs.values())
    where = "on one Mac" if local else "over the live network"

    parts = [card({
        "kicker": "Gulf Voice AI Benchmark",
        "title": title or f"{len(stacks)} voice agents. One Saudi caller. The same call.",
        "ar": "نفس المكالمة، نفس العميل",
        "lede": f"{scen.get('title', scenario)}: English, Gulf Arabic and code-switching. "
                "Every response time is real; only the caller's own pauses are trimmed.",
        "items": [labels[s] for s in stacks],
        "foot": f"Scripted mock calls {where} · scored from the recordings",
    }, fmt, 4.0, out_dir / "00_intro.mp4")]

    for i, s in enumerate(stacks, 1):
        clip = out_dir / f"{i:02d}_{s}.mp4"
        render(runs[s], fmt, turns=turns, end_card=3.0, out=clip, label=labels[s])
        parts.append(clip)

    rows = collect(stacks=stacks, since=since)
    chart_dir = render_all(name, rows, kicker=scen.get("title", ""), formats=(CHART_FMT[fmt],), animate=False)
    from playwright.sync_api import sync_playwright

    from .charts import _animate, _data

    anim = out_dir / "90_charts.mp4"
    with sync_playwright() as p:
        b = p.chromium.launch()
        _animate(b, _data(rows, scen.get("title", "")), anim, CHART_FMT[fmt])
        b.close()
    parts.append(anim)
    parts.append(card({
        "kicker": "How we tested",
        "title": "Same script, same voice, same Mac." if local else "Same script, same voice, same network.",
        "lede": "A simulated Saudi caller (ElevenLabs voices) places a live call to each agent. Response time is measured "
                "from the recording: caller stops, agent starts. Language, answer quality and task success come from "
                "the transcripts and an LLM judge.",
        "items": ["English", "Gulf Arabic", "MSA", "Code-switching"],
        "foot": f"Charts and per-call reports: {chart_dir.name}",
    }, fmt, 5.0, out_dir / "99_method.mp4"))
    if end_card:
        import yaml

        spec = yaml.safe_load(Path(end_card).read_text())
        parts.append(card(spec, fmt, float(spec.pop("seconds", 5.0)), out_dir / "99z_end.mp4"))
    final = out_dir / f"{name}.mp4"
    return concat(parts, final, fmt)
