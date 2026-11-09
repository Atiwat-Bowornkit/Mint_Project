"""Build a small Thai speech test set with edge-tts (sends these test sentences to Microsoft).

usage: build_stt_eval.py OUT_DIR
Writes OUT_DIR/*.pcm (int16 16 kHz mono) and OUT_DIR/index.json [{file, ref, kind}].
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from mint.tts import EdgeTts

SENTENCES = [
    # commands
    "เปิดไฟร์ฟอกซ์หน่อย", "ตั้งเวลาห้านาที", "ตอนนี้กี่โมงแล้ว", "ปรับเสียงเหลือสามสิบเปอร์เซ็นต์",
    "เพลงถัดไป", "ค้นหาสูตรต้มยำกุ้งให้หน่อย", "ยกเลิกตัวจับเวลาที", "ช่วยเปิดเครื่องคิดเลขหน่อย",
    "เปิดดิสคอร์ดให้หน่อยสิ", "หยุดเพลงก่อน", "ได้เลยค่ะ", "ไม่เอา", "เปิดเพลงเบาๆ ฟังหน่อย",
    # chat
    "สวัสดีมิ้นท์ วันนี้เป็นไงบ้าง", "ฉันเหนื่อยจังเลย งานเยอะมาก", "เมื่อวานฉันไปเที่ยวทะเลมา สนุกมากเลย",
    "เธอชอบกินอะไรเหรอ", "ช่วยแนะนำเมนูมื้อเย็นหน่อย", "ฉันสอบผ่านแล้ว", "อากาศร้อนจังเลยนะ",
    "เล่าเรื่องตลกให้ฟังหน่อย", "วันนี้ฝนตกหนักมาก", "พรุ่งนี้ต้องตื่นเช้า", "ฉันอยากกินข้าวมันไก่",
    "ขอบคุณนะมิ้นท์", "มิ้นท์ช่วยตั้งนาฬิกาปลุกหน่อยได้ไหมคะ",
]
VOICES = ["th-TH-PremwadeeNeural", "th-TH-NiwatNeural"]


def to_pcm(mp3: bytes) -> np.ndarray:
    p = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "s16le", "pipe:1"],
        input=mp3, capture_output=True, check=True,
    )
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768


def degrade(x: np.ndarray, kind: str, rng) -> np.ndarray:
    if kind == "clean":
        return x
    rms = np.sqrt(np.mean(x**2)) + 1e-9
    if kind == "noisy":  # ~12 dB SNR background noise
        return x + rng.normal(0, rms / 10 ** (12 / 20), x.shape).astype(np.float32)
    if kind == "quiet":  # soft speaker far from the mic, light noise
        y = x * 0.08
        return y + rng.normal(0, 0.0015, x.shape).astype(np.float32)
    raise ValueError(kind)


def save(path: Path, x: np.ndarray):
    pad = np.zeros(8000, np.float32)  # 0.5 s lead/tail, like the endpointer's pre-roll
    y = np.concatenate([pad, x, pad])
    path.write_bytes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())


async def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    tts = {v: EdgeTts(voice=v, rate="+0%", pitch="+0Hz") for v in VOICES}
    sem = asyncio.Semaphore(2)

    async def one(i, s, v):
        async with sem:
            for attempt in range(6):
                try:
                    return i, s, v, await tts[v].synth(s)
                except Exception:
                    await asyncio.sleep(1 + attempt)
            raise RuntimeError(f"TTS kept failing for {s!r}")

    results = await asyncio.gather(*(one(i, s, v) for i, s in enumerate(SENTENCES) for v in VOICES))
    index = []
    for i, s, v, mp3 in results:
        x = to_pcm(mp3)
        kinds = ["clean"] + (["noisy"] if i % 2 == 0 else ["quiet"])
        for k in kinds:
            name = f"{i:02d}_{v.split('-')[2][:4]}_{k}.pcm"
            save(out / name, degrade(x, k, rng))
            index.append({"file": name, "ref": s, "kind": k})
    # clips with NO speech: the transcriber must stay silent (hallucination check)
    for j, (name, x) in enumerate(
        [("silence", np.zeros(32000)), ("hiss", rng.normal(0, 0.003, 48000)), ("loud_hiss", rng.normal(0, 0.03, 48000)),
         ("hum", 0.05 * np.sin(2 * np.pi * 120 * np.arange(48000) / 16000)), ("click_noise", rng.normal(0, 0.01, 32000))]
    ):
        (out / f"nospeech_{name}.pcm").write_bytes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
        index.append({"file": f"nospeech_{name}.pcm", "ref": "", "kind": "nospeech"})
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(len(index), "clips ->", out)


asyncio.run(main(Path(sys.argv[1])))
