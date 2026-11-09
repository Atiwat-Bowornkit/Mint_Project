import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from .chunker import Sentence, SentenceChunker
from .config import config
from .endpointing import Discard, End, Endpointer, Start
from .llm import Conversation, ToolCall
from .tools import TOOLS, Result, Tool, classify_confirmation, looks_like_command

log = logging.getLogger("mint.session")

FRAME_BYTES = 1024  # 512 samples int16
CONFIRM_TTL_S = 60
# While we wait for yes/no the answer is almost certainly one of these; on short clips this lifted
# correct recognition of "ไม่เอา" etc. (measured on synthetic speech: 4/8 -> 6/8).
CONFIRM_HINT = "คำตอบ: ได้ ใช่ ตกลง โอเค ไม่เอา ไม่ ยกเลิก"
_stt_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")


class VadLike(Protocol):
    def prob(self, frame: bytes) -> float: ...
    def reset(self) -> None: ...


class TranscriberLike(Protocol):
    def transcribe(self, pcm: bytes, hint: str | None = None) -> str: ...


class TtsLike(Protocol):
    async def synth(self, text: str) -> bytes: ...


class LlmLike(Protocol):
    def stream(self, messages: list[dict]) -> AsyncIterator[str]: ...
    async def route(self, user_text: str) -> ToolCall | None: ...


Send = Callable[[dict], Awaitable[None]]
SendAudio = Callable[[bytes], Awaitable[None]]


@dataclass
class Pending:
    """A tool call waiting for the user's yes/no."""

    id: int
    tool: Tool
    args: dict
    expires: float


