"""Small factories for plugins whose options are objects, not plain keyword arguments (`plugin: custom`)."""

from __future__ import annotations


def soniox_stt(model: str = "stt-rt-v5", language_hints: list[str] | None = None, **opts):  # noqa: ANN201
    from livekit.plugins import soniox

    return soniox.STT(params=soniox.STTOptions(model=model, language_hints=language_hints or ["ar", "en"], **opts))
