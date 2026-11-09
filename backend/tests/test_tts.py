import asyncio
import time

import pytest

from mint.tts import EdgeTts


def tts_with(behaviours):
    """behaviours: one coroutine function per attempt."""
    t = EdgeTts()
    t.HEDGE_S = 0.05
    calls = iter(behaviours)

    async def once(text):
        return await next(calls)()

    t._once = once  # type: ignore[method-assign]
    return t


async def test_slow_first_attempt_is_raced_by_second():
    async def hang():
        await asyncio.sleep(10)

    async def fast():
        return b"ok"

    t0 = time.perf_counter()
    assert await tts_with([hang, fast]).synth("x") == b"ok"
    assert time.perf_counter() - t0 < 1


async def test_failed_attempt_is_replaced():
    async def boom():
        raise RuntimeError("no audio")

    async def ok():
        return b"ok"

    assert await tts_with([boom, ok]).synth("x") == b"ok"


async def test_all_attempts_failing_raises():
    async def boom():
        raise RuntimeError("no audio")

    with pytest.raises(RuntimeError):
        await tts_with([boom, boom, boom]).synth("x")
