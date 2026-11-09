"""Compare Ollama models on Thai chat: latency, speed, tag compliance, sample output."""
import asyncio
import sys
import time

from mint.chunker import SentenceChunker
from mint.llm import Conversation, Llm

PROMPTS = [
    "สวัสดี วันนี้เป็นไงบ้าง",
    "วันนี้เหนื่อยจังเลย งานเยอะมาก",
    "ช่วยแนะนำเมนูมื้อเย็นหน่อย",
    "ฉันสอบผ่านแล้ว!",
    "เธอชื่ออะไรเหรอ",
]


async def run(model: str) -> None:
    llm = Llm(model)
    t = time.perf_counter()
    await llm.warmup()
    print(f"\n=== {model} (load/warmup {time.perf_counter()-t:.1f}s)")
    firsts, rates, tagged, total = [], [], 0, 0
    for p in PROMPTS:
        conv = Conversation()
        conv.add_user(p)
        ch = SentenceChunker()
        t0 = time.perf_counter()
        first = first_sent = None
        n = 0
        raw = ""
        sents = []
        async for tok in llm.stream(conv.messages()):
            if first is None:
                first = time.perf_counter() - t0
            n += 1
            raw += tok
            for s in ch.feed(tok):
                if first_sent is None:
                    first_sent = time.perf_counter() - t0
                sents.append(s)
        sents += ch.flush()
        dt = time.perf_counter() - t0
        firsts.append(first_sent or dt)
        rates.append(n / (dt - first) if dt > first else 0)
        total += 1
        tagged += raw.lstrip().startswith("[")
        print(f"\nUser: {p}\n  first-token {first:.2f}s | first-sentence {first_sent or 0:.2f}s | {n} tok @ {rates[-1]:.1f} tok/s")
        for s in sents:
            print(f"  [{s.emotion}] {s.text}")
    print(f"\n  avg first-sentence {sum(firsts)/len(firsts):.2f}s | avg {sum(rates)/len(rates):.1f} tok/s | tag at start {tagged}/{total}")


async def main():
    for m in sys.argv[1:]:
        await run(m)


asyncio.run(main())
