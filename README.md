# Mint — ผู้ช่วย AI เสียง real-time พร้อมตัวละคร Live2D

คุยด้วยเสียงภาษาไทยกับตัวละคร Live2D บนเดสก์ท็อป ประมวลผลบนเครื่องเกือบทั้งหมด (CPU ล้วน)

```
ไมค์ → VAD (Silero) → STT (faster-whisper) → LLM (Ollama, stream) → TTS (edge-tts) → เสียง + ปากขยับ + อารมณ์
```

![CI](../../actions/workflows/ci.yml/badge.svg)

## Handoff สำหรับ AI / ผู้พัฒนาต่อ

ส่วนนี้เขียนให้ AI ตัวอื่น (หรือคนใหม่) อ่านแล้วทำงานต่อได้ทันที ส่วนที่เหลือของไฟล์เป็นเอกสารสำหรับผู้ใช้

### อ่านก่อนลงมือ
- **อย่าเชื่อว่าไฟล์ทุกไฟล์สมบูรณ์** `app/electron/main.mjs` กับ `app/scripts/mint-ctl.sh` เคยว่างเปล่า (0 ไบต์) ตอน push ครั้งแรก แล้วถูกกู้คืนจากบันทึกเซสชัน ก่อนทำอะไรให้เช็กว่าสองไฟล์นี้มีเนื้อหา (`wc -c`) ถ้าเจอว่างอีกให้แจ้งผู้ใช้ อย่าเขียนทับเอง
- ผู้ใช้สื่อสารเป็นภาษาไทย ตัวละครชื่อ "มิ้นท์" พูดไทยลงท้าย ค่ะ/นะคะ ข้อความที่พูดกับผู้ใช้และคอมเมนต์ต้นฉบับบางส่วนเป็นไทย ให้คงสไตล์เดิม
- ข้อความ prompt ของ LLM, ชื่อ tool และแท็กอารมณ์เป็นของที่ผ่านการวัดผลมาแล้ว อย่าแก้โดยไม่รัน `backend/scripts/bench_*.py` เทียบก่อน-หลัง

### สถานะปัจจุบัน (ตรวจเมื่อ 2026-11-09)
| ตรวจ | ผล |
|---|---|
| `cd backend && uv run pytest -q` | 105 passed |
| `uv run ruff check .` | ผ่าน |
| `cd app && npm run typecheck` | ผ่าน |
| `node --check app/electron/main.mjs` | ผ่าน |
| รันแอปจริงบน Linux (Hyprland/Wayland) | เคยใช้งานได้ ไม่ได้รันซ้ำหลังกู้ไฟล์ |
| รันบน Windows จริง | **ยังไม่เคย** (CI ผ่านอย่างเดียว) |

ฟีเจอร์ที่ทำแล้ว: ฟัง/ตอบด้วยเสียงไทย, พูดแทรก (barge-in), อารมณ์ตัวละครจากแท็กใน LLM, เครื่องมือสั่งงาน 8 ตัวพร้อมระบบยืนยัน, ซ่อน/แสดงหน้าต่าง + tray, `mint-ctl`, ตัวจับเวลา

### สถาปัตยกรรม
Electron (renderer = Vite + TypeScript + PixiJS/Live2D) คุยกับ backend (FastAPI) ผ่าน WebSocket `ws://127.0.0.1:8765/ws` หนึ่งการเชื่อมต่อ = หนึ่ง `Session` Electron main เป็นคนสตาร์ทและดูแล backend (รีสตาร์ทเมื่อล้ม)

**Client → server**
- binary: PCM int16 mono 16 kHz (ไมค์ ส่งเป็นเฟรม แล้ว server ตัดเป็นเฟรมละ 1024 ไบต์ = 512 samples)
- JSON: `{"type":"ping"}`, `{"type":"playback","playing":bool}` (บอกว่าเสียงตัวละครกำลังดัง เพื่อให้ barge-in เข้มขึ้น), `{"type":"confirm_reply","id":n,"ok":bool}`, `{"type":"user_text","text":"..."}`

