"""Things the assistant may do on the user's machine.

Safety model: the LLM can only pick from this fixed registry. Arguments are validated, commands
are run as argument lists (never through a shell), apps are resolved against the installed
.desktop entries, and URLs must be http(s). Anything that touches the machine asks the user to
confirm first (see Tool.confirm); the session handles that dialogue.
"""
import asyncio
import datetime as dt
import logging
import os
import re
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlparse

log = logging.getLogger("mint.tools")

MAX_TIMER_S = 24 * 3600


@dataclass(frozen=True)
class Result:
    text: str  # what Mint says afterwards
    emotion: str = "neutral"


class Host(Protocol):
    """What tools need from the session."""

    def start_timer(self, seconds: float, label: str) -> None: ...
    def cancel_timers(self) -> int: ...


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    confirm: bool
    describe: Callable[[dict], str]  # Thai yes/no question shown and spoken before running
    run: Callable[[dict, Host], Awaitable[Result]]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


# ---- platform layer -------------------------------------------------------------------------
# Supported: Linux (xdg-open, gtk-launch, playerctl, wpctl) and Windows (ShellExecute, Start Menu,
# media keys, pycaw). Tools a platform cannot do are left out of the registry, so the model never
# offers them. Everything here is replaced/patched in tests.

PLATFORM = sys.platform  # "linux", "win32", ...


async def run_cmd(*argv: str, wait_s: float = 3.0) -> int:
    """Run a program without a shell. Returns its exit code (0 if still running after wait_s)."""
    extra: dict[str, Any] = {}
    if PLATFORM == "win32":  # launched apps outlive the backend, no console window
        extra["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        )
    else:
        extra["start_new_session"] = True
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        **extra,
    )
    try:
        return await asyncio.wait_for(proc.wait(), wait_s)
    except asyncio.TimeoutError:
        return 0


async def _startfile(target: str) -> int:
    """Windows ShellExecute: opens a URL with the default browser or launches a shortcut."""
    try:
        await asyncio.get_running_loop().run_in_executor(None, os.startfile, target)  # type: ignore[attr-defined]
        return 0
    except OSError:
        return 1


async def open_target(target: str) -> int:
    """Open an http(s) URL in the default browser. Callers must validate `target` first."""
    if PLATFORM == "win32":
        return await _startfile(target)
    return await run_cmd("open" if PLATFORM == "darwin" else "xdg-open", target)


async def launch_app(app: "App") -> int:
    if PLATFORM == "win32":
        return await _startfile(app.id)  # id is the path of the Start Menu shortcut
    return await run_cmd("gtk-launch", app.id)


# Windows media keys (virtual-key codes): no player discovery is possible, so these "succeed" even
# when nothing is playing.
_WIN_MEDIA_VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}


def _win_media_key(action: str) -> int:
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    vk = _WIN_MEDIA_VK[action]
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
    return 0


async def send_media_key(action: str) -> int:
    if PLATFORM == "win32":
        return await asyncio.get_running_loop().run_in_executor(None, _win_media_key, action)
    return await run_cmd("playerctl", *MEDIA[action])


def _win_set_volume(pct: int) -> int:
    """Master volume via pycaw (the `pycaw` package is installed on Windows only)."""
    try:
        from pycaw.pycaw import AudioUtilities

        speakers = AudioUtilities.GetSpeakers()
        endpoint = getattr(speakers, "EndpointVolume", None)
        if endpoint is None:  # older pycaw releases
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import IAudioEndpointVolume

            iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            endpoint = cast(iface, POINTER(IAudioEndpointVolume))
        endpoint.SetMasterVolumeLevelScalar(pct / 100, None)
        return 0
    except Exception:
        log.exception("setting volume failed")
        return 1


async def set_system_volume(pct: int) -> int:
    if PLATFORM == "win32":
        return await asyncio.get_running_loop().run_in_executor(None, _win_set_volume, pct)
    return await run_cmd("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{pct / 100:.2f}")


# ---- installed apps -------------------------------------------------------------------------

ALIASES = {
    "ไฟร์ฟอกซ์": "firefox",
    "ไฟล์ฟอกซ์": "firefox",
    "โครม": "chrome",
    "กูเกิลโครม": "chrome",
    "ดิสคอร์ด": "discord",
    "เทอร์มินัล": "terminal",
    "เทอมินัล": "terminal",
    "ไฟล์เมเนเจอร์": "dolphin",
    "จัดการไฟล์": "dolphin",
    "เครื่องคิดเลข": "calculator",
    "แอนดรอยด์สตูดิโอ": "android studio",
    "วิดีโอ": "mpv",
    "เล่นวิดีโอ": "mpv",
}

