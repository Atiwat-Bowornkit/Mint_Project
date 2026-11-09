import asyncio
import datetime as dt
from pathlib import Path

import pytest

from mint import tools
from mint.endpointing import FRAME_MS  # noqa: F401  (import check)
from mint.llm import ToolCall
from mint.session import Session
from mint.tools import (
    TOOLS,
    App,
    AppIndex,
    classify_confirmation,
    normalize_url,
    parse_desktop,
)


class FakeHost:
    def __init__(self):
        self.timers, self.cancelled = [], 0

    def start_timer(self, seconds, label):
        self.timers.append((seconds, label))

    def cancel_timers(self):
        return 2


@pytest.fixture
def cmds(monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "PLATFORM", "linux")  # these tests assert the Linux commands

    async def fake(*argv, wait_s=3.0):
        calls.append(argv)
        return 0

    monkeypatch.setattr(tools, "run_cmd", fake)
    return calls


# ---- pure helpers ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("github.com", "https://github.com"),
        ("https://example.com/a?b=1", "https://example.com/a?b=1"),
        ("http://localhost:8000", "http://localhost:8000"),
        ("file:///etc/passwd", None),
        ("javascript:alert(1)", None),
        ("ftp://x.org", None),
        ("https://user:pw@evil.com", None),
        ("not a url", None),
        ("", None),
        ("https://a.com; rm -rf ~", None),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ได้", True), ("ได้เลยค่ะ", True), ("ตกลง", True), ("โอเค", True), ("ค่ะ", True), ("ใช่", True),
        ("ไม่", False), ("ไม่เอา", False), ("ไม่ได้", False), ("ยกเลิก", False), ("อย่าเปิด", False),
        ("ใช่ไหมคะ", None), ("ได้ไหม", None), ("จะเปิดโปรแกรมดิสคอร์ดใช่ไหมคะ", None),  # her own question echoed back
        ("เปิดเลยค่ะ", True), ("ไม่ใช่", False), ("ได้ค่ะ", True), ("OK", True),
        ("วันนี้อากาศดีจังเลย", None), ("เปิดดิสคอร์ดแทนได้ไหม", None), ("เล่าเรื่องตลกให้ฟังหน่อยสิ แล้วก็ช่วยเล่าให้ยาวๆ", None),
    ],
)
def test_classify_confirmation(text, expected):
    assert classify_confirmation(text) is expected


