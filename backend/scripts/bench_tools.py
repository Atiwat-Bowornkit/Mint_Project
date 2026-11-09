"""Does the model pick the right tool (and only when asked)? Run against Ollama."""
import asyncio
import sys
import time

from mint.llm import Llm
from mint.tools import looks_like_command

CASES = [  # (utterance, expected tool or None)
    ("เปิดไฟร์ฟอกซ์หน่อย", "open_app"),
    ("เปิดดิสคอร์ดให้หน่อยสิ", "open_app"),
    ("ช่วยเปิดเทอร์มินัลที", "open_app"),
    ("ตั้งเวลาห้านาที", "set_timer"),
    ("ตั้งนาฬิกาปลุกอีก 10 นาที ต้มมาม่า", "set_timer"),
    ("ยกเลิกตัวจับเวลาที", "cancel_timers"),
    ("ตอนนี้กี่โมงแล้ว", "get_time"),
    ("วันนี้วันอะไร", "get_time"),
    ("ปรับเสียงเหลือสามสิบเปอร์เซ็นต์", "set_volume"),
    ("เพลงถัดไป", "media_control"),
    ("หยุดเพลงก่อน", "media_control"),
    ("ค้นหาสูตรต้มยำกุ้งให้หน่อย", "web_search"),
    ("เปิดเว็บ github.com", "open_url"),
    ("สวัสดี วันนี้เป็นไงบ้าง", None),
    ("เธอชอบกินอะไร", None),
    ("ฉันเหนื่อยจังเลย", None),
    ("ไฟร์ฟอกซ์คืออะไรเหรอ", None),
    ("เมื่อวานฉันนอนไม่หลับ", None),
    ("อากาศร้อนจังเลยนะ", None),
    ("เล่าเรื่องตลกให้ฟังหน่อย", None),
]


async def main(model: str):
    llm = Llm(model)
    await llm.warmup()
    ok = 0
    for text, want in CASES:
        t0 = time.perf_counter()
        gated = not looks_like_command(text)
        call = None if gated else await llm.route(text)
        got = call.name if call else None
        good = got == want
        ok += good
        print(f"{'OK ' if good else 'BAD'} {time.perf_counter()-t0:4.1f}s {text!r:45} want={want} got={got} gated_out={gated} {call.args if call else ''} ")
    print(f"\n{ok}/{len(CASES)} correct")

asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:3b"))