APP_DIRS = [  # Linux .desktop locations
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local/share/applications",
    Path.home() / ".local/share/flatpak/exports/share/applications",
]


def default_app_dirs() -> list[Path]:
    if PLATFORM == "win32":  # Start Menu shortcuts, all users + current user
        return [
            Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            for base in (os.environ.get("ProgramData"), os.environ.get("APPDATA"))
            if base
        ]
    return APP_DIRS


@dataclass(frozen=True)
class App:
    id: str  # Linux: desktop file id without ".desktop"; Windows: path of the .lnk shortcut
    name: str
    keys: tuple[str, ...]  # normalised searchable names


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_.]+", "", s.lower())


def parse_desktop(path: Path) -> App | None:
    fields: dict[str, str] = {}
    in_entry = False
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("["):
                in_entry = line == "[Desktop Entry]"
            elif in_entry and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                fields.setdefault(k.strip(), v.strip())
    except OSError:
        return None
    if fields.get("Type") != "Application" or fields.get("NoDisplay") == "true" or fields.get("Hidden") == "true":
        return None
    name = fields.get("Name")
    if not name:
        return None
    raw = [name, fields.get("Name[th]", ""), fields.get("GenericName", ""), path.stem.split(".")[-1]]
    raw += [k for k in fields.get("Keywords", "").split(";") if k]
    return App(path.stem, name, tuple(dict.fromkeys(_norm(r) for r in raw if r)))


_SKIP_SHORTCUT = re.compile(r"uninstall|readme|release notes|\bhelp\b|website|documentation|license", re.I)


def parse_lnk(path: Path) -> App | None:
    name = path.stem
    if _SKIP_SHORTCUT.search(name):
        return None
    return App(str(path), name, (_norm(name),))


class AppIndex:
    def __init__(self, dirs: list[Path] | None = None, apps: list[App] | None = None):
        self._dirs = dirs
        self._apps = apps

    @property
    def apps(self) -> list[App]:
        if self._apps is None:
            windows = PLATFORM == "win32"
            seen: dict[str, App] = {}
            for d in self._dirs if self._dirs is not None else default_app_dirs():
                if not d.is_dir():
                    continue
                files = sorted(d.rglob("*.lnk")) if windows else sorted(d.glob("*.desktop"))
                for p in files:
                    a = parse_lnk(p) if windows else parse_desktop(p)
                    key = _norm(a.name) if (a and windows) else (a.id if a else "")
                    if a and key not in seen:
                        seen[key] = a
            self._apps = list(seen.values())
        return self._apps

    def resolve(self, query: str) -> App | None:
        q = _norm(ALIASES.get(query.strip(), query))
        if len(q) < 2:
            return None
        best: tuple[float, App] | None = None
        for app in self.apps:
            for key in app.keys:
                if key == q:
                    score = 1.0
                elif len(q) >= 3 and (q in key or key in q) and len(key) >= 3:
                    score = 0.85 - 0.1 * abs(len(key) - len(q)) / max(len(key), len(q))
                else:
                    score = SequenceMatcher(None, q, key).ratio() * 0.8
                if best is None or score > best[0]:
                    best = (score, app)
        return best[1] if best and best[0] >= 0.62 else None


app_index = AppIndex()

# ---- handlers --------------------------------------------------------------------------------

THAI_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม",
               "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
THAI_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]


def now() -> dt.datetime:  # replaced in tests
    return dt.datetime.now()


async def get_time(args: dict, host: Host) -> Result:
    n = now()
    return Result(
        f"ตอนนี้เวลา {n.hour} นาฬิกา {n.minute} นาทีค่ะ วัน{THAI_DAYS[n.weekday()]}ที่ {n.day} {THAI_MONTHS[n.month - 1]}",
        "happy",
    )


def _num(v: Any, default: float = 0) -> float:
    """Models send numbers as ints, floats or strings; missing/garbage becomes `default`."""
    if v is None or v == "":
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f == f and abs(f) != float("inf") else default


async def set_timer(args: dict, host: Host) -> Result:
    seconds = _num(args.get("minutes"), 0) * 60 + _num(args.get("seconds"), 0)
    if seconds <= 0:
        return Result("จะให้ตั้งเวลากี่นาทีดีคะ", "worried")
    if seconds > MAX_TIMER_S:
        return Result("ตั้งเวลาได้นานสุดยี่สิบสี่ชั่วโมงค่ะ", "worried")
    label = str(args.get("label") or "").strip()[:60]
    host.start_timer(seconds, label)
    m, s = divmod(int(round(seconds)), 60)
    spoken = (f"{m} นาที" if m else "") + (f" {s} วินาที" if s else "")
    return Result(f"ตั้งเวลา {spoken.strip()}ให้แล้วค่ะ", "happy")