**Server → client** (ชนิดอยู่ใน `app/src/ws.ts` `ServerEvent`)
- JSON: `state` (idle/listening/thinking/speaking), `transcript`, `reply` (`text`, `emotion`, `audio: bool`), `interrupt`, `metrics`, `confirm`, `confirm_done`, `error`, `pong`
- binary: เสียง TTS **ต้องตามหลังข้อความ `reply` ที่มี `audio:true` ทันที** (ล็อกด้วย `_send_lock` ใน `session.py`) ห้ามแทรกข้อความอื่นระหว่างคู่นี้

**ลำดับใน backend** (`backend/mint/`)
| ไฟล์ | หน้าที่ |
|---|---|
| `server.py` | FastAPI, `/health`, `/ws`, `Deps` (สลับของจริงเป็นตัวจำลองในเทสต์ได้) |
| `session.py` | หัวใจ: รับเสียง → endpointer → STT → (route เครื่องมือ หรือ stream LLM) → chunk เป็นประโยค → TTS ขนานแต่ส่งตามลำดับ, ยกเลิกคำตอบเก่าเมื่อผู้ใช้พูดใหม่, จัดการ confirm/ตัวจับเวลา |
| `endpointing.py` | แปลงความน่าจะเป็นของ VAD เป็นช่วงคำพูด (Start/End/Discard) มี pre-roll และเกณฑ์ที่เข้มขึ้นตอน barge-in |
| `vad.py`, `stt.py`, `llm.py`, `tts.py` | Silero VAD, faster-whisper, Ollama, edge-tts |
| `chunker.py` | แยกสตรีมโทเค็นเป็นประโยค + ดึงแท็ก `[emotion]` |
| `tools.py` | เครื่องมือ, schema, platform layer (Linux/Windows), `classify_confirmation`, `looks_like_command` |
| `config.py` | ค่า env ทั้งหมด (ดูตารางด้านล่าง) |

**ฝั่ง app:** `app/electron/main.mjs` (หน้าต่าง, tray, ดูแล backend, รับคำสั่ง `--toggle/--show/--hide/--quit` จากอินสแตนซ์ที่สอง), `app/src/main.ts` (จัดการ event ทั้งหมด), `audio/mic.ts` + `public/mic-worklet.js` (จับเสียง), `audio/player.ts` (เล่นเสียง + ปากขยับ), `live2d/` (โมเดล, อารมณ์)

### การตัดสินใจออกแบบที่ไม่ชัดจากโค้ด
- **Tool routing แยกเป็นการเรียก LLM สั้นๆ ก่อน** (`Llm.route`) เพราะ persona ยาวที่บังคับติดแท็กอารมณ์ทำให้ qwen2.5:3b เลิกเรียก tool เลย `looks_like_command` กรองประโยคคุยเล่นออกก่อนเพื่อประหยัด ~0.45 วินาที
- **Tool ที่กระทบเครื่อง (`open_app`, `open_url`, `web_search`, `set_volume`) ต้องยืนยันด้วยเสียงหรือปุ่ม** ถ้าตอบไม่ชัดถือว่า "ไม่" และหมดอายุใน 60 วินาที ขณะรอยืนยัน STT ถูกใส่ hint คำตอบ (`CONFIRM_HINT`) ห้ามทำให้ tool ใหม่ที่มีผลข้างเคียงข้ามขั้นนี้
- **AI ไม่มีทางรัน shell** เลือกได้แค่ tool ใน `_ALL_TOOLS` ชื่อแอปต้องตรงกับที่ติดตั้ง URL ต้อง http(s) ค่าตัวเลขถูกจำกัดช่วง ห้ามเพิ่ม tool แบบรันคำสั่งอิสระ
- **TTS ใช้ hedged request** (`MINT_TTS_HEDGE_S`) เพราะ edge-tts ล้ม/ช้าเป็นระยะ และสังเคราะห์ทีละประโยคขนานกันแต่ส่งตามลำดับ
- **ตัวจับเวลาผูกกับ Session** ปิดแอปหรือ backend รีสตาร์ทแล้วหาย (ยังไม่เก็บถาวร)
- **ซ่อนหน้าต่าง = ไมค์พัก** ยังไม่มี wake word จึงไม่ฟังเบื้องหลัง
- **`--no-sandbox` เฉพาะ Linux** (chrome-sandbox ไม่เป็น SUID) Windows/macOS เปิด sandbox ตามปกติ
- `LLM threads = 8` มาจากการวัดบนเครื่องผู้พัฒนา (14 คอร์ตรรกะ) อย่าถือเป็นค่าที่ดีที่สุดสำหรับเครื่องอื่น