def test_desktop_parsing_and_resolving(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(tools, "PLATFORM", "linux")  # .desktop files are the Linux app source
    (tmp_path / "org.mozilla.firefox.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Firefox Web Browser\nGenericName=Web Browser\nExec=firefox\n"
    )
    (tmp_path / "hidden.desktop").write_text("[Desktop Entry]\nType=Application\nName=Secret\nNoDisplay=true\n")
    (tmp_path / "kitty.desktop").write_text("[Desktop Entry]\nType=Application\nName=kitty\nExec=kitty\n")
    (tmp_path / "[bad].desktop").write_text("garbage")
    idx = AppIndex(dirs=[tmp_path])
    assert {a.id for a in idx.apps} == {"org.mozilla.firefox", "kitty"}
    assert idx.resolve("firefox").id == "org.mozilla.firefox"
    assert idx.resolve("ไฟร์ฟอกซ์").id == "org.mozilla.firefox"  # alias
    assert idx.resolve("Kitty").id == "kitty"
    assert idx.resolve("secret") is None
    assert idx.resolve("photoshop") is None
    assert idx.resolve("x") is None
    assert parse_desktop(tmp_path / "hidden.desktop") is None


# ---- tool handlers --------------------------------------------------------------------------


async def test_get_time(monkeypatch):
    monkeypatch.setattr(tools, "now", lambda: dt.datetime(2026, 11, 9, 14, 5))
    r = await TOOLS["get_time"].run({}, FakeHost())
    assert "14 นาฬิกา 5 นาที" in r.text and "วันจันทร์ที่ 9 พฤศจิกายน" in r.text


async def test_set_timer_variants_and_limits():
    h = FakeHost()
    r = await TOOLS["set_timer"].run({"minutes": "5", "label": "มาม่า"}, h)  # strings from the model
    assert h.timers == [(300.0, "มาม่า")] and "5 นาที" in r.text
    await TOOLS["set_timer"].run({"seconds": 30}, h)
    assert h.timers[-1] == (30.0, "")
    assert (await TOOLS["set_timer"].run({}, h)).emotion == "worried"
    assert "ยี่สิบสี่ชั่วโมง" in (await TOOLS["set_timer"].run({"minutes": 99999}, h)).text
    assert len(h.timers) == 2  # the rejected ones started nothing


async def test_media_and_volume_use_argv_not_shell(cmds):
    await TOOLS["media_control"].run({"action": "next"}, FakeHost())
    assert cmds[-1] == ("playerctl", "next")
    r = await TOOLS["media_control"].run({"action": "rm -rf /"}, FakeHost())
    assert len(cmds) == 1 and r.emotion == "worried"  # unknown action never reaches a process
    await TOOLS["set_volume"].run({"percent": 250}, FakeHost())
    assert cmds[-1] == ("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "1.00")  # clamped
    await TOOLS["set_volume"].run({"percent": "30"}, FakeHost())
    assert cmds[-1][-1] == "0.30"


async def test_open_app_and_url_and_search(cmds, monkeypatch):
    monkeypatch.setattr(tools, "app_index", AppIndex(apps=[App("firefox", "Firefox", ("firefox",))]))
    assert "Firefox" in (await TOOLS["open_app"].run({"name": "firefox"}, FakeHost())).text
    assert cmds[-1] == ("gtk-launch", "firefox")
    r = await TOOLS["open_app"].run({"name": "nonexistent; rm -rf /"}, FakeHost())
    assert len(cmds) == 1 and "ไม่เจอ" in r.text
    await TOOLS["open_url"].run({"url": "file:///etc/passwd"}, FakeHost())
    assert len(cmds) == 1
    await TOOLS["open_url"].run({"url": "github.com"}, FakeHost())
    assert cmds[-1] == ("xdg-open", "https://github.com")
    await TOOLS["web_search"].run({"query": "ต้มยำกุ้ง & ข้าว"}, FakeHost())
    assert cmds[-1][0] == "xdg-open" and cmds[-1][1].startswith("https://duckduckgo.com/?q=%E0%B8%95")
    assert " " not in cmds[-1][1] and "&" not in cmds[-1][1].split("q=")[1]


async def test_failed_launch_is_reported(monkeypatch):
    monkeypatch.setattr(tools, "PLATFORM", "linux")
    async def fail(*a, **k):
        return 1

    monkeypatch.setattr(tools, "run_cmd", fail)
    monkeypatch.setattr(tools, "app_index", AppIndex(apps=[App("firefox", "Firefox", ("firefox",))]))
    assert "ไม่สำเร็จ" in (await TOOLS["open_app"].run({"name": "firefox"}, FakeHost())).text


def test_only_side_effect_free_tools_skip_confirmation():
    assert {n for n, t in TOOLS.items() if not t.confirm} == {"get_time", "set_timer", "cancel_timers", "media_control"}


# ---- session: routing, confirmation dialogue, timers ----------------------------------------


class Rec:
    def __init__(self):
        self.msgs, self.audio = [], []

    async def send(self, m):
        self.msgs.append(m)

    async def send_audio(self, b):
        self.audio.append(b)

    def of(self, kind):
        return [m for m in self.msgs if m["type"] == kind]

    def said(self):
        return [m["text"] for m in self.of("reply")]


class StubTts:
    async def synth(self, text):
        return b"A:" + text.encode()


class StubLlm:
    def __init__(self, call=None, reply="[happy] สวัสดีค่ะ"):
        self.call, self.reply, self.streamed = call, reply, 0

    async def route(self, text):
        return self.call

    async def stream(self, messages):
        self.streamed += 1
        yield self.reply


def make(llm):
    rec = Rec()
    s = Session(None, None, llm, StubTts(), rec.send, rec.send_audio)
    return s, rec


async def settle(s):
    for _ in range(5):
        await asyncio.sleep(0.01)
        await asyncio.gather(*[t for t in (s._respond_task, *s._bg) if t and not t.done()], return_exceptions=True)


async def test_safe_tool_runs_immediately_without_chat(monkeypatch):
    llm = StubLlm(ToolCall("get_time", {}))
    s, rec = make(llm)
    monkeypatch.setattr(tools, "now", lambda: dt.datetime(2026, 1, 2, 9, 30))
    s.say_to_llm("กี่โมงแล้ว")
    await settle(s)
    assert "9 นาฬิกา 30 นาที" in rec.said()[0]
    assert llm.streamed == 0 and not rec.of("confirm") and s.pending is None


async def test_confirmed_action_runs_only_after_yes(cmds, monkeypatch):
    monkeypatch.setattr(tools, "app_index", AppIndex(apps=[App("discord", "Discord", ("discord",))]))
    s, rec = make(StubLlm(ToolCall("open_app", {"name": "discord"})))
    s.say_to_llm("เปิดดิสคอร์ด")
    await settle(s)
    assert cmds == []  # nothing launched yet
    assert rec.of("confirm")[0]["text"] == "จะเปิดโปรแกรม discord ใช่ไหมคะ" and s.pending
    assert rec.said() == ["จะเปิดโปรแกรม discord ใช่ไหมคะ"]
    s.say_to_llm("ได้เลย")
    await settle(s)
    assert cmds == [("gtk-launch", "discord")]
    assert "เปิด Discord ให้แล้วค่ะ" in rec.said()[-1]
    assert rec.of("confirm_done") and s.pending is None


async def test_no_cancels_and_nothing_runs(cmds):
    s, rec = make(StubLlm(ToolCall("set_volume", {"percent": 90})))
    s.say_to_llm("ปรับเสียงเก้าสิบ")
    await settle(s)
    s.say_to_llm("ไม่เอา")
    await settle(s)
    assert cmds == [] and rec.said()[-1] == "ยกเลิกแล้วค่ะ" and s.pending is None


async def test_button_confirm_and_wrong_id_ignored(cmds):
    s, rec = make(StubLlm(ToolCall("set_volume", {"percent": 40})))
    s.say_to_llm("ปรับเสียง")
    await settle(s)
    s.confirm_reply(999, True)  # stale button from an old dialog
    await settle(s)
    assert cmds == [] and s.pending
    s.confirm_reply(rec.of("confirm")[0]["id"], True)
    await settle(s)
    assert cmds[-1][-1] == "0.40"


async def test_unrelated_reply_drops_pending_and_chats_normally(cmds):
    llm = StubLlm(ToolCall("open_app", {"name": "x"}))
    s, rec = make(llm)
    s.say_to_llm("เปิดแอป")
    await settle(s)
    llm.call = None
    s.say_to_llm("วันนี้อากาศดีจังเลยนะ")  # not yes/no
    await settle(s)
    assert cmds == [] and s.pending is None and llm.streamed == 1
    assert rec.of("confirm_done")


async def test_expired_confirmation_is_not_executed(cmds, monkeypatch):
    s, rec = make(StubLlm(ToolCall("set_volume", {"percent": 40})))
    s.say_to_llm("ปรับเสียง")
    await settle(s)
    s.pending.expires = 0  # long ago
    s.say_to_llm("ได้")
    await settle(s)
    assert cmds == []


async def test_unknown_tool_and_router_failure_are_handled():
    s, rec = make(StubLlm(ToolCall("format_disk", {"dev": "/dev/sda"})))
    s.say_to_llm("เปิดอะไรก็ได้")
    await settle(s)
    assert rec.said() == ["ขอโทษค่ะ มิ้นท์ทำสิ่งนั้นไม่ได้"]

    class Broken(StubLlm):
        async def route(self, text):
            raise RuntimeError("ollama down")

    s2, rec2 = make(Broken())
    s2.say_to_llm("เปิดเพลงหน่อย")
    await settle(s2)
    assert rec2.said() == ["สวัสดีค่ะ"]  # falls back to plain chat


async def test_timer_fires_announcement_and_cancels():
    s, rec = make(StubLlm())
    s.start_timer(0.05, "มาม่า")
    await asyncio.sleep(0.2)
    assert rec.said() == ["ครบเวลา มาม่าแล้วค่ะ"] and rec.audio
    s.start_timer(5, "")
    assert s.cancel_timers() == 1 and not s._timers


async def test_reply_and_audio_stay_adjacent_under_concurrency():
    s, rec = make(StubLlm())
    order = []

    async def send(m):
        order.append(m["type"])
        await asyncio.sleep(0.01)

    async def send_audio(b):
        order.append("audio")
        await asyncio.sleep(0.01)

    s.send, s.send_audio = send, send_audio
    await asyncio.gather(*(s.announce(f"ข้อความ {i}") for i in range(5)))
    assert order == ["reply", "audio"] * 5


@pytest.mark.parametrize(
    "text",
    ["เปิดไฟร์ฟอกซ์หน่อย", "เปิดดิสคอร์ดให้หน่อยสิ", "ช่วยเปิดเทอร์มินัลที", "ตั้งเวลาห้านาที", "ตั้งนาฬิกาปลุกอีก 10 นาที ต้มมาม่า",
     "ยกเลิกตัวจับเวลาที", "ตอนนี้กี่โมงแล้ว", "วันนี้วันอะไร", "ปรับเสียงเหลือสามสิบเปอร์เซ็นต์", "เพลงถัดไป",
     "หยุดเพลงก่อน", "ค้นหาสูตรต้มยำกุ้งให้หน่อย", "เปิดเว็บ github.com", "ข้ามเพลงนี้", "ย้อนกลับไปเพลงก่อนหน้า",
     "เสียงดังไปหน่อย", "Open firefox", "ช่วยหาข้อมูลเรื่องแมวให้หน่อย"],
)
def test_every_command_phrase_reaches_the_router(text):
    assert tools.looks_like_command(text)


@pytest.mark.parametrize(
    "text",
    ["สวัสดีมิ้นท์ วันนี้เป็นไงบ้าง", "ฉันเหนื่อยจังเลย งานเยอะมาก", "เธอชอบกินอะไรเหรอ", "ฉันสอบผ่านแล้ว", "อากาศร้อนจังเลยนะ",
     "เล่าเรื่องตลกให้ฟังหน่อย", "ขอบคุณนะมิ้นท์"],
)
def test_plain_chat_skips_the_router(text):
    assert not tools.looks_like_command(text)


async def test_plain_chat_never_calls_the_router():
    class Spy(StubLlm):
        async def route(self, text):
            raise AssertionError("router must not run for small talk")

    s, rec = make(Spy())
    s.say_to_llm("วันนี้อากาศดีจังเลยนะ")
    await settle(s)
    assert rec.said() == ["สวัสดีค่ะ"]


async def test_stt_gets_a_yes_no_hint_only_while_a_confirmation_is_pending():
    import struct


    seen = []

    class Stt:
        def transcribe(self, pcm, hint=None):
            seen.append(hint)
            return "ไม่เอา"

    rec = Rec()
    s = Session(None, Stt(), StubLlm(ToolCall("set_volume", {"percent": 40})), StubTts(), rec.send, rec.send_audio)
    pcm = struct.pack("<512h", *([1000] * 512))
    await s._transcribe(pcm, 0.0)  # nothing pending
    s.say_to_llm("ปรับเสียงหน่อย")
    await settle(s)
    assert s.pending
    await s._transcribe(pcm, 0.0)  # now waiting for yes/no
    await settle(s)
    assert seen[0] is None and "ไม่เอา" in seen[1] and "ได้" in seen[1]
    assert s.pending is None  # "ไม่เอา" was understood and cancelled it


# ---- Windows / platform dispatch (cannot launch real apps here: we check what would be called) -----


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(tools, "PLATFORM", "win32")
    started, keys, vols = [], [], []
    monkeypatch.setattr(tools.os, "startfile", lambda t: started.append(t), raising=False)
    monkeypatch.setattr(tools, "_win_media_key", lambda a: keys.append(a) or 0)
    monkeypatch.setattr(tools, "_win_set_volume", lambda p: vols.append(p) or 0)

    async def no_posix_commands(*a, **k):
        raise AssertionError(f"Windows must not shell out to {a[0]}")

    monkeypatch.setattr(tools, "run_cmd", no_posix_commands)
    return started, keys, vols


async def test_windows_urls_media_and_volume_use_native_calls(win):
    started, keys, vols = win
    await TOOLS["open_url"].run({"url": "github.com"}, FakeHost())
    await TOOLS["web_search"].run({"query": "แมว"}, FakeHost())
    assert started[0] == "https://github.com" and started[1].startswith("https://duckduckgo.com/?q=")
    await TOOLS["media_control"].run({"action": "next"}, FakeHost())
    assert keys == ["next"]
    await TOOLS["set_volume"].run({"percent": 35}, FakeHost())
    assert vols == [35]
    await TOOLS["open_url"].run({"url": "file:///C:/Windows/System32/cmd.exe"}, FakeHost())
    assert len(started) == 2  # validation still blocks non-http(s) targets on Windows


async def test_windows_start_menu_apps(win, tmp_path, monkeypatch):
    started, _, _ = win
    (tmp_path / "Mozilla Firefox.lnk").write_text("")
    (tmp_path / "Uninstall Firefox.lnk").write_text("")
    (tmp_path / "Sub").mkdir()
    (tmp_path / "Sub" / "Discord.lnk").write_text("")
    idx = tools.AppIndex(dirs=[tmp_path])
    assert sorted(a.name for a in idx.apps) == ["Discord", "Mozilla Firefox"]  # uninstallers skipped, subfolders scanned
    monkeypatch.setattr(tools, "app_index", idx)
    r = await TOOLS["open_app"].run({"name": "firefox"}, FakeHost())
    assert "Mozilla Firefox" in r.text and started == [str(tmp_path / "Mozilla Firefox.lnk")]


async def test_windows_startfile_failure_is_reported(monkeypatch):
    monkeypatch.setattr(tools, "PLATFORM", "win32")

    def boom(_):
        raise OSError("no association")

    monkeypatch.setattr(tools.os, "startfile", boom, raising=False)
    assert "ไม่สำเร็จ" in (await TOOLS["open_url"].run({"url": "https://example.com"}, FakeHost())).text


def test_default_app_dirs_follow_the_platform(monkeypatch):
    monkeypatch.setattr(tools, "PLATFORM", "win32")
    monkeypatch.setenv("APPDATA", "C:/Users/x/AppData/Roaming")
    monkeypatch.setenv("ProgramData", "C:/ProgramData")
    assert all("Start Menu" in str(d) for d in tools.default_app_dirs()) and len(tools.default_app_dirs()) == 2
    monkeypatch.setattr(tools, "PLATFORM", "linux")
    assert tools.default_app_dirs() == tools.APP_DIRS


def test_unsupported_platforms_do_not_offer_os_tools():
    assert set(tools.tools_for("linux")) == set(tools.tools_for("win32")) == set(TOOLS) | set()
    mac = set(tools.tools_for("darwin"))
    assert not mac & {"open_app", "media_control", "set_volume"} and {"get_time", "set_timer", "open_url"} <= mac
