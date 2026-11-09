from mint.endpointing import Discard, End, Endpointer, Start

F = b"\x01\x00" * 512


def run(ep, probs):
    out = []
    for p in probs:
        out += ep.feed(F, p)
    return out


def test_silence_emits_nothing():
    assert run(Endpointer(), [0.01] * 100) == []


def test_utterance_start_and_end():
    ep = Endpointer(end_silence_ms=320, min_speech_ms=64)
    ev = run(ep, [0.0] * 20 + [0.9] * 10 + [0.0] * 10)
    assert isinstance(ev[0], Start)
    assert isinstance(ev[1], End)
    assert len(ev) == 2
    assert not ep.speaking


def test_preroll_is_included():
    ep = Endpointer(end_silence_ms=320, preroll_ms=320, min_speech_ms=64)
    ev = run(ep, [0.0] * 20 + [0.9] * 10 + [0.0] * 10)
    end = ev[1]
    # 10 pre-roll + 10 speech + 10 trailing silence frames
    assert len(end.pcm) == 30 * len(F)


def test_short_blip_is_discarded():
    ep = Endpointer(end_silence_ms=320, min_speech_ms=250)
    ev = run(ep, [0.9] + [0.0] * 12)
    assert isinstance(ev[0], Start) and isinstance(ev[1], Discard)


def test_pause_shorter_than_threshold_does_not_split():
    ep = Endpointer(end_silence_ms=640, min_speech_ms=64)
    ev = run(ep, [0.9] * 5 + [0.0] * 10 + [0.9] * 5 + [0.0] * 25)
    assert [type(e) for e in ev] == [Start, End]


def test_max_length_forces_end():
    ep = Endpointer(max_utterance_ms=320, min_speech_ms=64)
    ev = run(ep, [0.9] * 15)
    assert any(isinstance(e, End) for e in ev)


def test_barge_in_ignores_quiet_or_brief_sound():
    ep = Endpointer()
    ep.barge_in = True
    # moderately loud echo-like sound, and a short loud burst, must not start an utterance
    assert run(ep, [0.7] * 40) == []
    assert run(ep, [0.95] * 5 + [0.0] * 5) == []
    assert not ep.speaking


def test_barge_in_accepts_sustained_loud_speech():
    ep = Endpointer(end_silence_ms=320, min_speech_ms=64)
    ep.barge_in = True
    ev = run(ep, [0.0] * 10 + [0.95] * 12 + [0.0] * 10)
    assert [type(e) for e in ev] == [Start, End]
    # the frames that triggered the start are kept in the audio
    assert len(ev[1].pcm) >= (12 + 10) * len(F)
