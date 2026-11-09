"""Turns a stream of per-frame speech probabilities into utterances."""
from collections import deque
from dataclasses import dataclass

FRAME_MS = 32  # 512 samples @ 16 kHz


@dataclass(frozen=True)
class Start:
    pass


@dataclass(frozen=True)
class End:
    pcm: bytes  # int16 LE mono 16 kHz, includes pre-roll


@dataclass(frozen=True)
class Discard:
    """Speech started but was too short to be an utterance (noise, click)."""


Event = Start | End | Discard


class Endpointer:
    def __init__(
        self,
        start_prob: float = 0.5,
        end_prob: float = 0.35,
        end_silence_ms: int = 700,
        preroll_ms: int = 320,
        min_speech_ms: int = 250,
        max_utterance_ms: int = 20_000,
        barge_start_prob: float = 0.85,
        barge_start_frames: int = 6,
    ):
        self.start_prob = start_prob
        self.end_prob = end_prob
        self.end_silence_frames = end_silence_ms // FRAME_MS
        self.min_speech_frames = min_speech_ms // FRAME_MS
        self.max_frames = max_utterance_ms // FRAME_MS
        # While the assistant is talking, its own voice can leak into the mic: demand clearly
        # louder, sustained speech (barge_start_frames * 32 ms) before calling it the user.
        self.barge_in = False
        self.barge_start_prob = barge_start_prob
        self.barge_start_frames = barge_start_frames
        self._pre_n = max(1, preroll_ms // FRAME_MS)
        self._preroll: deque[bytes] = deque(maxlen=self._pre_n + barge_start_frames)
        self.reset()

    @property
    def speaking(self) -> bool:
        return self._speaking

    def reset(self) -> None:
        self._preroll.clear()
        self._buf: list[bytes] = []
        self._speaking = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._run = 0  # consecutive loud frames while idle

    def feed(self, frame: bytes, prob: float) -> list[Event]:
        if not self._speaking:
            self._preroll.append(frame)
            thr = self.barge_start_prob if self.barge_in else self.start_prob
            need = self.barge_start_frames if self.barge_in else 1
            self._run = self._run + 1 if prob >= thr else 0
            if self._run < need:
                return []
            self._speaking = True
            self._buf = list(self._preroll)[-(self._pre_n + need) :]
            self._preroll.clear()
            self._speech_frames = self._run
            self._silence_frames = 0
            self._run = 0
            return [Start()]

        self._buf.append(frame)
        if prob >= self.end_prob:
            self._speech_frames += 1
            self._silence_frames = 0
        else:
            self._silence_frames += 1

        if self._silence_frames >= self.end_silence_frames or len(self._buf) >= self.max_frames:
            return [self._finish()]
        return []

    def _finish(self) -> Event:
        long_enough = self._speech_frames >= self.min_speech_frames
        pcm = b"".join(self._buf)
        self.reset()
        return End(pcm) if long_enough else Discard()
