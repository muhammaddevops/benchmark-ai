"""HUMAIN Voice (Riyadh) as LiveKit STT/TTS, wrapping the official `humain-voice` SDK (pip install humain-voice).

There is no LiveKit plugin, so:
  STT: HUMAIN Fast Transcription per utterance (LiveKit's VAD cuts the turns), model bayan_cs_ar_en_v2 with
       language "codeswitch" by default. HUMAIN's realtime Socket.IO stream would be faster; this is the simple,
       robust first version (say so in the stack notes).
  TTS: Nebula, streamed (PCM16 24 kHz) as it arrives.

Env: HUMAIN_VOICE_API_KEY, HUMAIN_VOICE_API_URL (from HUMAIN's onboarding), optional HUMAIN_VOICE_API_PATH.
Untested against the live service until a key is added: run one call and check results/worker.log.
"""

from __future__ import annotations

import os

from livekit import rtc
from livekit.agents import APIConnectOptions, stt, tts, utils
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer


def _conn() -> dict[str, str | None]:
    url, key = os.environ.get("HUMAIN_VOICE_API_URL"), os.environ.get("HUMAIN_VOICE_API_KEY")
    if not url or not key:
        raise RuntimeError("set HUMAIN_VOICE_API_URL and HUMAIN_VOICE_API_KEY in .env")
    return {"api_url": url, "api_key": key, "api_path": os.environ.get("HUMAIN_VOICE_API_PATH") or None}


class HumainSTT(stt.STT):
    def __init__(self, model: str = "bayan_cs_ar_en_v2", language: str = "codeswitch") -> None:
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self._model, self._language, self._client = model, language, None

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "HUMAIN"

    async def _recognize_impl(self, buffer: AudioBuffer, *, language: NotGivenOr[str] = NOT_GIVEN,
                              conn_options: APIConnectOptions) -> stt.SpeechEvent:
        from humain_voice import stt as hstt

        if self._client is None:
            self._client = hstt.FastTranscriptionClient(**_conn())
        frame = rtc.combine_audio_frames(buffer)
        if frame.sample_rate != 16000:  # HUMAIN's examples use 16 kHz mono PCM16 WAV
            rs = rtc.AudioResampler(frame.sample_rate, 16000)
            frame = rtc.combine_audio_frames([*rs.push(frame), *rs.flush()])
        res = await self._client.transcribe(frame.to_wav_bytes(), self._language, self._model,
                                            timeout_seconds=conn_options.timeout + 20)
        text = (res.transcription if res else "") or ""
        lang = "ar" if any("؀" <= ch <= "ۿ" for ch in text) else "en"
        return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                               alternatives=[stt.SpeechData(text=text, language=lang)])

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()


class HumainTTS(tts.TTS):
    def __init__(self, voice: str | None = None, model: str = "nebula") -> None:
        from humain_voice.tts import get_sample_rate

        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=get_sample_rate(model),
                         num_channels=1)
        self._voice, self._model, self._client = voice, model, None

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "HUMAIN"

    async def client(self):  # noqa: ANN201
        from humain_voice.tts import TTSClient

        if self._client is None:
            self._client = TTSClient(**_conn())
            if not self._voice:  # first voice HUMAIN lists, unless the stack names one (see list_voices)
                voices = await self._client.list_voices(timeout_seconds=10)
                self._voice = voices[0]["id"] if voices else None
        return self._client

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> tts.ChunkedStream:
        return _HumainChunked(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()


class _HumainChunked(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        t: HumainTTS = self._tts  # type: ignore[assignment]
        client = await t.client()
        output_emitter.initialize(request_id=utils.shortuuid(), sample_rate=t.sample_rate, num_channels=1,
                                  mime_type="audio/pcm")
        async for chunk in client.synthesize_stream(self._input_text, t._voice, model=t._model,
                                                    timeout_seconds=self._conn_options.timeout + 30):
            if chunk.audio:
                output_emitter.push(chunk.audio)
        output_emitter.flush()


def stt_factory(**opts) -> HumainSTT:  # noqa: ANN003
    return HumainSTT(**opts)


def tts_factory(**opts) -> HumainTTS:  # noqa: ANN003
    return HumainTTS(**opts)
