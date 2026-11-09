# Bridges: hosted agents reached over a web or WebSocket API

A bridge is an async function that joins the LiveKit call room as participant `bridge-sut`, plays the provider's
audio into the room and sends the caller's audio to the provider. The caller and the recorder treat it exactly like
our own agent, so latency, videos and charts work unchanged (scores are black-box: no STT/TTS internals).

```python
async def run(url: str, token: str, scenario: dict, run_dir: Path, **options) -> None:
    room = rtc.Room(); await room.connect(url, token)
    # publish an rtc.AudioSource track with the provider's speech; read the caller's track with rtc.AudioStream
    # and stream it to the provider; return (or get cancelled) when the call ends
```

Stack file:

```yaml
kind: bridge
bridge: {factory: "bench.bridges.<module>:run", options: {...}, requires: [PROVIDER_API_KEY]}
```

Prefer the phone path (`stacks/phone-template.yaml`) when the provider gives you a number: it needs no code.
