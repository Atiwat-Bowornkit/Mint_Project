import { app, BrowserWindow, ipcMain, Menu, nativeImage, Notification, screen, session, Tray } from "electron";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Linux needs --no-sandbox here (SUID chrome-sandbox); on Windows/macOS keep the sandbox on.
if (process.platform === "linux") app.commandLine.appendSwitch("no-sandbox");

const here = path.dirname(fileURLToPath(import.meta.url));
const backendDir = path.resolve(here, "../../backend");
const dev = !!process.env.MINT_DEV;
const HEALTH = "http://127.0.0.1:8765/health";
const stateFile = path.join(app.getPath("userData"), "window.json");
const IS_WIN = process.platform === "win32";

let win;
let tray;
let quitting = false;

// ---- backend supervision -------------------------------------------------------------------

let backend;
let failures = 0;

async function backendAlreadyRunning() {
  try {
    return (await fetch(HEALTH, { signal: AbortSignal.timeout(500) })).ok;
  } catch {
    return false;
  }
}

function backendCommand() {
  const py = IS_WIN
    ? path.join(backendDir, ".venv", "Scripts", "python.exe")
    : path.join(backendDir, ".venv", "bin", "python");
  return fs.existsSync(py)
    ? [py, ["-m", "mint.server"]]
    : ["uv", ["run", "python", "-m", "mint.server"]];
}

async function startBackend() {
  if (quitting) return;
  if (await backendAlreadyRunning()) {
    console.log("[backend] already running on :8765, reusing it");
    return;
  }
  const [cmd, args] = backendCommand();
  const startedAt = Date.now();
  // POSIX: detached = own process group, so we can stop the whole tree (uv + python) on quit.
  // Windows: no process groups here; we use `taskkill /T` instead and just hide the console.
  backend = spawn(cmd, args, { cwd: backendDir, stdio: "inherit", detached: !IS_WIN, windowsHide: true });
  backend.on("exit", (code, signal) => {
    backend = undefined;
    if (quitting) return;
    failures = Date.now() - startedAt > 30_000 ? 1 : failures + 1;
    if (failures > 6) {
      console.error(`[backend] crashed ${failures} times in a row, giving up`);
      return;
    }
    const delay = Math.min(1000 * 2 ** (failures - 1), 10_000);
    console.log(`[backend] exited (${code ?? signal}), restarting in ${delay} ms`);
    setTimeout(startBackend, delay);
  });
}

function stopBackend() {
  if (!backend?.pid) return;
  try {
    if (IS_WIN) spawnSync("taskkill", ["/pid", String(backend.pid), "/T", "/F"], { windowsHide: true });
    else process.kill(-backend.pid, "SIGTERM");
  } catch {
    /* already gone */
  }
}

// ---- window --------------------------------------------------------------------------------

function loadBounds() {
  try {
    const b = JSON.parse(fs.readFileSync(stateFile, "utf8"));
    const visible = screen.getAllDisplays().some((d) => {
      const a = d.workArea;
      return b.x >= a.x - 50 && b.y >= a.y - 50 && b.x < a.x + a.width - 50 && b.y < a.y + a.height - 50;
    });
    if (visible) return b;
  } catch {
    /* first run or corrupt file */
  }
  return {};
}

function saveBoundsSoon() {
  clearTimeout(saveBoundsSoon.t);
  saveBoundsSoon.t = setTimeout(() => {
    if (!win || win.isDestroyed()) return;
    try {
      fs.mkdirSync(path.dirname(stateFile), { recursive: true });
      fs.writeFileSync(stateFile, JSON.stringify(win.getBounds()));
    } catch (e) {
      console.warn("could not save window position:", e.message);
    }
  }, 400);
}

/** The renderer may be gone (crashed, reloading): never let that throw inside an event handler. */
function sendToRenderer(channel, ...args) {
  if (!win || win.isDestroyed()) return;
  const wc = win.webContents;
  if (wc.isDestroyed() || wc.isCrashed()) return;
  try {
    wc.send(channel, ...args);
  } catch (e) {
    console.warn(`[main] could not send "${channel}" to the window: ${e.message}`);
  }
}

const wantsHidden = (argv) => argv.includes("--hide") || argv.includes("--hidden");
let hintedHide = false;

function showWindow() {
  win.show();
  win.focus();
}

