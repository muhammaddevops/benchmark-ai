"""The tester ("caller"): joins the LiveKit room as an ordinary participant, speaks the
scenario turns in English / Gulf Arabic / MSA / code-switched speech, waits for the
agent-under-test to answer, and records both sides on one sample-accurate timeline.

Two modes:
  scripted  every turn's text is fixed in the scenario and its audio is cached, so every
            stack hears byte-identical input (apples-to-apples STT / latency comparison)
  dynamic   an LLM plays the persona and writes each turn from the turn's intent and
            language directive, reacting to what the agent actually said
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import aiohttp
import numpy as np
from livekit import rtc

from . import eleven
from .config import SAMPLE_RATE as SR

logger = logging.getLogger("bench.caller")

FRAME = SR // 100  # 10 ms
VOICE_RMS = 350  # int16 RMS above which a frame counts as speech (TTS audio is clean)
SILENCE_TO_END = 1.5  # s of silence after agent speech that ends its turn
NO_RESPONSE_TIMEOUT = 12.0
GREETING_TIMEOUT = 10.0
THINK_GAP = 0.45  # s the caller "thinks" before speaking (fixed: reproducible)


# --------------------------------------------------------------------------- recorder


class Recorder:
    """Places caller and agent audio on a single timeline anchored at t0 (wall clock)."""

    def __init__(self) -> None:
        self.t0 = time.time()
        self.caller: list[tuple[int, np.ndarray]] = []
        self.sut: list[tuple[int, np.ndarray]] = []
        self._cursor: int | None = None

    def add_caller(self, pcm: np.ndarray, t_start: float) -> None:
        self.caller.append((int((t_start - self.t0) * SR), pcm))

    def add_sut_frame(self, pcm: np.ndarray, t_arrival: float) -> None:
        n = len(pcm)
        expected = int((t_arrival - self.t0) * SR) - n
        c = self._cursor
        # remote streams are continuous; only re-anchor after a real gap (>80 ms)
        if c is None or expected - c > int(0.08 * SR):
            c = max(expected, 0)
        self.sut.append((c, pcm))
        self._cursor = c + n

    def sut_audio(self, start_s: float, end_s: float) -> np.ndarray:
        a, b = int(start_s * SR), int(end_s * SR)
        out = np.zeros(max(0, b - a), dtype=np.int16)
        for pos, pcm in self.sut:
            if pos + len(pcm) <= a or pos >= b:
                continue
            s = max(pos, a)
            e = min(pos + len(pcm), b)
            out[s - a : e - a] = pcm[s - pos : e - pos]
        return out

    def render(self) -> np.ndarray:
        end = 0
        for pos, pcm in self.caller + self.sut:
            end = max(end, pos + len(pcm))
        out = np.zeros((end + SR // 2, 2), dtype=np.int16)
        for ch, segs in ((0, self.caller), (1, self.sut)):
            for pos, pcm in segs:
                out[pos : pos + len(pcm), ch] = pcm
        return out


# --------------------------------------------------------------------------- live VAD


class SpeechTracker:
    """Cheap live detector for agent speech (onsets / last voiced time)."""

    def __init__(self) -> None:
        self.last_voice: float = 0.0
        self.onsets: list[float] = []
        self._speaking = False
        self._event = asyncio.Event()

    def update(self, pcm: np.ndarray, t: float) -> None:
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) if len(pcm) else 0.0
        if rms > VOICE_RMS:
            if not self._speaking and t - self.last_voice > 0.25:
                self.onsets.append(t - len(pcm) / SR)
                self._event.set()
            self._speaking = True
            self.last_voice = t
        else:
            self._speaking = False

    def speaking_now(self, t: float) -> bool:
        return t - self.last_voice < 0.25

    async def wait_onset_after(self, t: float, timeout: float) -> float | None:
        deadline = time.time() + timeout
        while True:
            for o in self.onsets:
                if o >= t:
                    return o
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            self._event.clear()
            try:
                await asyncio.wait_for(self._event.wait(), timeout=min(remaining, 0.25))
            except asyncio.TimeoutError:
                pass

    async def wait_silence(self, silence: float, max_wait: float = 60.0) -> float:
        start = time.time()
        while time.time() - start < max_wait:
            now = time.time()
            if now - self.last_voice >= silence:
                return self.last_voice
            await asyncio.sleep(0.05)
        return self.last_voice


# --------------------------------------------------------------------------- turn log


@dataclass
class CallerTurn:
    idx: int
    lang: str
    text: str
    expect: str
    interrupt: bool = False
    t_start: float = 0.0  # seconds from t0
    t_end: float = 0.0
    sut_onset: float | None = None
    sut_end: float | None = None
    no_response: bool = False
    generated: bool = False
    tts_model: str = ""
    voice: str = ""


@dataclass
class CallResult:
    t0: float
    rtt_ms: list[float] = field(default_factory=list)
    greeting_onset: float | None = None
    greeting_end: float | None = None
    turns: list[CallerTurn] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def expected_reply_lang(turn: dict[str, Any]) -> str:
    if turn.get("expect"):
        return turn["expect"]
    lang = turn["lang"]
    if lang.startswith("ar"):
        return "ar"
    if lang == "en":
        return "en"
    return "any"


# --------------------------------------------------------------------------- dynamic persona


async def _generate_turn(
    http: aiohttp.ClientSession,
    scenario: dict[str, Any],
    turn: dict[str, Any],
    history: list[dict[str, str]],
) -> str:
    """LLM writes the caller's next line (dynamic mode)."""
    from .llmclient import backend, chat

    lang_rules = {
        "en": "Speak only English.",
        "ar-gulf": "Speak only Saudi/Gulf colloquial Arabic (Khaleeji) in Arabic script, e.g. ابغى، وش، زين، الحين، مره.",
        "ar-msa": "Speak only Modern Standard Arabic (Fusha) in Arabic script.",
        "mixed": "Code-switch naturally inside the sentence between Saudi Arabic and English, like a bilingual Saudi professional: Arabic script for Arabic words, Latin script for English words.",
    }
    persona = scenario.get("caller_persona", "")
    sys = (
        f"You are role-playing a phone caller. Persona: {persona}\n"
        f"Overall goal of the call: {scenario.get('caller_goal', '')}\n"
        "You talk to a customer-service voice agent. Write ONLY the words you say next, one or two short "
        "spoken sentences, no stage directions, no quotes, no emojis. Digits should be written as words."
    )
    convo = "\n".join(f"{h['who']}: {h['text']}" for h in history[-12:])
    user = (
        f"Conversation so far:\n{convo or '(call just connected)'}\n\n"
        f"Your next line must: {turn.get('intent') or turn.get('text')}\n"
        f"Language rule: {lang_rules.get(turn['lang'], lang_rules['mixed'])}"
    )
    b = backend("BENCH_TESTER_LLM", default_openai="gpt-5.4-mini", default_local="qwen3:14b")
    return (await chat(b, sys, user)).strip().strip('"')


