from pysilero_vad import SileroVoiceActivityDetector

SAMPLES = 512
FRAME_BYTES = SAMPLES * 2


class Vad:
    """Per-connection Silero VAD (the detector is stateful)."""

    def __init__(self) -> None:
        self._det = SileroVoiceActivityDetector()

    def prob(self, frame: bytes) -> float:
        return float(self._det(frame))

    def reset(self) -> None:
        self._det.reset()