function hideWindow() {
  win.hide();
  if (!hintedHide && Notification.isSupported()) {
    hintedHide = true;
    new Notification({
      title: "Mint ซ่อนอยู่เบื้องหลัง",
      body: "ไมค์พักอยู่ เรียกกลับด้วย tray หรือ mint-ctl --toggle",
    }).show();
  }
}

function toggleWindow() {
  if (win.isVisible()) hideWindow();
  else showWindow();
}

/** Commands from a second launch (`mint-ctl --toggle`), e.g. bound to a compositor key. */
function handleCommand(argv) {
  if (!win) return;
  if (argv.includes("--quit")) app.quit();
  else if (argv.includes("--toggle")) toggleWindow();
  else if (argv.includes("--hide")) hideWindow();
  else showWindow(); // plain launch or --show
}

function createWindow() {
  win = new BrowserWindow({
    width: 420,
    height: 640,
    show: !wantsHidden(process.argv),
    ...loadBounds(),
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    hasShadow: false,
    webPreferences: {
      contextIsolation: true,
      autoplayPolicy: "no-user-gesture-required",
      preload: path.join(here, "preload.cjs"),
    },
  });
  win.on("move", saveBoundsSoon);
  win.on("resize", saveBoundsSoon);
  // The renderer pauses the microphone while we are hidden.
  win.on("show", () => sendToRenderer("visibility", true));
  win.on("hide", () => sendToRenderer("visibility", false));
  win.webContents.on("render-process-gone", (_e, d) =>
    console.error(`[renderer] gone: ${d.reason} (exit ${d.exitCode})`),
  );
  win.webContents.on("did-fail-load", (_e, code, desc, url) =>
    console.error(`[renderer] failed to load ${url}: ${desc} (${code})`),
  );
  if (process.env.MINT_DEBUG) {
    win.webContents.on("console-message", (e) => console.log(`[renderer:${e.level}] ${e.message}`));
  }
  // Closing (✕, compositor "close window") hides; only Quit really quits.
  win.on("close", (e) => {
    if (!quitting) {
      e.preventDefault();
      hideWindow();
    }
  });
  if (dev) win.loadURL("http://localhost:5173");
  else win.loadFile(path.join(here, "../dist/index.html"));
  // a window created hidden never fires "hide": tell the renderer once it can listen
  win.webContents.once("did-finish-load", () => {
    if (!win.isVisible()) sendToRenderer("visibility", false);
  });
}

function createTray() {
  try {
    tray = new Tray(nativeImage.createFromPath(path.join(here, "tray.png")));
    tray.setToolTip("Mint");
    const wayland = process.env.XDG_SESSION_TYPE === "wayland"; // compositor decides stacking there
    const menu = Menu.buildFromTemplate([
      { label: "Show / hide", click: toggleWindow },
      { label: "Mute microphone", click: () => sendToRenderer("toggle-mute") },
      ...(wayland
        ? []
        : [{ label: "Always on top", type: "checkbox", checked: true, click: (i) => win.setAlwaysOnTop(i.checked) }]),
      { type: "separator" },
      { label: "Quit", click: () => app.quit() },
    ]);
    tray.setContextMenu(menu);
    tray.on("click", toggleWindow);
  } catch (e) {
    // Many Wayland setups have no tray; the in-window ⏻ button still quits.
    console.warn("tray unavailable:", e.message);
  }
}

// One instance only: a second launch just forwards its command (--toggle, --quit, ...) to us.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", (_e, argv) => handleCommand(argv));
  app.whenReady().then(() => {
    if (process.argv.includes("--quit")) return app.quit(); // nothing running: nothing to stop
    // Only the microphone is ever needed; deny everything else.
    session.defaultSession.setPermissionRequestHandler((_wc, permission, cb) => cb(permission === "media"));
    session.defaultSession.setPermissionCheckHandler((_wc, permission) => permission === "media");
    ipcMain.on("quit", () => app.quit());
    ipcMain.on("hide", hideWindow);
    void startBackend();
    createWindow();
    createTray();
  });
}

app.on("before-quit", () => {
  quitting = true;
  stopBackend();
});
app.on("window-all-closed", () => quitting && app.quit());

// Ctrl+C / `kill` must still take the backend down with us.
for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(sig, () => app.quit());
process.on("exit", stopBackend);