# --------------------------------------------------------------------------- the call


class Caller:
    def __init__(self, room: rtc.Room, scenario: dict[str, Any], mode: str = "scripted", sut_kind: str = "pipeline") -> None:
        self.room = room
        self.sut_kind = sut_kind  # pipeline | realtime (our agent) | phone (SIP participant) | bridge (relay)
        self.scenario = scenario
        self.mode = mode
        self.rec = Recorder()
        self.vad = SpeechTracker()
        self.source = rtc.AudioSource(SR, 1, queue_size_ms=100)
        self.sut_identity: str | None = None
        self._sut_audio_ready = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        voice_cfg = scenario.get("caller_voice", {})
        self.voice = voice_cfg.get("voice_id", "yXEnnEln9armDCyhkXcA")
        self.tts_model = voice_cfg.get("model", "eleven_multilingual_v2")
        self.dynamic_tts_model = voice_cfg.get("dynamic_model", "eleven_flash_v2_5")
        self.voice_settings = voice_cfg.get("settings")
        room.on("track_subscribed", self._on_track)

    # -- media -----------------------------------------------------------------
    def _on_track(self, track: rtc.Track, pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        is_sut = (
            p.kind in (rtc.ParticipantKind.PARTICIPANT_KIND_AGENT, rtc.ParticipantKind.PARTICIPANT_KIND_SIP)
            or p.identity.startswith(("agent", "sip-", "bridge-"))
        )
        if not is_sut:
            return
        if self.sut_identity and p.identity != self.sut_identity:
            return
        self.sut_identity = p.identity
        self._tasks.append(asyncio.create_task(self._read(track)))

    async def _read(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream.from_track(track=track, sample_rate=SR, num_channels=1)
        self._sut_audio_ready.set()
        async for ev in stream:
            t = time.time()
            pcm = np.frombuffer(ev.frame.data, dtype=np.int16).copy()
            self.rec.add_sut_frame(pcm, t)
            self.vad.update(pcm, t)

    async def _play(self, pcm: np.ndarray) -> tuple[float, float]:
        t_start = time.time()
        self.rec.add_caller(pcm, t_start)
        for i in range(0, len(pcm), FRAME):
            chunk = pcm[i : i + FRAME]
            if len(chunk) < FRAME:
                chunk = np.pad(chunk, (0, FRAME - len(chunk)))
            frame = rtc.AudioFrame(
                data=chunk.astype(np.int16).tobytes(),
                sample_rate=SR,
                num_channels=1,
                samples_per_channel=FRAME,
            )
            await self.source.capture_frame(frame)
        await self.source.wait_for_playout()
        return t_start, t_start + len(pcm) / SR

    def rel(self, t: float | None) -> float | None:
        return None if t is None else round(t - self.rec.t0, 3)

    # -- flow ------------------------------------------------------------------
    async def _ping(self, n: int = 5) -> list[float]:
        out = []
        for _ in range(n):
            t = time.perf_counter()
            try:
                await self.room.local_participant.perform_rpc(
                    destination_identity=self.sut_identity or "", method="bench.ping", payload="", response_timeout=5
                )
                out.append(round((time.perf_counter() - t) * 1000, 1))
            except Exception as e:  # noqa: BLE001
                logger.warning("ping failed: %s", e)
            await asyncio.sleep(0.1)
        return out

    async def prerender(self, http: aiohttp.ClientSession) -> None:
        """Synthesize (and cache) every scripted turn before dialing."""
        if self.mode != "scripted":
            return
        await asyncio.gather(
            *[
                eleven.tts_pcm(t["text"], voice=self.voice, model=self.tts_model, settings=self.voice_settings, session=http)
                for t in self.scenario["turns"]
                if t.get("text")
            ]
        )

    async def run(self) -> CallResult:
        res = CallResult(t0=self.rec.t0)
        track = rtc.LocalAudioTrack.create_audio_track("caller-mic", self.source)
        await self.room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        try:
            await asyncio.wait_for(self._sut_audio_ready.wait(), timeout=45)
        except asyncio.TimeoutError:
            res.errors.append("agent never joined / published audio within 45s")
            return res
        # round-trip ping only works against our own agent; phone and bridge targets are black boxes
        res.rtt_ms = await self._ping() if self.sut_kind in ("pipeline", "realtime") else []

        # greeting
        onset = await self.vad.wait_onset_after(self.rec.t0, GREETING_TIMEOUT)
        if onset is not None:
            res.greeting_onset = self.rel(onset)
            end = await self.vad.wait_silence(SILENCE_TO_END)
            res.greeting_end = self.rel(end)

        history: list[dict[str, str]] = []
        turns = self.scenario["turns"]
        async with aiohttp.ClientSession() as http:
            for i, spec in enumerate(turns):
                generated = self.mode == "dynamic" or not spec.get("text")
                if generated:
                    # what did the agent just say? (Scribe on the recorded agent audio)
                    if res.turns and res.turns[-1].sut_onset is not None:
                        last = res.turns[-1]
                        seg = self.rec.sut_audio(last.sut_onset - 0.1, (last.sut_end or last.sut_onset + 8) + 0.2)
                        try:
                            heard = (await eleven.scribe(seg, session=http)).get("text", "")
                        except Exception as e:  # noqa: BLE001
                            heard = ""
                            res.errors.append(f"scribe: {e}")
                        history.append({"who": "Agent", "text": heard})
                    text = await _generate_turn(http, self.scenario, spec, history)
                    model = self.dynamic_tts_model
                else:
                    text = spec["text"]
                    model = self.tts_model
                history.append({"who": "Caller", "text": text})
                pcm = await eleven.tts_pcm(
                    text, voice=self.voice, model=model, settings=self.voice_settings, session=http
                )

                turn = CallerTurn(
                    idx=i,
                    lang=spec["lang"],
                    text=text,
                    expect=expected_reply_lang(spec),
                    interrupt=bool(spec.get("interrupt_after")),
                    generated=generated,
                    tts_model=model,
                    voice=self.voice,
                )
                if not turn.interrupt:
                    await asyncio.sleep(THINK_GAP)
                t_start, t_end = await self._play(pcm)
                turn.t_start, turn.t_end = self.rel(t_start), self.rel(t_end)

                # wait for the agent's answer
                nxt = turns[i + 1] if i + 1 < len(turns) else None
                onset = await self.vad.wait_onset_after(t_start + 0.3, NO_RESPONSE_TIMEOUT + (t_end - t_start))
                if onset is None:
                    turn.no_response = True
                else:
                    turn.sut_onset = self.rel(onset)
                    if nxt and nxt.get("interrupt_after"):
                        # barge-in test: next caller line starts while the agent is still talking
                        await asyncio.sleep(max(0.0, onset + float(nxt["interrupt_after"]) - time.time()))
                        turn.sut_end = None
                    else:
                        end = await self.vad.wait_silence(SILENCE_TO_END)
                        turn.sut_end = self.rel(end)
                res.turns.append(turn)
                logger.info("turn %d [%s] done (onset=%s)", i, turn.lang, turn.sut_onset)

        await asyncio.sleep(1.0)
        return res

    async def aclose(self) -> None:
        for t in self._tasks:
            t.cancel()
        await self.source.aclose()