### งานที่ยังค้าง / ไอเดียต่อ (เรียงตามความคุ้ม)
1. ทดสอบบน Windows จริง (ไมค์/ลำโพง, `pycaw` ของ `set_volume`, `mint-ctl.cmd`, tray) แล้วอัปเดตตาราง "สถานะแพลตฟอร์ม"
2. เสียงสำรองออฟไลน์เมื่อ edge-tts ใช้ไม่ได้ (ตอนนี้เหลือซับไตเติลอย่างเดียว)
3. Wake word เพื่อให้ฟังเบื้องหลังตอนซ่อนหน้าต่างได้
4. เก็บตัวจับเวลาให้อยู่รอดหลังรีสตาร์ท
5. ทำให้พอร์ต backend ตั้งค่าได้ฝั่ง app (ตอนนี้ `MINT_PORT` เปลี่ยนได้ แต่ app ยังผูก 8765)
6. ลองโมเดล LLM ใหญ่กว่า 3B หรือ routing ที่แม่นขึ้น (ดู `bench_tools.py` เป็นเกณฑ์วัด)
7. ใส่ไฟล์ LICENSE (repo เป็น public แต่ยังไม่มี)

### ข้อควรระวังเวลาแก้
- ถ้าเปลี่ยนโปรโตคอล WebSocket ให้แก้ทั้ง `session.py`/`server.py`, `app/src/ws.ts` และ `app/src/main.ts` พร้อมกัน แล้วเพิ่มเทสต์ใน `backend/tests/test_server.py`
- โค้ดที่ขึ้นกับ OS ให้อยู่ใน platform layer ของ `tools.py` และ `main.mjs` เท่านั้น แล้วทำให้เทสต์รันได้บนทั้ง Linux และ Windows (CI รันทั้งคู่)
- เทสต์ต้องไม่พึ่ง Ollama/ไมค์/เน็ต ใช้ตัวจำลองผ่าน `Deps` เหมือนเดิม
- อย่า commit: โมเดล Live2D, `app/public/lib/` (Cubism Core), `.env*`, `*.local` (อยู่ใน `.gitignore` แล้ว)
- ก่อนบอกว่าเสร็จ ให้รันชุดตรวจในตารางสถานะด้านบนทั้งหมด

## สถานะแพลตฟอร์ม

| | Linux | Windows |
|---|---|---|
| Backend (เสียง → LLM → เสียง) | ทดสอบใช้งานจริงแล้ว | เทสต์อัตโนมัติผ่านใน CI, **ยังไม่เคยรันกับไมค์/ลำโพงจริง** |
| แอป Electron + Live2D | ทดสอบใช้งานจริงแล้ว (Hyprland/Wayland) | build ผ่านใน CI, **ยังไม่เคยเปิดหน้าต่างจริง** |
| เครื่องมือสั่งงาน (เปิดแอป/เว็บ, เพลง, เสียง) | ทดสอบแล้ว | เขียนไว้แล้วแต่**ยังไม่ได้ทดสอบบน Windows จริง** (โดยเฉพาะ `set_volume` ผ่าน `pycaw`) |
| macOS | — | ไม่รองรับ (เครื่องมือที่ผูกกับระบบถูกซ่อน) |

ถ้าเจอปัญหาบน Windows แจ้งเป็น issue ได้เลย

## ความเป็นส่วนตัว
- เสียงของคุณ **ไม่ถูกส่งออกจากเครื่อง** (VAD, Whisper, LLM รันในเครื่อง)
- **ข้อความที่ตัวละครจะพูด** ถูกส่งไปที่บริการอ่านออกเสียงของ Microsoft ผ่าน `edge-tts` (ฟรี ไม่ต้องมี key) ถ้าเน็ตหลุดจะเหลือแค่ซับไตเติล ไม่มีเสียง