async def cancel_timers(args: dict, host: Host) -> Result:
    n = host.cancel_timers()
    return Result("ยกเลิกตัวจับเวลาให้แล้วค่ะ" if n else "ตอนนี้ไม่มีตัวจับเวลาที่ตั้งไว้ค่ะ", "neutral")


MEDIA = {"play_pause": ["play-pause"], "next": ["next"], "previous": ["previous"], "stop": ["stop"]}
MEDIA_SPOKEN = {"play_pause": "เล่นหรือหยุดเพลงให้แล้วค่ะ", "next": "ข้ามไปเพลงถัดไปแล้วค่ะ",
                "previous": "ย้อนไปเพลงก่อนหน้าแล้วค่ะ", "stop": "หยุดเพลงแล้วค่ะ"}


async def media_control(args: dict, host: Host) -> Result:
    action = str(args.get("action", ""))
    if action not in MEDIA:
        return Result("ไม่แน่ใจว่าจะให้ทำอะไรกับเพลงค่ะ", "worried")
    if await send_media_key(action) != 0:
        return Result("ไม่พบโปรแกรมเล่นเพลงที่เปิดอยู่ค่ะ", "worried")
    return Result(MEDIA_SPOKEN[action], "happy")


async def open_app(args: dict, host: Host) -> Result:
    query = str(args.get("name", "")).strip()
    app = app_index.resolve(query)
    if not app:
        return Result(f"หาแอป {query} ในเครื่องไม่เจอค่ะ", "worried")
    if await launch_app(app) != 0:
        return Result(f"เปิด {app.name} ไม่สำเร็จค่ะ", "sad")
    return Result(f"เปิด {app.name} ให้แล้วค่ะ", "happy")


def normalize_url(raw: str) -> str | None:
    raw = raw.strip()
    if not raw or re.search(r"\s", raw):
        return None
    if "://" not in raw:
        if not re.fullmatch(r"[\w\-]+(\.[\w\-]+)+(/\S*)?", raw):
            return None
        raw = "https://" + raw
    u = urlparse(raw)
    if u.scheme not in ("http", "https") or not u.netloc or u.username or u.password:
        return None
    return raw


async def open_url(args: dict, host: Host) -> Result:
    url = normalize_url(str(args.get("url", "")))
    if not url:
        return Result("ลิงก์นี้เปิดไม่ได้ค่ะ ต้องเป็นเว็บที่ขึ้นต้นด้วย http หรือ https", "worried")
    if await open_target(url) != 0:
        return Result("เปิดเว็บไม่สำเร็จค่ะ", "sad")
    return Result("เปิดเว็บให้แล้วค่ะ", "happy")


def search_url(query: str) -> str:
    return "https://duckduckgo.com/?q=" + quote(query.strip())


async def web_search(args: dict, host: Host) -> Result:
    q = str(args.get("query", "")).strip()
    if not q:
        return Result("จะให้ค้นหาอะไรดีคะ", "worried")
    if await open_target(search_url(q)) != 0:
        return Result("เปิดเบราว์เซอร์ไม่สำเร็จค่ะ", "sad")
    return Result(f"ค้นหา {q} ให้แล้วค่ะ", "happy")


async def set_volume(args: dict, host: Host) -> Result:
    if _num(args.get("percent"), -1) < 0:
        return Result("จะให้ปรับเสียงเป็นเท่าไหร่ดีคะ", "worried")
    pct = max(0, min(100, int(round(_num(args.get("percent"))))))
    if await set_system_volume(pct) != 0:
        return Result("ปรับเสียงไม่สำเร็จค่ะ", "sad")
    return Result(f"ปรับเสียงเป็น {pct} เปอร์เซ็นต์แล้วค่ะ", "happy")


# ---- registry --------------------------------------------------------------------------------


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


