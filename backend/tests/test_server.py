import asyncio
import json
import struct

from fastapi.testclient import TestClient

from mint import server
from mint.server import app
from mint.session import Session

FRAME = struct.pack("<512h", *([1000] * 512))


class FakeVad:
    """Speech while the frame counter is inside [start, stop)."""

    def __init__(self, start=3, stop=13):
        self.n, self.start, self.stop = 0, start, stop

    def prob(self, frame):
        self.n += 1
        return 0.9 if self.start <= self.n < self.stop else 0.0

    def reset(self):
        self.n = 0


class FakeStt:
    def __init__(self, text="สวัสดี"):
        self.text, self.calls = text, []

    def transcribe(self, pcm, hint=None):
        self.calls.append(len(pcm))
        self.hints = getattr(self, "hints", []) + [hint]
        return self.text


class FakeLlm:
    def __init__(self, tokens=("[hap", "py] สวัสดีค่ะ ", "[shy] ยินดี", "ที่ได้รู้จักค่ะ"), call=None):
        self.tokens, self.seen, self.call = tokens, [], call

    async def route(self, text):
        return self.call

    async def stream(self, messages):
        self.seen.append(messages)
        for t in self.tokens:
            yield t


class FakeTts:
    def __init__(self, fail_on=None):
        self.fail_on, self.calls = fail_on, []

    async def synth(self, text):
        self.calls.append(text)
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("offline")
        return b"AUDIO:" + text.encode()


def setup(**kw):
    server.deps.vad_factory = FakeVad
    server.deps.transcriber = kw.get("stt", FakeStt())
    server.deps.llm = kw.get("llm", FakeLlm())
    server.deps.tts = kw.get("tts", FakeTts())


def test_health():
    assert TestClient(app).get("/health").json() == {"ok": True}


def test_ws_ping():
    setup()
    with TestClient(app).websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"type": "state", "value": "idle"}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_audio_to_transcript_to_reply():
    stt, llm = FakeStt(), FakeLlm()
    setup(stt=stt, llm=llm)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.receive_json()
        # odd chunk size on purpose: the session must re-frame to 512 samples
        data = FRAME * 40
        for i in range(0, len(data), 700):
            ws.send_bytes(data[i : i + 700])
        msgs = []
        while not (msgs and msgs[-1] == {"type": "state", "value": "idle"} and len(msgs) > 4):
            m = ws.receive()
            if m.get("bytes") is not None:
                msgs.append({"type": "audio", "data": m["bytes"]})
            else:
                msgs.append(json.loads(m["text"]))
    kinds = [(m["type"], m.get("value") or m.get("text")) for m in msgs]
    assert kinds[:4] == [
        ("interrupt", None),
        ("state", "listening"),
        ("state", "thinking"),
        ("transcript", "สวัสดี"),
    ]
    # every reply is directly followed by its own audio frame
    for i, m in enumerate(msgs):
        if m["type"] == "reply":
            assert m["audio"] is True
            assert msgs[i + 1] == {"type": "audio", "data": b"AUDIO:" + m["text"].encode()}
    replies = [m for m in msgs if m["type"] == "reply"]
    assert [(r["text"], r["emotion"]) for r in replies] == [
        ("สวัสดีค่ะ", "happy"),
        ("ยินดีที่ได้รู้จักค่ะ", "shy"),
    ]
    assert llm.seen[0][-1] == {"role": "user", "content": "สวัสดี"}
    assert len(stt.calls) == 1


async def test_new_speech_cancels_reply_and_keeps_partial_history():
    gate = asyncio.Event()

    class SlowLlm:
        async def route(self, text):
            return None

        async def stream(self, messages):
            yield "[happy] ประโยคแรกค่ะ "
            await gate.wait()
            yield "ไม่ควรมาถึง"

    sent = []

    async def send(m):
        sent.append(m)

    async def send_audio(b):
        sent.append({"type": "audio"})

    s = Session(FakeVad(), FakeStt(), SlowLlm(), FakeTts(), send, send_audio)
    s._respond_task = asyncio.create_task(s._respond("ทดสอบ"))
    await asyncio.sleep(0.05)
    assert any(m["type"] == "reply" for m in sent)
    from mint.endpointing import Start

    await s._handle(Start())
    await asyncio.sleep(0.05)
    assert {"type": "interrupt"} in sent
    assert sent[-1] == {"type": "state", "value": "listening"}
    assert "ไม่ควรมาถึง" not in str(s.conv.turns)
    assert s.conv.turns[-1]["role"] == "assistant"


async def test_tts_failure_falls_back_to_text_only():
    sent = []

    async def send(m):
        sent.append(m)

    async def send_audio(b):
        sent.append({"type": "audio"})

    s = Session(FakeVad(), FakeStt(), FakeLlm(("[happy] ดีค่ะ ", "[shy] ไปก่อนนะคะ")), FakeTts("ไปก่อน"), send, send_audio)
    await s._respond("hi")
    replies = [m for m in sent if m["type"] == "reply"]
    assert [(r["text"], r["audio"]) for r in replies] == [("ดีค่ะ", True), ("ไปก่อนนะคะ", False)]
    assert sent[-1] == {"type": "state", "value": "idle"}


def test_typed_message_goes_straight_to_llm():
    llm = FakeLlm()
    setup(llm=llm)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_text", "text": "  สวัสดี  "})
        assert ws.receive_json() == {"type": "transcript", "text": "  สวัสดี  ", "stt_ms": 0}
        while True:
            m = ws.receive()
            if m.get("text") and json.loads(m["text"]) == {"type": "state", "value": "idle"}:
                break
    assert llm.seen[0][-1] == {"role": "user", "content": "สวัสดี"}


def test_metrics_sent_with_first_reply_and_playback_toggles_barge_in():
    setup()
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "playback", "playing": True})
        ws.send_json({"type": "user_text", "text": "สวัสดี"})
        metrics = None
        while True:
            m = ws.receive()
            if m.get("text"):
                d = json.loads(m["text"])
                if d["type"] == "metrics":
                    metrics = d
                if d == {"type": "state", "value": "idle"}:
                    break
    assert metrics and metrics["stt_ms"] is None and metrics["endpoint_ms"] == 0
    assert metrics["llm_ms"] is not None and metrics["server_ms"] >= metrics["tts_ms"] >= 0