## ติดตั้ง

ต้องมี: Python ≥ 3.12 + [`uv`](https://docs.astral.sh/uv/), Node ≥ 20 + npm, [Ollama](https://ollama.com) (มีตัวติดตั้ง Windows), `ffmpeg` (ใช้เฉพาะสคริปต์ทดสอบใน `backend/scripts`)

**ทางลัด** (ติดตั้ง dependency ของ backend/app และดาวน์โหลด Cubism Core):

```bash
./scripts/setup.sh          # Linux / macOS
```
```powershell
.\scripts\setup.ps1         # Windows (PowerShell)
```

**หรือทำเอง:**

```bash
cd backend && uv sync                      # backend
cd ../app && npm install                   # app
node scripts/fetch-cubism-core.mjs         # Live2D Cubism Core (license ของ Live2D)
ollama pull qwen2.5:3b                     # LLM ประมาณ 2 GB
```

สิ่งที่**ไม่อยู่ใน repo** และต้องมีเอง:
- **Live2D Cubism Core:** `fetch-cubism-core.mjs` ดาวน์โหลดจากเว็บ Live2D ให้ ซึ่งอยู่ภายใต้ [license ของ Live2D](https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html)
- **โมเดล Live2D:** เป็นผลงานของผู้สร้างแต่ละคน ต้องหามาเอง วิธีวางดู [app/public/models/README.md](app/public/models/README.md)
- **Whisper `small`** (ประมาณ 480 MB) ดาวน์โหลดอัตโนมัติจาก Hugging Face ตอนรันครั้งแรก หลังจากนั้นใช้จากแคชโดยไม่แตะเน็ต

**ถ้า `npm install` ไม่โหลดตัว Electron** (npm บางเวอร์ชันบล็อก install script) รัน `node node_modules/electron/install.js`

### Windows: ข้อควรรู้
- ติดตั้ง `uv` (`winget install astral-sh.uv`), Node.js และ Ollama ก่อน แล้วรัน `.\scripts\setup.ps1`
- ไมค์: เปิดสิทธิ์ใน Settings → Privacy & security → Microphone (รวมถึง "Let desktop apps access your microphone")
- ปุ่มเปิด/ซ่อนจากภายนอกใช้ `app\scripts\mint-ctl.cmd` (ดูหัวข้อซ่อน-แสดง) ผูกกับปุ่มลัดของ Windows ได้ผ่าน shortcut
- เปิดเว็บ/แอปใช้ ShellExecute และรายการแอปมาจากชอร์ตคัต Start Menu (ไม่ใช่ทุกแอปที่ติดตั้งแบบ portable จะอยู่ในรายการ)
- ปุ่มเพลง (เล่น/หยุด/ถัดไป) ส่งปุ่ม media ของระบบ Windows ไม่รู้ว่ามีเครื่องเล่นเปิดอยู่หรือไม่ จึงตอบสำเร็จเสมอ

## รัน

```bash
cd app && npm run dev
```

Electron จะเปิด backend ให้เอง (รีสตาร์ทอัตโนมัติถ้าล้ม และปิดให้ตอนออก)

| ปุ่ม | ทำอะไร |
|---|---|
| `m` หรือปุ่ม mute | ปิด/เปิดไมค์ (แถบเขียวที่มุมล่างซ้ายคือระดับเสียงไมค์) |
| `d` | ซ่อน/แสดงแผงทดสอบอารมณ์และปาก |
| `l` | แสดงเวลาแต่ละขั้น (silence · stt · llm · tts · client ⇒ รวม) |
| ช่องพิมพ์ล่างจอ | พิมพ์คุยแทนการพูด |
| แถบเทาบนกลางจอ | ลากย้ายหน้าต่าง (ตำแหน่งถูกจำไว้) |
| — | ซ่อนไว้เบื้องหลัง (ไมค์พักจนกว่าจะแสดงอีกครั้ง) |
| ⏻ หรือ Ctrl+Q | ออกจากโปรแกรมจริงๆ (เมนู tray ก็มี Quit) |

พูดแทรกระหว่างที่ตัวละครกำลังพูดได้ ระหว่างที่เสียงตัวละครดัง ระบบจะเข้มขึ้นกับการตัดสินว่าเป็นเสียงผู้ใช้ เพื่อไม่ให้เสียงตัวเองที่ลอดเข้าไมค์ไปตัดตัวเอง ถ้ายังตัดตัวเองบ่อย ให้ใช้หูฟัง

## รันเบื้องหลัง / ซ่อน-แสดง

กด — หรือปิดหน้าต่าง = **ซ่อน** แอปยังรันอยู่ (ตัวจับเวลายังเตือนด้วยเสียงได้) แต่**ไมค์พัก** ไม่ฟังอะไรจนกว่าจะแสดงหน้าต่างอีกครั้ง (ยังไม่มี wake word จึงไม่ฟังเบื้องหลัง) การ mute ด้วยมือยังคงอยู่หลังแสดงกลับมา

ควบคุมจากภายนอกด้วยสคริปต์ (เปิดซ้ำจะส่งคำสั่งไปยังตัวที่รันอยู่ ไม่เปิดซ้อน):

```bash
app/scripts/mint-ctl.sh            # Linux: เปิด (หรือแสดงถ้าเปิดอยู่แล้ว) — ถ้าไม่ได้รันผ่าน npm run dev ต้อง npm run build ก่อน 1 ครั้ง
app/scripts/mint-ctl.sh --toggle   # ซ่อน/แสดง
app/scripts/mint-ctl.sh --hide | --show | --quit
```
```bat
app\scripts\mint-ctl.cmd --toggle  &rem Windows: คำสั่งเหมือนกัน
```

**Hyprland (Wayland):** Electron บังคับ "always on top" และตั้งตำแหน่งเองไม่ได้ ต้องให้ Hyprland ทำ หน้าต่างมี class `mint-app` ตัวอย่างสำหรับ config แบบ Lua (ปรับ key และ path ตามเครื่อง ตรวจว่าปุ่มไม่ชนกับที่ใช้อยู่):

```lua
-- Mint: ลอย ปักทุก workspace ไม่โปร่งซ้ำ (หน้าต่างโปร่งใสในตัวเองอยู่แล้ว) มุมขวาล่าง
hl.window_rule({
    match   = { class = "mint-app" },
    float   = true,
    pin     = true,
    opacity = "1 override",
    move    = "(monitor_w*0.98-window_w) (monitor_h*0.97-window_h)",
})
hl.bind("SUPER + M", hl.dsp.exec_cmd("/path/to/Mint_Project/app/scripts/mint-ctl.sh --toggle"))
```

ถ้าเห็นกรอบฝ้าๆ (blur) ด้านหลังตัวละคร แปลว่า Hyprland ใส่ blur ให้ส่วนโปร่งใส ต้องเพิ่ม rule ปิด blur ของ class นี้ตามเวอร์ชันของคุณ

## สั่งงานด้วยเสียง

พูดสั่งได้เลย เช่น "ตอนนี้กี่โมงแล้ว", "ตั้งเวลาห้านาที", "เพลงถัดไป", "เปิดไฟร์ฟอกซ์", "ค้นหาสูตรต้มยำกุ้ง", "ปรับเสียงเหลือสามสิบ"

| เครื่องมือ | ทำอะไร | ถามยืนยันก่อน |
|---|---|---|
| `get_time` | บอกเวลา/วันที่ | ไม่ |
| `set_timer`, `cancel_timers` | ตั้ง/ยกเลิกตัวจับเวลา ครบแล้วตัวละครพูดเตือน | ไม่ |
| `media_control` | เล่น/หยุด/ข้าม/ย้อนเพลง (Linux: `playerctl`, Windows: ปุ่ม media) | ไม่ |
| `open_app` | เปิดแอปที่ติดตั้ง (Linux: ไฟล์ `.desktop`, Windows: ชอร์ตคัต Start Menu) | **ใช่** |
| `open_url`, `web_search` | เปิดเว็บ/ค้นหาในเบราว์เซอร์ (เฉพาะ http/https) | **ใช่** |
| `set_volume` | ตั้งเสียงลำโพง 0–100% (Linux: `wpctl`, Windows: `pycaw`) | **ใช่** |

- เครื่องมือที่ต้องยืนยัน ตัวละครจะถามก่อน ("จะเปิดโปรแกรม ... ใช่ไหมคะ") ตอบด้วยเสียงว่า "ได้/ตกลง/โอเค" หรือ "ไม่/ยกเลิก" หรือกดปุ่มบนจอ ภายใน 60 วินาที ถ้าตอบอย่างอื่นหรือตอบไม่ชัด จะถือว่า**ไม่ยืนยัน**
- ความปลอดภัย: AI เลือกได้เฉพาะเครื่องมือในรายการนี้ ไม่มีการรัน shell แอปต้องตรงกับที่ติดตั้งจริง URL ต้องเป็น http(s) เท่านั้น ค่าตัวเลขถูกจำกัดช่วง
- วิธีทำงาน: มีการเรียก LLM สั้นๆ ก่อนรอบที่ดูเหมือนคำสั่งเพื่อตัดสินว่าจะใช้เครื่องมือไหม (เพิ่มเวลาประมาณ 0.45 วินาที) เพราะ persona ยาวๆ ทำให้โมเดล 3B เลิกเรียกเครื่องมือ ประโยคคุยเล่นไม่เรียกขั้นนี้ เพิ่มเครื่องมือใหม่ได้ที่ `backend/mint/tools.py` (ลงทะเบียนใน `_ALL_TOOLS`)
- ตัวจับเวลาผูกกับการเชื่อมต่อ ถ้าปิดแอปหรือ backend รีสตาร์ท ตัวจับเวลาจะหายไป

## ตั้งค่า (environment variables)

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `MINT_LLM_MODEL` | `qwen2.5:3b` | โมเดล Ollama |
| `MINT_LLM_THREADS` | `8` | จำนวน thread ของ LLM (ค่าเริ่มต้นของ Ollama ช้ากว่า ~2.6 เท่าบนเครื่องที่วัด ปรับตามจำนวนคอร์ของคุณ) |
| `MINT_STT_MODEL` | `small` | ขนาด Whisper (`base` เร็วกว่า, `medium` แม่นกว่าแต่ช้า) |
| `MINT_STT_BEAM` | `5` | beam search ของ Whisper (ลด CER 22.2% → 19.8% บนชุดทดสอบเสียงสังเคราะห์) |
| `MINT_STT_LANG` | `th` | ภาษาที่พูด |
| `MINT_END_SILENCE_MS` | `500` | เงียบนานเท่าไรถึงถือว่าพูดจบ |
| `MINT_TTS_VOICE` | `th-TH-PremwadeeNeural` | เสียง (`th-TH-NiwatNeural` = ชาย) |
| `MINT_TTS_RATE` / `MINT_TTS_PITCH` | `+5%` / `+15Hz` | ความเร็ว / โทนเสียง |
| `MINT_TTS_HEDGE_S` | `0.7` | รอกี่วินาทีก่อนยิงคำขอ TTS สำรองซ้อน (edge-tts ล้ม/ช้าเป็นระยะ) |
| `MINT_PORT` | `8765` | พอร์ต backend (ฝั่ง app ยังผูกที่ 8765) |

ตัวแปรฝั่ง app (ใส่ใน `app/.env.local` ซึ่งไม่ขึ้น git): `VITE_MODEL_URL` ชี้ไปยังไฟล์ `mint.model3.json` ของโมเดลที่ใช้

## เปลี่ยนโมเดล Live2D
ดู [app/public/models/README.md](app/public/models/README.md): วางโมเดล สร้าง `mint.model3.json` กับ `mint.emotions.json` ไว้ในโฟลเดอร์เดียวกัน แล้วตั้ง `VITE_MODEL_URL` ตรวจ license ของโมเดลก่อนเผยแพร่ต่อ

## พัฒนาต่อ

```bash
cd backend
uv run pytest            # เทสต์ (ไม่ต้องมี Ollama/ไมค์/เน็ต: ใช้ตัวจำลองทั้งหมด)
uv run ruff check .      # lint

cd ../app
npm run typecheck        # TypeScript
npm run build            # bundle
npm run dev              # รันแอปเต็ม (Vite + Electron)
```

- CI (`.github/workflows/ci.yml`) รัน lint + เทสต์ backend บน Ubuntu และ Windows (Python 3.12 และ 3.14) และ typecheck + build ของ app
- โค้ดที่ขึ้นกับระบบปฏิบัติการอยู่ในชั้น "platform layer" ของ `backend/mint/tools.py` และ `app/electron/main.mjs` เท่านั้น ส่วนอื่นเป็นแบบข้ามแพลตฟอร์ม
- สคริปต์วัดผลใน `backend/scripts/` (`bench_llm.py`, `bench_tools.py`, `bench_stt.py` ฯลฯ) ใช้ Ollama/โมเดลจริง ไม่ได้รันใน CI
- ใส่ความลับ (API key ฯลฯ) ในไฟล์ `.env*` เท่านั้น ซึ่งถูก ignore ไว้แล้ว

## แก้ปัญหา
- **ไมค์ไม่ทำงาน:** ดูแถบเขียวล่างซ้าย ถ้าขึ้นข้อความแดง "ไม่ได้ยินเสียงจากไมค์เลย" ให้เช็กว่าไมค์ไม่ถูก mute (Linux: `wpctl status`, `wpctl set-mute @DEFAULT_AUDIO_SOURCE@ 0`; Windows: Settings → Sound → Input)
- **ไม่มีเสียงตอบ:** เช็กเสียงลำโพง (Linux: `wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.6`) และต่อเน็ตอยู่ไหม
- **`Electron failed to install correctly`:** รัน `node node_modules/electron/install.js` ถ้าแตกไฟล์ไม่สำเร็จ ให้แตก zip ในแคชของ Electron (Linux: `~/.cache/electron/`, Windows: `%LOCALAPPDATA%\electron\Cache`) ลง `node_modules/electron/dist/` เอง แล้วเขียนคำว่า `electron` (Windows: `electron.exe`) ลงไฟล์ `node_modules/electron/path.txt`
- **ตัวละครไม่ขึ้น / `model error`:** ยังไม่ได้วางโมเดลหรือยังไม่ได้ตั้ง `VITE_MODEL_URL` และต้องมี `app/public/lib/live2dcubismcore.min.js`
- **ตอบช้า:** กด `l` ดูว่าช้าที่ขั้นไหน หน้าต่างที่วาด Live2D ด้วย software rendering กิน CPU มาก (จำกัดไว้ที่ 30 fps แล้ว) ถ้า LLM ช้าให้ลอง `MINT_LLM_THREADS` ค่าอื่น
- **เสียงตัวละครสะดุด/ตัดตัวเอง:** ใช้หูฟัง หรือ mute ไมค์ระหว่างฟัง

## ข้อจำกัดที่รู้อยู่
- Wayland ไม่รองรับ global hotkey และ click-through ของ Electron จึงยังไม่มีปุ่มลัดทั้งระบบ (ใช้ปุ่มในหน้าต่างหรือ `mint-ctl` แทน)
- TTS ของ edge-tts ล้มสุ่มบ้าง (แก้ด้วยการยิงซ้ำอัตโนมัติ) และยังไม่มีเสียงสำรองออฟไลน์
- LLM ขนาด 3B ตอบสั้นและบางครั้งเพี้ยน และอาจเลือกเครื่องมือผิดหรือไม่เลือกกับประโยคที่แปลกจากตัวอย่าง (ถ้าไม่ถูกเลือก ตัวละครจะตอบเป็นคำพูดแทน)

## โครงสร้าง
```
backend/mint/   server.py session.py endpointing.py vad.py stt.py llm.py chunker.py tts.py tools.py config.py
backend/tests/  เทสต์ (pytest)       backend/scripts/  สคริปต์วัดผล
app/electron/   main.mjs (หน้าต่าง, ดูแล backend, tray)  preload.cjs
app/src/        main.ts  ws.ts  audio/(mic, player)  live2d/(model, emotions)  ui/debug.ts
app/scripts/    mint-ctl.sh|cmd  fetch-cubism-core.mjs
scripts/        setup.sh  setup.ps1
```