class Session:
    """One websocket connection: PCM in -> events out."""

    def __init__(
        self,
        vad: VadLike,
        transcriber: TranscriberLike,
        llm: LlmLike,
        tts: TtsLike,
        send: Send,
        send_audio: SendAudio,
    ):
        self.vad = vad
        self.transcriber = transcriber
        self.llm = llm
        self.tts = tts
        self.send = send
        self.send_audio = send_audio
        self.endpointer = Endpointer(end_silence_ms=config.end_silence_ms)
        self.conv = Conversation()
        self._rest = bytearray()
        self._stt_tasks: set[asyncio.Task] = set()
        self._respond_task: asyncio.Task | None = None
        # tool use
        self.pending: Pending | None = None
        self._confirm_id = 0
        self._bg: set[asyncio.Task] = set()  # confirmed actions and timer announcements
        self._timers: dict[int, asyncio.Task] = {}
        self._timer_id = 0
        # a `reply` message and its audio frame must stay adjacent on the wire
        self._send_lock = asyncio.Lock()

    def set_playing(self, playing: bool) -> None:
        """Client reports whether the assistant's voice is audible (enables stricter barge-in)."""
        self.endpointer.barge_in = playing

    async def on_audio(self, data: bytes) -> None:
        self._rest += data
        while len(self._rest) >= FRAME_BYTES:
            frame = bytes(self._rest[:FRAME_BYTES])
            del self._rest[:FRAME_BYTES]
            for ev in self.endpointer.feed(frame, self.vad.prob(frame)):
                await self._handle(ev)

    async def _handle(self, ev) -> None:
        if isinstance(ev, Start):
            self._cancel_response()  # user started talking: stop answering
            await self.send({"type": "interrupt"})  # ...and stop whatever is still playing
            await self.send({"type": "state", "value": "listening"})
        elif isinstance(ev, Discard):
            await self.send({"type": "state", "value": "idle"})
        elif isinstance(ev, End):
            await self.send({"type": "state", "value": "thinking"})
            task = asyncio.create_task(self._transcribe(ev.pcm, time.perf_counter()))
            self._stt_tasks.add(task)
            task.add_done_callback(self._stt_tasks.discard)

    async def _transcribe(self, pcm: bytes, t_end: float) -> None:
        t0 = time.perf_counter()
        waiting = self.pending is not None and time.monotonic() <= self.pending.expires
        try:
            text = await asyncio.get_running_loop().run_in_executor(
                _stt_pool, self.transcriber.transcribe, pcm, CONFIRM_HINT if waiting else None
            )
        except Exception:
            log.exception("transcription failed")
            await self.send({"type": "error", "message": "stt failed"})
            await self.send({"type": "state", "value": "idle"})
            return
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("stt %d ms for %d ms audio: %r", ms, len(pcm) // 32, text)
        if not text:
            await self.send({"type": "state", "value": "idle"})
            return
        await self.send({"type": "transcript", "text": text, "stt_ms": ms})
        self.say_to_llm(text, t_end, ms)

    def say_to_llm(self, text: str, t_end: float | None = None, stt_ms: int | None = None) -> None:
        """Entry point for recognised speech and for typed messages."""
        if self.pending:
            p = self.pending
            verdict = None if time.monotonic() > p.expires else classify_confirmation(text)
            if verdict is not None:  # the user is answering our question
                self._spawn(self._resolve(p, verdict))
                return
            self._drop_pending()  # they said something else: the old request is stale
        self._cancel_response()
        turn = {"t_end": t_end or time.perf_counter(), "stt_ms": stt_ms, "llm_ms": None}
        self._respond_task = asyncio.create_task(self._respond(text, turn))

    # ---- responding -------------------------------------------------------------------------

    async def _respond(self, text: str, turn: dict | None = None) -> None:
        turn = turn if turn is not None else {"t_end": time.perf_counter(), "stt_ms": None, "llm_ms": None}
        self.conv.add_user(text)
        chunker = SentenceChunker()
        raw = ""
        t0 = time.perf_counter()
        queue: asyncio.Queue[Sentence | None] = asyncio.Queue()
        llm_logged = False
        speaker = asyncio.create_task(self._speak(queue, t0, turn))

        try:
            call = await self._route(text)
            if call:
                turn["llm_ms"] = int((time.perf_counter() - t0) * 1000)
                for s in await self._use_tool(call):
                    raw += f"[{s.emotion}] {s.text} "
                    queue.put_nowait(s)
            else:
                async for tok in self.llm.stream(self.conv.messages()):
                    raw += tok
                    for s in chunker.feed(tok):
                        if queue.empty() and not llm_logged:
                            llm_logged = True
                            turn["llm_ms"] = int((time.perf_counter() - t0) * 1000)
                            log.info("llm first sentence after %d ms", (time.perf_counter() - t0) * 1000)
                        queue.put_nowait(s)
                for s in chunker.flush():
                    queue.put_nowait(s)
            queue.put_nowait(None)
            await speaker
        except asyncio.CancelledError:
            raise  # the new utterance drives the next state
        except Exception:
            log.exception("response failed")
            await self.send({"type": "error", "message": "llm unavailable"})
        finally:
            speaker.cancel()
            if raw:
                self.conv.add_assistant(raw)  # keep what was said, even if cut off
        await self.send({"type": "state", "value": "idle"})

    async def _route(self, text: str) -> ToolCall | None:
        if not looks_like_command(text):
            return None  # plain chat: skip the extra LLM call
        try:
            return await self.llm.route(text)
        except Exception:
            log.warning("tool routing failed, answering as plain chat", exc_info=True)
            return None

    async def _speak(self, queue: "asyncio.Queue[Sentence | None]", t0: float, turn: dict) -> None:
        """Synthesises sentences concurrently (TTS latency varies a lot) but sends them in order."""
        ready: asyncio.Queue[tuple[Sentence, asyncio.Task, float] | None] = asyncio.Queue()

        async def synth(s: Sentence) -> bytes | None:
            return await self._synth(s.text)

        async def feed() -> None:
            while (s := await queue.get()) is not None:
                ready.put_nowait((s, asyncio.create_task(synth(s)), time.perf_counter()))
            ready.put_nowait(None)

        feeder = asyncio.create_task(feed())
        pending: list[asyncio.Task] = []
        first = True
        try:
            while (item := await ready.get()) is not None:
                s, task, t_start = item
                pending.append(task)
                audio = await task
                if first:
                    first = False
                    await self.send(
                        {
                            "type": "metrics",
                            "endpoint_ms": config.end_silence_ms if turn["stt_ms"] is not None else 0,
                            "stt_ms": turn["stt_ms"],
                            "llm_ms": turn["llm_ms"],
                            "tts_ms": int((time.perf_counter() - t_start) * 1000),
                            "server_ms": int((time.perf_counter() - turn["t_end"]) * 1000),
                        }
                    )
                    log.info("first sentence ready after %d ms", (time.perf_counter() - t0) * 1000)
                    await self.send({"type": "state", "value": "speaking"})
                await self._send_reply(s.text, s.emotion, audio)
        finally:
            feeder.cancel()
            for t in pending:
                t.cancel()
            while not ready.empty():  # synths started but not yet picked up
                item = ready.get_nowait()
                if item:
                    item[1].cancel()

    async def _synth(self, text: str) -> bytes | None:
        t = time.perf_counter()
        try:
            audio = await self.tts.synth(text)
            log.info("tts %d ms for %r", (time.perf_counter() - t) * 1000, text)
            return audio
        except Exception:
            log.warning("tts failed for %r; sending text only", text, exc_info=True)
            return None

    async def _send_reply(self, text: str, emotion: str, audio: bytes | None) -> None:
        async with self._send_lock:
            await self.send({"type": "reply", "text": text, "emotion": emotion, "audio": audio is not None})
            if audio:
                await self.send_audio(audio)  # always directly follows its `reply` message

    async def announce(self, text: str, emotion: str = "neutral") -> None:
        """Say something unprompted (timers, results of confirmed actions)."""
        await self._send_reply(text, emotion, await self._synth(text))

    # ---- tools ------------------------------------------------------------------------------

    async def _use_tool(self, call: ToolCall) -> list[Sentence]:
        tool = TOOLS.get(call.name)
        if tool is None:
            log.warning("model asked for unknown tool %r", call.name)
            return [Sentence("ขอโทษค่ะ มิ้นท์ทำสิ่งนั้นไม่ได้", "worried")]
        if tool.confirm:
            self._confirm_id += 1
            question = tool.describe(call.args)
            self.pending = Pending(self._confirm_id, tool, call.args, time.monotonic() + CONFIRM_TTL_S)
            log.info("tool %s %s waiting for confirmation", tool.name, call.args)
            await self.send({"type": "confirm", "id": self.pending.id, "text": question})
            return [Sentence(question, "neutral")]
        res = await self._execute(tool, call.args)
        return [Sentence(res.text, res.emotion)]

    async def _execute(self, tool: Tool, args: dict) -> Result:
        log.info("running tool %s %s", tool.name, args)
        try:
            return await tool.run(args, self)
        except Exception:
            log.exception("tool %s failed", tool.name)
            return Result("ขอโทษค่ะ ทำไม่สำเร็จ", "sad")

    async def _resolve(self, p: Pending, ok: bool) -> None:
        if self.pending is not p:
            return
        self._drop_pending()
        if not ok:
            await self.announce("ยกเลิกแล้วค่ะ")
            return
        res = await self._execute(p.tool, p.args)
        await self.announce(res.text, res.emotion)

    def confirm_reply(self, confirm_id: int | None, ok: bool) -> None:
        """The user pressed a button on screen."""
        p = self.pending
        if p and (confirm_id is None or confirm_id == p.id):
            self._spawn(self._resolve(p, ok and time.monotonic() <= p.expires))

    def _drop_pending(self) -> None:
        if self.pending:
            cid, self.pending = self.pending.id, None
            self._spawn(self.send({"type": "confirm_done", "id": cid}))

    def _spawn(self, coro: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    # timers (tools call these through the Host protocol)

    def start_timer(self, seconds: float, label: str) -> None:
        self._timer_id += 1
        tid = self._timer_id
        self._timers[tid] = asyncio.create_task(self._timer(tid, seconds, label))

    async def _timer(self, tid: int, seconds: float, label: str) -> None:
        await asyncio.sleep(seconds)
        self._timers.pop(tid, None)
        await self.announce(f"ครบเวลา{' ' + label if label else ''}แล้วค่ะ", "surprised")

    def cancel_timers(self) -> int:
        n = len(self._timers)
        for t in self._timers.values():
            t.cancel()
        self._timers.clear()
        return n

    # ---- lifecycle --------------------------------------------------------------------------

    def _cancel_response(self) -> None:
        if self._respond_task and not self._respond_task.done():
            self._respond_task.cancel()
        self._respond_task = None

    def close(self) -> None:
        self._cancel_response()
        self.cancel_timers()
        for t in (*self._stt_tasks, *self._bg):
            t.cancel()
