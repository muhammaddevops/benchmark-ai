"""Agent-under-test worker.

One generic LiveKit agent whose whole voice stack (STT/LLM/TTS or realtime model,
turn detection, endpointing) comes from the dispatch metadata, so every provider
is benchmarked through identical code. Run it with:

    .venv/bin/python -m bench.sut_agent start      # `python -m bench run` starts it for you

Everything the session observes is appended to <run_dir>/sut_events.jsonl and the
full chat history (with LiveKit's per-turn latency metrics) is written to
<run_dir>/sut_history.json on shutdown.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from . import config  # noqa: F401  (loads .env, maps ElevenLabs key)
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
    room_io,
)
from livekit.plugins import silero

from .config import CALLER_IDENTITY, SUT_AGENT_NAME
from .stacks import build_session_kwargs

logger = logging.getLogger("bench.sut")


class EventLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = path.open("a", encoding="utf-8")

    def write(self, kind: str, **data: Any) -> None:
        rec = {"t": time.time(), "kind": kind, **data}
        self._f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()


def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)
    return obj


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(setup_fnc=prewarm)


@server.rtc_session(agent_name=SUT_AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata or "{}")
    run_dir = Path(meta["run_dir"])
    stack: dict[str, Any] = meta["stack"]
    scenario: dict[str, Any] = meta["scenario"]
    log = EventLog(run_dir / "sut_events.jsonl")
    log.write("job_start", stack_id=stack["id"], room=ctx.room.name)

    try:
        kwargs = build_session_kwargs(stack, vad=ctx.proc.userdata.get("vad"))
    except Exception as e:  # surface config errors in the report instead of hanging
        log.write("error", where="build_stack", error=repr(e))
        raise
    session: AgentSession = AgentSession(**kwargs)

    @session.on("user_input_transcribed")
    def _on_transcript(ev) -> None:  # noqa: ANN001
        if ev.is_final:
            log.write("user_transcript", text=ev.transcript, language=str(ev.language or ""))

    @session.on("conversation_item_added")
    def _on_item(ev) -> None:  # noqa: ANN001
        item = ev.item
        if getattr(item, "type", "") != "message":
            return
        log.write(
            "message",
            role=item.role,
            text=item.text_content or "",
            interrupted=item.interrupted,
            created_at=item.created_at,
            metrics=dict(item.metrics or {}),
        )

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:  # noqa: ANN001
        log.write("agent_state", old=ev.old_state, new=ev.new_state)

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:  # noqa: ANN001
        log.write("user_state", old=ev.old_state, new=ev.new_state)

    @session.on("agent_false_interruption")
    def _on_false_int(ev) -> None:  # noqa: ANN001
        log.write("false_interruption")

    @session.on("error")
    def _on_error(ev) -> None:  # noqa: ANN001
        log.write("error", where=str(getattr(ev, "source", "")), error=repr(getattr(ev, "error", ev)))

    @session.on("session_usage_updated")
    def _on_usage(ev) -> None:  # noqa: ANN001
        log.write("usage", usage=_dump(getattr(ev, "usage", None)))

    async def _on_shutdown() -> None:
        try:
            items = []
            for it in session.history.items:
                if getattr(it, "type", "") != "message":
                    continue
                items.append(
                    {
                        "role": it.role,
                        "text": it.text_content or "",
                        "interrupted": it.interrupted,
                        "created_at": it.created_at,
                        "metrics": dict(it.metrics or {}),
                    }
                )
            (run_dir / "sut_history.json").write_text(
                json.dumps(items, ensure_ascii=False, indent=1, default=str)
            )
        finally:
            log.write("job_end")
            log.close()

    ctx.add_shutdown_callback(_on_shutdown)

    await ctx.connect()
    await session.start(
        agent=Agent(instructions=scenario["sut_instructions"]),
        room=ctx.room,
        room_options=room_io.RoomOptions(participant_identity=CALLER_IDENTITY),
    )
    log.write("session_started")

    # Lets the caller measure the network round trip of the media path.
    @ctx.room.local_participant.register_rpc_method("bench.ping")
    async def _ping(data: rtc.RpcInvocationData) -> str:
        return json.dumps({"t": time.time()})

    greeting = scenario.get("sut_greeting")
    if greeting:
        if stack["kind"] == "realtime" and not stack.get("tts"):
            await session.generate_reply(
                instructions=f"Greet the caller by saying exactly this and nothing else: {greeting}"
            )
        else:
            await session.say(greeting)
    log.write("greeting_done")
    # The job lives on until the caller deletes the room.


if __name__ == "__main__":
    cli.run_app(server)
