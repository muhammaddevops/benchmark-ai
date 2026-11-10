"""Run benchmarks: start the agent-under-test worker, place the call, analyze, report."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
import uuid
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
import yaml
from livekit import api, rtc

from .caller import Caller
from .config import CALLER_IDENTITY, RESULTS_DIR, ROOT, RUNS_DIR, SAMPLE_RATE, SCENARIOS_DIR, SUT_AGENT_NAME
from .stacks import describe, load_stack

logger = logging.getLogger("bench.run")
WORKER_LOG = RESULTS_DIR / "worker.log"


def load_scenario(name: str) -> dict[str, Any]:
    p = Path(name)
    if p.suffix not in (".yaml", ".yml"):
        p = SCENARIOS_DIR / f"{name}.yaml"
    sc = yaml.safe_load(p.read_text())
    sc.setdefault("id", p.stem)
    return sc


def all_scenarios() -> list[str]:
    return [p.stem for p in sorted(SCENARIOS_DIR.glob("*.yaml"))]


# --------------------------------------------------------------------------- worker


class Worker:
    """Starts `python -m bench.sut_agent start` unless one is already registered."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        log = WORKER_LOG.open("w")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "bench.sut_agent", "start"],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            start_new_session=True,
        )
        deadline = time.time() + 90
        while time.time() < deadline:
            text = WORKER_LOG.read_text(errors="ignore")
            if "registered worker" in text:
                logger.info("agent-under-test worker registered")
                return
            if self.proc.poll() is not None:
                raise RuntimeError(f"worker exited early, see {WORKER_LOG}:\n{text[-2000:]}")
            time.sleep(0.5)
        raise RuntimeError(f"worker did not register within 90s, see {WORKER_LOG}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGINT)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)


class LocalSpeech:
    """Starts bench/localspeech.py (local Whisper + macOS voices) when a stack uses `plugin: localspeech`."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None

    @staticmethod
    def up() -> bool:
        import urllib.request

        from .localspeech import URL

        try:
            with urllib.request.urlopen(URL.replace("/v1", "/health"), timeout=2):
                return True
        except Exception:  # noqa: BLE001
            return False

    def start(self) -> None:
        if self.up():
            return
        log = (RESULTS_DIR / "localspeech.log").open("w")
        self.proc = subprocess.Popen([sys.executable, "-m", "bench.localspeech"], cwd=ROOT, stdout=log,
                                     stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1"},
                                     start_new_session=True)
        deadline = time.time() + 180
        while time.time() < deadline:
            if self.up():
                logger.info("local speech server ready")
                return
            if self.proc.poll() is not None:
                raise RuntimeError(f"local speech server exited, see {RESULTS_DIR / 'localspeech.log'}")
            time.sleep(1)
        raise RuntimeError("local speech server did not start within 180s")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)


async def _prewarm(stack: dict[str, Any], http) -> None:  # noqa: ANN001
    """Load local models before dialling, so turn 1 isn't charged with a cold model load (hosted APIs are warm)."""
    llm = stack.get("llm") or {}
    if llm.get("plugin") != "ollama":
        return
    base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").replace("/v1", "")
    try:
        t = time.time()
        async with http.post(f"{base}/api/generate", json={"model": llm["model"], "prompt": "", "keep_alive": "30m"},
                             timeout=aiohttp.ClientTimeout(total=300)) as r:
            await r.read()
        logger.info("warmed %s in %.1fs", llm["model"], time.time() - t)
    except Exception as e:  # noqa: BLE001
        logger.warning("could not prewarm %s: %s", llm["model"], e)


# --------------------------------------------------------------------------- one call


def _write_wav(path: Path, stereo) -> None:  # noqa: ANN001
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(stereo.tobytes())


async def run_one(stack_id: str, scenario_id: str, mode: str = "scripted", judge: bool = True) -> Path:
    stack = load_stack(stack_id)
    scenario = load_scenario(scenario_id)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{stamp}_{stack['id']}_{scenario['id']}_{mode}_{uuid.uuid4().hex[:4]}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    room_name = f"bench-{uuid.uuid4().hex[:10]}"
    meta: dict[str, Any] = {
        "run_id": run_id,
        "room": room_name,
        "date": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "stack": stack,
        "stack_labels": describe(stack),
        "scenario_id": scenario["id"],
        "scenario_title": scenario.get("title", scenario["id"]),
        "blackbox": stack.get("blackbox", False),
        "path": {"phone": "phone (SIP/PSTN)", "bridge": "provider web API"}.get(stack["kind"], "LiveKit WebRTC"),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    (run_dir / "scenario.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=1))
    print(f"\n▶ {stack['name']}  ×  {scenario.get('title', scenario['id'])}  [{mode}]  → {run_dir.name}")

    url = os.environ["LIVEKIT_URL"]
    lk = api.LiveKitAPI()
    room = rtc.Room()
    caller: Caller | None = None
    result = None
    bridge_task: asyncio.Task | None = None
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=room_name, empty_timeout=60, max_participants=4))
        token = (
            api.AccessToken()
            .with_identity(CALLER_IDENTITY)
            .with_name("Benchmark caller")
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )
        caller = Caller(room, scenario, mode=mode, sut_kind=stack["kind"])
        import aiohttp

        async with aiohttp.ClientSession() as http:
            await caller.prerender(http)
            await _prewarm(stack, http)
        await room.connect(url, token, rtc.RoomOptions(auto_subscribe=True))
        if stack["kind"] == "phone":
            await _dial(lk, stack, room_name, meta)
        elif stack["kind"] == "bridge":
            bridge_task = asyncio.create_task(_bridge(stack, scenario, room_name, run_dir))
        else:
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=SUT_AGENT_NAME,
                    room=room_name,
                    metadata=json.dumps(
                        {"run_dir": str(run_dir), "stack": stack, "scenario": scenario}, ensure_ascii=False
                    ),
                )
            )
        result = await asyncio.wait_for(caller.run(), timeout=scenario.get("max_duration_s", 420))
    except TimeoutError:
        # the call ran past the scenario's limit (usually very long replies): score the turns that completed
        result = getattr(caller, "result", None) if caller else None
        done, total = len(result.turns) if result else 0, len(scenario.get("turns", []))
        logger.warning("call hit the %ss limit after %d of %d turns", scenario.get("max_duration_s", 420), done, total)
        meta["incomplete"] = {"reason": "call duration limit", "turns_done": done, "turns_total": total}
    except Exception as e:  # noqa: BLE001
        logger.exception("call failed")
        meta["call_error"] = repr(e)
    finally:
        if bridge_task:
            bridge_task.cancel()
        if caller:
            stereo = caller.rec.render()
            _write_wav(run_dir / "call.wav", stereo)
            await caller.aclose()
        await room.disconnect()
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
        except Exception:  # noqa: BLE001
            pass
        await lk.aclose()

    if result is not None:
        (run_dir / "caller_turns.json").write_text(json.dumps(result.to_json(), ensure_ascii=False, indent=1))
    (run_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))

    # the worker writes its chat history on shutdown (only our own agent has one)
    for _ in range(0 if stack.get("blackbox") else 40):
        if (run_dir / "sut_history.json").exists():
            break
        await asyncio.sleep(0.5)

    from .analyze import analyze_run

    await analyze_run(run_dir, judge=judge)
    return run_dir