_ALL_TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("get_time", "บอกเวลาและวันที่ปัจจุบัน", _obj({}), False, lambda a: "", get_time),
        Tool(
            "set_timer",
            "ตั้งเวลานับถอยหลัง พอครบจะเตือนด้วยเสียง",
            _obj({"minutes": {"type": "number", "description": "จำนวนนาที"},
                  "seconds": {"type": "number", "description": "จำนวนวินาที"},
                  "label": {"type": "string", "description": "ชื่อ/เหตุผลของการตั้งเวลา"}}),
            False, lambda a: "", set_timer,
        ),
        Tool("cancel_timers", "ยกเลิกตัวจับเวลาทั้งหมด", _obj({}), False, lambda a: "", cancel_timers),
        Tool(
            "media_control",
            "ควบคุมโปรแกรมเล่นเพลง/วิดีโอที่เปิดอยู่",
            _obj({"action": {"type": "string", "enum": list(MEDIA), "description": "play_pause=เล่น/หยุดชั่วคราว"}},
                 ["action"]),
            False, lambda a: "", media_control,
        ),
        Tool(
            "open_app",
            "Open/launch an installed program. Use for เปิด + program name (firefox, discord, terminal/เทอร์มินัล, files, calculator...)",
            _obj({"name": {"type": "string", "description": "program name in English if known, e.g. firefox, discord, terminal, kitty"}}, ["name"]),
            True, lambda a: f"จะเปิดโปรแกรม {a.get('name', '')} ใช่ไหมคะ", open_app,
        ),
        Tool(
            "open_url",
            "เปิดเว็บไซต์ตามลิงก์ในเบราว์เซอร์",
            _obj({"url": {"type": "string", "description": "ที่อยู่เว็บ"}}, ["url"]),
            True, lambda a: f"จะเปิดเว็บ {a.get('url', '')} ใช่ไหมคะ", open_url,
        ),
        Tool(
            "web_search",
            "Search the web in the browser. Use when the user says ค้นหา / หา / ค้น / เสิร์ช / google something",
            _obj({"query": {"type": "string", "description": "คำค้นหา"}}, ["query"]),
            True, lambda a: f"จะค้นหา {a.get('query', '')} ในเบราว์เซอร์ใช่ไหมคะ", web_search,
        ),
        Tool(
            "set_volume",
            "ตั้งระดับเสียงลำโพงของเครื่อง",
            _obj({"percent": {"type": "number", "description": "0 ถึง 100"}}, ["percent"]),
            True, lambda a: f"จะปรับเสียงเป็น {a.get('percent', '')} เปอร์เซ็นต์ใช่ไหมคะ", set_volume,
        ),
    ]
}

# These need OS integration that only exists for Linux and Windows; elsewhere the model never sees them.
_NEEDS_OS_SUPPORT = {"open_app", "media_control", "set_volume"}


def tools_for(platform: str) -> dict[str, Tool]:
    supported = platform in ("linux", "win32")
    return {n: t for n, t in _ALL_TOOLS.items() if supported or n not in _NEEDS_OS_SUPPORT}


TOOLS = tools_for(PLATFORM)
TOOL_SCHEMAS = [t.schema() for t in TOOLS.values()]

# ---- yes / no ------------------------------------------------------------------------------
# Deliberately strict: a wrong "yes" runs something on the machine, a wrong "no"/"unclear" only
# makes the user repeat themselves. So only short, answer-shaped replies count as yes.

_PARTICLES = re.compile(r"(ครับผม|ค่ะ|คะ|ครับ|จ้ะ|จ้า|นะ|[\s!.,?]+)")
_YES_WORDS = {
    "ใช่", "ใช่แล้ว", "ได้", "ได้เลย", "ตกลง", "โอเค", "โอเคเลย", "เอา", "เอาเลย", "เปิดเลย", "ทำเลย",
    "จัดไป", "ยืนยัน", "อืม", "อือ", "ok", "okay", "yes", "yeah", "yep", "sure", "ได้เลยจ้า",
}
_NO_START = re.compile(r"^(ไม่|อย่า|ยกเลิก|เลิก|หยุด|no\b|cancel|stop|nope)", re.I)
_BARE_POLITE = re.compile(r"^(ค่ะ|คะ|ครับ|จ้ะ|จ้า|ครับผม)[\s!.]*$")


def classify_confirmation(text: str) -> bool | None:
    """True = yes, False = no, None = unclear (treated as a new request, never as consent)."""
    t = text.strip().lower()
    if not t or len(t) > 24:
        return None
    if _NO_START.match(t):
        return False
    if _BARE_POLITE.match(t):
        return True
    return True if _PARTICLES.sub("", t) in _YES_WORDS else None


# ---- cheap pre-filter so ordinary chat skips the router call (~0.45 s) ------------------------
# Deliberately generous: a false positive only costs the router call, a false negative would turn
# a command into small talk. Every phrase our tools need is covered by at least one of these.
_COMMAND_HINTS = re.compile(
    "|".join([
        "เปิด", "ปิด", "ตั้ง", "ยกเลิก", "เลิก", "จับเวลา", "นาฬิกา", "นับถอยหลัง", "กี่โมง", "เวลา",
        "วันอะไร", "วันที่", "ค้น", "หา", "เสิร์ช", "เว็บ", "ลิงก์", "ลิงค์", "เสียง", "ดังขึ้น", "เบาลง",
        "เพลง", "ถัดไป", "ต่อไป", "ย้อน", "ข้าม", "หยุด", "เล่น", "พัก", "volume", "timer", "open", "search",
        "google", "http", r"\.com",
    ]),
    re.I,
)


def looks_like_command(text: str) -> bool:
    return bool(_COMMAND_HINTS.search(text))
