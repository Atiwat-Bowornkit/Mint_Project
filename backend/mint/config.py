import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = int(os.getenv("MINT_PORT", "8765"))
    stt_model: str = os.getenv("MINT_STT_MODEL", "small")
    stt_beam: int = int(os.getenv("MINT_STT_BEAM", "5"))  # 5 cut CER 22.2% -> 19.8% on our Thai test set
    stt_language: str = os.getenv("MINT_STT_LANG", "th")
    llm_model: str = os.getenv("MINT_LLM_MODEL", "qwen2.5:3b")
    end_silence_ms: int = int(os.getenv("MINT_END_SILENCE_MS", "500"))
    # Ollama's default (all 14 logical cores) measured 2.6x slower than 8 threads on this machine.
    llm_threads: int = int(os.getenv("MINT_LLM_THREADS", "8"))
    tts_hedge_s: float = float(os.getenv("MINT_TTS_HEDGE_S", "0.7"))  # edge-tts is flaky: race a 2nd request
    tts_voice: str = os.getenv("MINT_TTS_VOICE", "th-TH-PremwadeeNeural")
    tts_rate: str = os.getenv("MINT_TTS_RATE", "+5%")
    tts_pitch: str = os.getenv("MINT_TTS_PITCH", "+15Hz")
    sample_rate: int = 16000


config = Config()
