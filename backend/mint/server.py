import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .session import LlmLike, Session, TranscriberLike, TtsLike, VadLike

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _default_vad() -> VadLike:
    from .vad import Vad

    return Vad()


def _default_transcriber() -> TranscriberLike:
    from .stt import Transcriber

    return Transcriber()


def _default_llm() -> LlmLike:
    from .llm import Llm

    return Llm()


def _default_tts() -> TtsLike:
    from .tts import EdgeTts

    return EdgeTts()


@dataclass
class Deps:
    """Swappable in tests so no real model is needed."""

    vad_factory: Callable[[], VadLike] = _default_vad
    transcriber: TranscriberLike | None = None
    llm: LlmLike | None = None
    tts: TtsLike | None = None
    warmup: bool = True


deps = Deps()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if deps.transcriber is None:
        deps.transcriber = _default_transcriber()
        if deps.warmup:
            import asyncio

            await asyncio.get_running_loop().run_in_executor(None, deps.transcriber.warmup)  # type: ignore[attr-defined]
    if deps.llm is None:
        deps.llm = _default_llm()
        if deps.warmup:
            try:
                await deps.llm.warmup()  # type: ignore[attr-defined]
            except Exception:
                logging.getLogger("mint").warning("Ollama not reachable; replies will fail until it is")
    if deps.tts is None:
        deps.tts = _default_tts()
    yield


app = FastAPI(title="Mint backend", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    session = Session(
        deps.vad_factory(), deps.transcriber, deps.llm, deps.tts, sock.send_json, sock.send_bytes
    )  # type: ignore[arg-type]
    await sock.send_json({"type": "state", "value": "idle"})
    try:
        while True:
            msg = await sock.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await session.on_audio(msg["bytes"])
            elif msg.get("text") is not None:
                data = json.loads(msg["text"])
                if data.get("type") == "ping":
                    await sock.send_json({"type": "pong"})
                elif data.get("type") == "playback":
                    session.set_playing(bool(data.get("playing")))
                elif data.get("type") == "confirm_reply":
                    session.confirm_reply(data.get("id"), bool(data.get("ok")))
                elif data.get("type") == "user_text" and str(data.get("text", "")).strip():
                    await sock.send_json({"type": "transcript", "text": data["text"], "stt_ms": 0})
                    session.say_to_llm(data["text"].strip())
    except WebSocketDisconnect:
        pass
    finally:
        session.close()


def main():
    import uvicorn

    from .config import config

    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
