"""Compare Whisper decoding settings on a test set built by build_stt_eval.py.

usage: bench_stt.py EVAL_DIR [model] [config ...]
Reports character error rate (CER, lower is better) per clip kind, time per clip, and how many
no-speech clips produced text anyway (hallucinations).
"""
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

PROMPT = "บทสนทนากับผู้ช่วยส่วนตัวชื่อมิ้นท์ เช่น เปิดโปรแกรม ตั้งเวลา ค้นหา ปรับเสียง เพลง ค่ะ นะคะ"
HOTWORDS = "มิ้นท์ ตั้งเวลา ไฟร์ฟอกซ์ ดิสคอร์ด เปิดเว็บ ปรับเสียง"


def normalise_gain(x: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(x))) if len(x) else 0
    return x * (0.7 / peak) if peak > 0.02 else x


CONFIGS = {
    "base": dict(beam_size=1),
    "beam5": dict(beam_size=5),
    "prompt": dict(beam_size=1, initial_prompt=PROMPT),
    "hotwords": dict(beam_size=1, hotwords=HOTWORDS),
    "prompt+beam5": dict(beam_size=5, initial_prompt=PROMPT),
    "gain": dict(beam_size=1, _gain=True),
    "gain+beam5": dict(beam_size=5, _gain=True),
}


def norm(s: str) -> str:
    return re.sub(r"[\s.,!?\-]+", "", s)


def cer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    if not r:
        return float(len(h) > 0)
    prev = list(range(len(h) + 1))
    for i, a in enumerate(r, 1):
        cur = [i]
        for j, b in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1] / len(r)


def main():
    d = Path(sys.argv[1])
    model_name = sys.argv[2] if len(sys.argv) > 2 else "small"
    names = sys.argv[3:] or list(CONFIGS)
    index = json.loads((d / "index.json").read_text())
    model = WhisperModel(model_name, device="cpu", compute_type="int8", local_files_only=True)
    audio = {c["file"]: np.frombuffer((d / c["file"]).read_bytes(), np.int16).astype(np.float32) / 32768 for c in index}
    model.transcribe(next(iter(audio.values())), language="th", beam_size=1)  # warm up
    rows, details = [], {}
    for name in names:
        cfg = dict(CONFIGS[name])
        gain = cfg.pop("_gain", False)
        errs: dict[str, list[float]] = {}
        halluc, t_total, per = 0, 0.0, []
        for c in index:
            x = normalise_gain(audio[c["file"]]) if gain else audio[c["file"]]
            t = time.perf_counter()
            segs, _ = model.transcribe(
                x, language="th", vad_filter=False, condition_on_previous_text=False, no_speech_threshold=0.6, **cfg
            )
            hyp = "".join(s.text for s in segs).strip()
            t_total += time.perf_counter() - t
            if c["kind"] == "nospeech":
                halluc += bool(hyp)
            else:
                errs.setdefault(c["kind"], []).append(cer(c["ref"], hyp))
            per.append({"file": c["file"], "kind": c["kind"], "ref": c["ref"], "hyp": hyp})
        details[name] = per
        all_e = [e for v in errs.values() for e in v]
        row = {k: f"{100 * np.mean(v):5.1f}" for k, v in errs.items()}
        rows.append((name, f"{100 * np.mean(all_e):5.1f}", row, f"{t_total / len(index):.2f}", halluc))
        print(f"{name:14} CER all {rows[-1][1]}%  " + "  ".join(f"{k} {v}%" for k, v in row.items())
              + f"  | {rows[-1][3]}s/clip | hallucinated {halluc}/5", flush=True)
    (d / f"results_{model_name}.json").write_text(json.dumps(details, ensure_ascii=False, indent=1))


main()
