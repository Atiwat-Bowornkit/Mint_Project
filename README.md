# Mint — ผู้ช่วย AI เสียง real-time พร้อมตัวละคร Live2D

คุยด้วยเสียงภาษาไทยกับตัวละคร Live2D บนเดสก์ท็อป ประมวลผลบนเครื่องเกือบทั้งหมด (CPU ล้วน)

```
ไมค์ → VAD (Silero) → STT (faster-whisper) → LLM (Ollama, stream) → TTS (edge-tts) → เสียง + ปากขยับ + อารมณ์
```

![CI](../../actions/workflows/ci.yml/badge.svg)

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
