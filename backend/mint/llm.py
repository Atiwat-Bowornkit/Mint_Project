from collections.abc import AsyncIterator
from dataclasses import dataclass

import ollama

from .config import config
from .tools import TOOL_SCHEMAS


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict

SYSTEM_PROMPT = """คุณคือ "มิ้นท์" ผู้ช่วยส่วนตัวที่น่ารัก สดใส และเป็นกันเอง กำลังคุยกับผู้ใช้ด้วยเสียง
กติกา:
- ตอบเป็นภาษาไทย ใช้ภาษาพูดธรรมชาติ ลงท้ายด้วย "ค่ะ" "นะคะ" "คะ" ตามความเหมาะสม
- ตอบสั้นๆ 1-3 ประโยค เพราะผู้ใช้จะฟังเสียง ห้ามใช้หัวข้อ ลิสต์ markdown หรืออีโมจิ
- ขึ้นต้นทุกประโยคด้วยแท็กอารมณ์หนึ่งอย่างในวงเล็บเหลี่ยม เลือกจาก:
  [neutral] [happy] [shy] [sad] [surprised] [worried] [gloomy]
- ห้ามอธิบายเรื่องแท็ก
"""

FEWSHOT = [
    ("วันนี้เหนื่อยจังเลย", "[worried] เหนื่อยมากเลยเหรอคะ [happy] พักผ่อนสักหน่อยนะคะ มิ้นท์อยู่ตรงนี้ค่ะ"),
    ("ฉันได้งานใหม่แล้ว", "[surprised] จริงเหรอคะ! [happy] ยินดีด้วยนะคะ เก่งมากเลยค่ะ"),
    ("เธอทำอะไรได้บ้าง", "[neutral] มิ้นท์คุยเป็นเพื่อนและช่วยตอบคำถามได้ค่ะ [happy] ลองถามอะไรก็ได้เลยนะคะ"),
]


ROUTER_PROMPT = (
    "You control a computer for the user through tools. Call a tool ONLY when the user explicitly "
    "asks you to perform an action that matches one of the tools. For greetings, chit-chat, "
    "questions, feelings, stories or advice, do NOT call any tool: reply with the single word NONE."
)


class Conversation:
    """Chat history with a sliding window (system prompt is always kept)."""

    def __init__(self, max_turns: int = 8):
        self.max_turns = max_turns
        self.turns: list[dict] = []

    def add_user(self, text: str) -> None:
        self.turns.append({"role": "user", "content": text})
        self.turns = self.turns[-2 * self.max_turns :]

    def add_assistant(self, text: str) -> None:
        self.turns.append({"role": "assistant", "content": text})

    def messages(self) -> list[dict]:
        shots = [
            m
            for u, a in FEWSHOT
            for m in ({"role": "user", "content": u}, {"role": "assistant", "content": a})
        ]
        return [{"role": "system", "content": SYSTEM_PROMPT}, *shots, *self.turns]


OPTIONS = {"temperature": 0.7, "num_ctx": 2048, "num_predict": 200, "num_thread": config.llm_threads}


class Llm:
    def __init__(self, model: str | None = None):
        self.model = model or config.llm_model
        self._client = ollama.AsyncClient()

    async def warmup(self) -> None:
        # Same system+few-shot prefix as real requests, so Ollama caches its prompt evaluation.
        conv = Conversation()
        conv.add_user("สวัสดี")
        await self._client.chat(
            model=self.model, messages=conv.messages(),
            options={**OPTIONS, "num_predict": 1}, keep_alive="30m",
        )
        await self.route("สวัสดี")

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        async for part in await self._client.chat(
            model=self.model,
            messages=messages,
            stream=True,
            keep_alive="30m",
            options=OPTIONS,
        ):
            tok = part["message"]["content"]
            if tok:
                yield tok

    async def route(self, user_text: str) -> ToolCall | None:
        """Decide whether the request is a command for one of our tools.

        Done as a separate, short-prompt call: with the long persona prompt (tag every sentence)
        the 3B model stops calling tools at all, while a minimal prompt gets it right.
        """
        stream = await self._client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": ROUTER_PROMPT},
                {"role": "user", "content": user_text},
            ],
            tools=TOOL_SCHEMAS,
            stream=True,
            keep_alive="30m",
            options={"temperature": 0, "num_ctx": 2048, "num_predict": 48, "num_thread": config.llm_threads},
        )
        try:
            async for part in stream:
                msg = part["message"]
                for call in msg.get("tool_calls") or []:
                    return ToolCall(call["function"]["name"], dict(call["function"]["arguments"] or {}))
                if msg["content"].strip():  # started answering in words: not a command
                    return None
        finally:
            await stream.aclose()
        return None
