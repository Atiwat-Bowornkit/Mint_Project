from mint.chunker import Sentence, SentenceChunker


def run(tokens):
    c = SentenceChunker()
    out = []
    for t in tokens:
        out += c.feed(t)
    return out + c.flush()


def test_tags_split_sentences_and_set_emotion():
    out = run(["[wor", "ried] เหนื่อย", "มากเลยเหรอคะ ", "[happy] พักผ่อน", "นะคะ"])
    assert out == [Sentence("เหนื่อยมากเลยเหรอคะ", "worried"), Sentence("พักผ่อนนะคะ", "happy")]


def test_tag_split_across_tokens_is_never_spoken():
    out = run(list("[happy] สวัสดีค่ะ"))
    assert out == [Sentence("สวัสดีค่ะ", "happy")]


def test_punctuation_splits():
    out = run(["[happy] ดีใจจัง! ", "ไปไหนดีคะ? ", "บอกมิ้นท์ได้นะ."])
    assert [s.text for s in out] == ["ดีใจจัง!", "ไปไหนดีคะ?", "บอกมิ้นท์ได้นะ."]
    assert all(s.emotion == "happy" for s in out)


def test_unknown_tag_dropped_keeps_emotion():
    out = run(["[happy] ก่อน ", "[weird] ต่อ"])
    assert [s.emotion for s in out] == ["happy", "happy"]
    assert "weird" not in "".join(s.text for s in out)


def test_markdown_and_emoji_free_text():
    out = run(["**สวัสดี**ค่ะ\n", "ยินดีที่ได้รู้จัก"])
    assert [s.text for s in out] == ["สวัสดีค่ะ", "ยินดีที่ได้รู้จัก"]


def test_long_thai_without_punctuation_splits_at_space():
    long = ("ก" * 45) + " " + ("ข" * 10)
    out = run([long])
    assert len(out) == 2 and out[0].text == "ก" * 45


def test_default_emotion_neutral():
    assert run(["สวัสดีค่ะ"]) == [Sentence("สวัสดีค่ะ", "neutral")]


def test_polite_particle_followed_by_space_ends_sentence():
    c = SentenceChunker()
    out = c.feed("[happy] ยินดีค่ะ ")
    assert out == [Sentence("ยินดีค่ะ", "happy")]
    # without the trailing space we must wait: the next token could continue the word
    assert SentenceChunker().feed("ยินดีค่ะ") == []
