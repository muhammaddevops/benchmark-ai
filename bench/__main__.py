"""CLI.

  python -m bench doctor                                 what is ready to run: keys, local models, SIP trunk, ElevenLabs quota
  python -m bench providers [--group domestic|global]    the Gulf provider registry and how ready each one is
  python -m bench list                                   stacks + scenarios
  python -m bench brief <scenario>                       the agent brief to paste into a hosted platform's dashboard
  python -m bench run  -s <stack|all|ready> -c <scenario|all>  [--mode scripted|dynamic] [--no-judge]
  python -m bench analyze <run_dir|latest> [--no-judge] [--rescribe]
  python -m bench rejudge [-s <stack>] [-c <scenario>]   re-score runs with the current judge (one judge per comparison)
  python -m bench video <run|latest> [--format landscape|square|vertical] [--turns 0-2] [--gap 0.8] [--label "Name"]
  python -m bench charts [-s <stack> ...] [-c <scenario> ...] [--since YYYY-MM-DD] [--name NAME]
  python -m bench montage -s <stack> -s <stack> ... -c <scenario> [--turns 0-1] [--format landscape]
  python -m bench report                                 rebuild results/index.html
  python -m bench serve [--port 8765]                    serve results/ over http
  python -m bench worker                                 run the agent-under-test worker in the foreground
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from .config import RESULTS_DIR, ROOT, RUNS_DIR


def _run_dir(arg: str) -> Path:
    d = Path(arg)
    if arg == "latest":
        return sorted(p for p in RUNS_DIR.iterdir() if (p / "metrics.json").exists())[-1]
    return d if d.exists() else RUNS_DIR / arg


def main() -> None:
    ap = argparse.ArgumentParser(prog="bench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    pv = sub.add_parser("providers")
    pv.add_argument("--group", choices=["domestic", "global"])
    sub.add_parser("list")
    nw = sub.add_parser("new", help="write a stack for a new provider (see bench/scaffold.py)")
    nw.add_argument("role", choices=["stt", "tts", "llm", "s2s", "agent"])
    nw.add_argument("name")
    for opt in ("--plugin", "--model", "--voice", "--language", "--base-url", "--key", "--display"):
        nw.add_argument(opt)
    nw.add_argument("--local", action="store_true", help="hold the local speech constant instead of the reference")
    nw.add_argument("--force", action="store_true")
    b = sub.add_parser("brief")
    b.add_argument("scenario")
    r = sub.add_parser("run")
    r.add_argument("-s", "--stack", action="append", required=True, help="stack id (repeatable), 'all' or 'ready'")
    r.add_argument("-c", "--scenario", action="append", required=True, help="scenario id (repeatable) or 'all'")
    r.add_argument("--mode", default="scripted", choices=["scripted", "dynamic"])
    r.add_argument("--no-judge", action="store_true")
    r.add_argument("--no-worker", action="store_true", help="don't spawn a worker (one is already running)")
    a = sub.add_parser("analyze")
    a.add_argument("run", help="run directory, run id, or 'latest'")
    a.add_argument("--no-judge", action="store_true")
    a.add_argument("--rescribe", action="store_true")
    rj = sub.add_parser("rejudge")
    rj.add_argument("-s", "--stack", action="append")
    rj.add_argument("-c", "--scenario", action="append")
    v = sub.add_parser("video")
    v.add_argument("run", help="run directory, run id, or 'latest'")
    v.add_argument("--format", default="landscape", choices=["landscape", "square", "vertical"])
    v.add_argument("--turns", help="only these caller turns, e.g. 0-2")
    v.add_argument("--gap", type=float, default=0.8, help="shorten the caller's own pauses to this many seconds")
    v.add_argument("--fps", type=int, default=25)
    v.add_argument("--label", help="provider name shown in the video")
    v.add_argument("--out")
    c = sub.add_parser("charts")
    c.add_argument("-s", "--stack", action="append")
    c.add_argument("-c", "--scenario", action="append")
    c.add_argument("--since", help="only runs from this date (YYYY-MM-DD)")
    c.add_argument("--name", default=None)
    c.add_argument("--kicker", default="")
    c.add_argument("--no-animate", action="store_true")
    mo = sub.add_parser("montage")
    mo.add_argument("-s", "--stack", action="append", required=True)
    mo.add_argument("-c", "--scenario", required=True)
    mo.add_argument("--turns", default="0-1")
    mo.add_argument("--format", default="landscape", choices=["landscape", "square", "vertical"])
    mo.add_argument("--name")
    mo.add_argument("--title")
    sub.add_parser("report")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    sub.add_parser("worker")
    sub.add_parser("speech", help="local Whisper + macOS voices, OpenAI-compatible, on :8770 (auto-started by run)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in logging.getLogger().handlers:  # the caller ignores the agent's transcription streams on purpose
        h.addFilter(lambda r: not str(r.msg).startswith(("ignoring byte stream", "ignoring text stream")))
    for noisy in ("livekit", "livekit.agents", "aiohttp", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.cmd == "doctor":
        from .doctor import doctor

        doctor()
    elif args.cmd == "providers":
        from .providers import print_providers

        print_providers(args.group)
    elif args.cmd == "new":
        from .scaffold import new_stack
        from .stacks import load_stack, requirements

        p = new_stack(args.role, args.name, plugin=args.plugin, model=args.model, voice=args.voice,
                      language=args.language, base_url=args.base_url, key=args.key, display=args.display,
                      local=args.local, force=args.force)
        miss = requirements(load_stack(str(p)))
        print(f"{p}\n  {'ready' if not miss else 'needs ' + ', '.join(miss)}")
    elif args.cmd == "list":
        from .run import all_scenarios, load_scenario
        from .stacks import describe, list_stacks, requirements

        print("STACKS")
        for st in list_stacks():
            miss = requirements(st) if not st.get("error") else []
            state = "ready" if not miss and not st.get("error") else ("needs " + ", ".join(miss) if miss else st.get("error"))
            print(f"  {st['id']:<44} {st.get('kind', ''):<9} {state}")
        print("SCENARIOS")
        for sc in all_scenarios():
            d = load_scenario(sc)
            print(f"  {sc:<44} {d.get('title')}  ({len(d['turns'])} turns)")
    elif args.cmd == "brief":
        from .run import load_scenario

        sc = load_scenario(args.scenario)
        print(f"# Agent brief: {sc.get('title', args.scenario)}\n")
        print("Paste this into the provider's agent configuration (system prompt / instructions). Keep its default voice")
        print("and language settings unless the test plan says otherwise, and note anything you had to change.\n")
        if sc.get("sut_greeting"):
            print(f"First message (greeting): {sc['sut_greeting']}\n")
        print(sc.get("sut_instructions", "(this scenario has no sut_instructions)"))
    elif args.cmd == "run":
        from .run import LocalSpeech, Worker, all_scenarios, run_matrix
        from .stacks import list_stacks, load_stack, requirements

        if "ready" in args.stack:
            stacks = [x["id"] for x in list_stacks() if not x.get("disabled") and not x.get("error") and not requirements(x)]
        elif "all" in args.stack:
            stacks = [x["id"] for x in list_stacks() if not x.get("disabled") and not x.get("error")]
        else:
            stacks = args.stack
        for st in stacks:
            miss = requirements(load_stack(st))
            if miss:
                raise SystemExit(f"{st} is not ready: missing {', '.join(miss)} (see `bench doctor`)")
        scens = all_scenarios() if "all" in args.scenario else args.scenario
        from .stacks import uses_localspeech

        need_worker = any(not load_stack(st).get("blackbox") for st in stacks)
        w, ls = Worker(), LocalSpeech()
        if sys.platform == "darwin":  # a sleeping Mac stalls calls for hours (seen 2026-11-10): stay awake while running
            subprocess.Popen(["caffeinate", "-ims", "-w", str(os.getpid())])
        try:
            if any(uses_localspeech(load_stack(st)) for st in stacks):
                ls.start()
            if need_worker and not args.no_worker:
                w.start()
            dirs = asyncio.run(run_matrix(stacks, scens, args.mode, not args.no_judge))
        finally:
            w.stop()
            ls.stop()
        _print_summary(dirs)
        print(f"\nLeaderboard: {RESULTS_DIR / 'index.html'}")
    elif args.cmd == "analyze":
        from .analyze import analyze_run

        d = _run_dir(args.run)
        asyncio.run(analyze_run(d, judge=not args.no_judge, rescribe=args.rescribe))
        _print_summary([d])
    elif args.cmd == "rejudge":
        from .analyze import analyze_run
        from .llmclient import backend

        print(f"judge: {backend('BENCH_JUDGE').label}")
        for f in sorted(RUNS_DIR.glob("*/metrics.json")):
            m = json.loads(f.read_text())
            if args.stack and m.get("stack_id") not in args.stack:
                continue
            if args.scenario and m.get("scenario_id") not in args.scenario:
                continue
            asyncio.run(analyze_run(f.parent, judge=True))
            print(f"  rejudged {f.parent.name}")
    elif args.cmd == "video":
        from .video import parse_turns, render

        d = _run_dir(args.run)
        out = render(d, args.format, turns=parse_turns(args.turns), gap=args.gap, fps=args.fps,
                     out=Path(args.out) if args.out else None, label=args.label)
        print(out)
    elif args.cmd == "charts":
        from datetime import datetime

        from .charts import collect, render_all

        rows = collect(args.stack, args.scenario, args.since)
        if not rows:
            raise SystemExit("no valid runs match")
        out = render_all(args.name or f"{datetime.now():%Y%m%d-%H%M}", rows, kicker=args.kicker, animate=not args.no_animate)
        print(out / "index.html")
    elif args.cmd == "montage":
        from .montage import build
        from .video import parse_turns

        print(build(args.stack, args.scenario, turns=parse_turns(args.turns), fmt=args.format, name=args.name, title=args.title))
    elif args.cmd == "report":
        from .report import write_index, write_run_report

        for d in RUNS_DIR.glob("*/metrics.json"):
            write_run_report(d.parent)
        write_index()
        print(RESULTS_DIR / "index.html")
    elif args.cmd == "serve":
        print(f"http://localhost:{args.port}/index.html")
        subprocess.run([sys.executable, "-m", "http.server", str(args.port), "-d", str(RESULTS_DIR)])
    elif args.cmd == "speech":
        from .localspeech import serve

        serve()
    elif args.cmd == "worker":
        subprocess.run([sys.executable, "-m", "bench.sut_agent", "start"], cwd=ROOT)


def _print_summary(dirs: list[Path]) -> None:
    for d in dirs:
        try:
            m = json.loads((d / "metrics.json").read_text())
        except Exception:  # noqa: BLE001
            print(f"  {d.name}: no metrics")
            continue
        if m.get("failed"):
            print(f"  {d.name}: FAILED {m.get('error')}")
            continue
        s = m["summary"]
        cs = (s.get("caller_score") or {}).get("score")
        print(
            f"  {m['stack_id']:<30} {m['scenario_id']:<26} caller score {cs}"
            f" | p50 {s['latency_p50_ms']} ms | right language {s.get('spoken_lang_accuracy')}"
            f" | stt {s['stt_error']} | judge {s.get('judge_overall')} | task {s.get('judge_task_success')}"
            f"\n    {d / 'report.html'}"
        )


if __name__ == "__main__":
    main()