async def _dial(lk: api.LiveKitAPI, stack: dict[str, Any], room_name: str, meta: dict[str, Any]) -> None:
    """Phone a hosted agent into the room through the LiveKit SIP outbound trunk (see scripts/setup_sip.py)."""
    ph = stack.get("phone") or {}
    number = os.environ.get(ph["number_env"], "") if ph.get("number_env") else ph.get("number", "")
    trunk = os.environ.get(ph.get("trunk_env", "BENCH_SIP_TRUNK_ID"), "")
    if not number or not trunk:
        raise RuntimeError(f"{stack['id']}: phone number and SIP trunk id are needed ({ph})")
    meta["dialled"] = number[:-4] + "****"  # don't keep full numbers in results
    await lk.sip.create_sip_participant(
        api.CreateSIPParticipantRequest(
            sip_trunk_id=trunk,
            sip_call_to=number,
            room_name=room_name,
            participant_identity="sip-sut",
            participant_name=stack.get("name", "agent"),
            play_dialtone=False,
            krisp_enabled=False,  # hear exactly what the provider sends
            wait_until_answered=True,
        ),
        timeout=60,
    )


async def _bridge(stack: dict[str, Any], scenario: dict[str, Any], room_name: str, run_dir: Path) -> None:
    """Run a relay participant (``bridge-sut``) between the room and a provider's web/WebSocket agent API."""
    import importlib

    b = stack["bridge"]
    mod, _, fn = b["factory"].partition(":")
    token = (
        api.AccessToken()
        .with_identity("bridge-sut")
        .with_name(stack.get("name", "agent"))
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )
    await getattr(importlib.import_module(mod), fn)(
        url=os.environ["LIVEKIT_URL"], token=token, scenario=scenario, run_dir=run_dir, **b.get("options", {})
    )


async def run_matrix(stacks: list[str], scenarios: list[str], mode: str, judge: bool) -> list[Path]:
    out = []
    for st in stacks:
        for sc in scenarios:
            try:
                out.append(await run_one(st, sc, mode=mode, judge=judge))
            except Exception:  # noqa: BLE001
                logger.exception("run %s × %s failed", st, sc)
    return out
