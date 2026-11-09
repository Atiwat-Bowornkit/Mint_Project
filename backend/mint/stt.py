import logging
import threading

import numpy as np

from .config import config

log = logging.getLogger("mint.stt")


class Transcriber:
    """faster-whisper wrapper; the model loads lazily on first use."""

    def __init__(self, model: str | None = None, language: str | None = None):
        self.model_name = model or config.stt_model
        self.language = language or config.stt_language
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        from faster_whisper import WhisperModel

        # Prefer the local cache so nothing touches the network once the model is downloaded.
        for local_only in (True, False):
            try:
                return WhisperModel(
                    self.model_name, device="cpu", compute_type="int8", local_files_only=local_only
                )
            except Exception:
                if not local_only:
                    raise
                log.info("model %s not cached, falling back to download", self.model_name)

    def warmup(self) -> None:
        with self._lock:
            if self._model is None:
                self._model = self._load()

    def transcribe(self, pcm: bytes, hint: str | None = None) -> str:
        """`hint` biases decoding towards words we expect (e.g. the answer to a yes/no question)."""
        self.warmup()
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(  # type: ignore[union-attr]
            audio,
            language=self.language,
            beam_size=config.stt_beam,
            initial_prompt=hint,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
        )
        return "".join(s.text for s in segments).strip()
