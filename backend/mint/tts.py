import asyncio
import logging

import edge_tts

from .config import config

log = logging.getLogger("mint.tts")


class EdgeTts:
    """Online Microsoft Edge voices (free, no key). Returns one mp3 per sentence."""

    ATTEMPTS = 3  # the service intermittently answers late or with no audio
    # Launch another attempt in parallel if the first is this slow. Measured on 16 sentences:
    # 1.6 s -> mean 2.0 s / p90 4.3 s;  0.7 s -> mean 1.1 s / p90 1.2 s.
    HEDGE_S = config.tts_hedge_s

    def __init__(self, voice: str | None = None, rate: str | None = None, pitch: str | None = None):
        self.voice = voice or config.tts_voice
        self.rate = rate or config.tts_rate
        self.pitch = pitch or config.tts_pitch

    async def synth(self, text: str) -> bytes:
        """Hedged request: slow or failed attempts are raced by fresh ones, first success wins."""
        tasks: set[asyncio.Task[bytes]] = set()
        try:
            for _ in range(self.ATTEMPTS):
                tasks.add(asyncio.create_task(self._once(text)))
                result = await self._first_success(tasks, self.HEDGE_S)
                if result is not None:
                    return result
            while tasks:
                result = await self._first_success(tasks, None)
                if result is not None:
                    return result
            raise RuntimeError("TTS failed after retries")
        finally:
            for t in tasks:
                t.cancel()

    @staticmethod
    async def _first_success(tasks: set, timeout: float | None) -> bytes | None:
        done, _ = await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        for d in done:
            tasks.discard(d)
            if d.exception() is None:
                return d.result()
            log.info("tts attempt failed (%s)", type(d.exception()).__name__)
        return None

    async def _once(self, text: str) -> bytes:
        comm = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch)
        buf = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        if not buf:
            raise RuntimeError("TTS returned no audio")
        return bytes(buf)
