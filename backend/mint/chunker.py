"""Splits an LLM token stream into speakable sentences tagged with an emotion."""
import re
from dataclasses import dataclass

EMOTIONS = {"neutral", "happy", "shy", "sad", "surprised", "worried", "gloomy"}

_TAG = re.compile(r"\[([A-Za-z]{2,12})\]")
_STRIP = re.compile(r"[*#`_~>]+")
# Thai rarely uses punctuation: a polite particle followed by a space also ends a sentence.
_END = re.compile(r"[!?！？。]+|\.(?=\s)|\n|(?:นะคะ|ค่ะ|คะ|ครับ|จ้ะ|จ้า)(?=\s)")


@dataclass(frozen=True)
class Sentence:
    text: str
    emotion: str


class SentenceChunker:
    """Feed tokens, get complete sentences. `[emotion]` tags are consumed, never spoken."""

    def __init__(self, soft_limit: int = 40):
        self.soft_limit = soft_limit  # split Thai (no punctuation) at a space beyond this length
        self.emotion = "neutral"
        self._buf = ""

    def feed(self, token: str) -> list[Sentence]:
        self._buf += token
        out: list[Sentence] = []
        while True:
            # hold back a possibly-incomplete tag like "[hap"
            open_ = self._buf.rfind("[")
            if open_ != -1 and "]" not in self._buf[open_:] and len(self._buf) - open_ <= 12:
                head, tail = self._buf[:open_], self._buf[open_:]
            else:
                head, tail = self._buf, ""
            cut = self._next_cut(head)
            if cut is None:
                self._buf = head + tail
                return out
            piece, rest = head[:cut], head[cut:]
            out += self._emit(piece)
            self._buf = rest + tail

    def flush(self) -> list[Sentence]:
        out = self._emit(self._buf)
        self._buf = ""
        return out

    def _next_cut(self, s: str) -> int | None:
        tag = _TAG.search(s)
        end = _END.search(s)
        cands = []
        if tag and tag.start() > 0:
            cands.append(tag.start())  # text before a tag belongs to the previous emotion
        elif tag:
            cands.append(tag.end())
        if end:
            cands.append(end.end())
        if len(s) >= self.soft_limit:
            sp = s.find(" ", self.soft_limit)
            if sp != -1:
                cands.append(sp + 1)
        return min(cands) if cands else None

    def _emit(self, piece: str) -> list[Sentence]:
        out: list[Sentence] = []
        m = _TAG.fullmatch(piece.strip())
        if m:
            tag = m.group(1).lower()
            if tag in EMOTIONS:
                self.emotion = tag
            return out
        text = _STRIP.sub("", _TAG.sub("", piece)).strip()
        if text and re.search(r"\w", text):
            out.append(Sentence(text, self.emotion))
        return out
