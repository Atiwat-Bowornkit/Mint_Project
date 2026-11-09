"""Does LLM CPU usage slow TTS? Run TTS calls while qwen is generating, per num_thread."""

import asyncio
import sys
import time

import ollama

from mint.llm import OPTIONS, Conversation
from mint.tts import EdgeTts


async def run(num_thread):
    client = ollama.AsyncClient()
    conv = Conversation()
    conv.add_user("เล่าเรื่องการไปเที่ยวทะเลให้ฟังหน่อย")
    opts = {**OPTIONS, "num_predict": 120}
    if num_thread:
        opts["num_thread"] = num_thread
    tts = EdgeTts()
    times = []
    toks = 0
    t_llm = None

    async def llm():
        nonlocal toks, t_llm
        first = None
        async for p in await client.chat(
            model="qwen2.5:3b", messages=conv.messages(), stream=True, options=opts, keep_alive="5m"
        ):
            if first is None:
                first = time.perf_counter()
            toks += 1
        t_llm = toks / (time.perf_counter() - first)

    async def speak():
        await asyncio.sleep(2.5)  # while generation is in full swing
        for x in ["สบายใจแล้วนะคะ", "ไปเที่ยวต่อกันไหมคะ", "อากาศดีจังเลยค่ะ", "ยินดีที่ได้รู้จักค่ะ"]:
            s = time.perf_counter()
            try:
                await tts._once(x)
                times.append(round(time.perf_counter() - s, 1))
            except Exception:
                times.append("FAIL")

    await asyncio.gather(llm(), speak())
    print(f"num_thread={num_thread or 'default'}: llm {t_llm:.1f} tok/s | tts during llm: {times}")


async def main():
    for n in [int(a) if a != "0" else 0 for a in sys.argv[1:]]:
        await run(n)


asyncio.run(main())
