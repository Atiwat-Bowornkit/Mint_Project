import { connect, type ServerEvent } from "./ws";
import { Avatar } from "./live2d/model";
import { mountDebugPanel } from "./ui/debug";
import { Mic } from "./audio/mic";
import { SpeechPlayer, type Utterance } from "./audio/player";

const status = document.getElementById("status")!;
const transcript = document.getElementById("transcript")!;
const reply = document.getElementById("reply")!;
const confirmBox = document.getElementById("confirm")!;
const confirmText = document.getElementById("confirm-text")!;
const latencyBox = document.getElementById("latency")!;
const meterFill = document.getElementById("meter-fill")!;
const micHint = document.getElementById("mic-hint")!;
const muteBtn = document.getElementById("mute") as HTMLButtonElement;
const textBox = document.getElementById("text") as HTMLInputElement;

let sock: WebSocket | undefined;
let avatar: Avatar | undefined;
let serverState = "idle";
let pending: Utterance | undefined; // `reply` metadata waiting for its audio frame

function notifyPlayback(playing: boolean) {
  if (sock?.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: "playback", playing }));
}

// Latency of the current turn: server-side stages plus time until the voice is actually audible.
let turnMetrics: (Extract<ServerEvent, { type: "metrics" }> & { at: number }) | undefined;

function showLatency(playAt: number) {
  const m = turnMetrics;
  if (!m) return;
  const s = (ms: number | null) => (ms == null ? "–" : (ms / 1000).toFixed(1) + "s");
  const lag = playAt - m.at; // decode + queue on the client
  const total = m.endpoint_ms + m.server_ms + lag;
  latencyBox.textContent =
    `silence ${s(m.endpoint_ms)} · stt ${s(m.stt_ms)} · llm ${s(m.llm_ms)} · tts ${s(m.tts_ms)}` +
    ` · client ${s(lag)}  ⇒  ${s(total)}`;
  turnMetrics = undefined;
}

const player = new SpeechPlayer();
player.onStart = (u) => {
  notifyPlayback(true);
  showLatency(performance.now());
  reply.textContent += (reply.textContent ? " " : "") + u.text;
  void avatar?.setEmotion(u.emotion);
  status.textContent = "speaking";
};
player.onIdle = () => {
  notifyPlayback(false);
  status.textContent = serverState === "speaking" ? "idle" : serverState;
  void avatar?.setEmotion("neutral");
};

function showState(value: string) {
  serverState = value;
  if (value === "speaking") player.setExpecting(true);
  else if (value === "idle" || value === "listening") player.setExpecting(false);
  if (player.busy && value === "idle") return; // the player decides when speaking is over
  status.textContent = player.busy && value !== "listening" ? "speaking" : value;
}

function onEvent(e: ServerEvent) {
  switch (e.type) {
    case "state":
      showState(e.value);
      break;
    case "transcript":
      transcript.textContent = e.text;
      reply.textContent = "";
      break;
    case "reply": {
      const u = { text: e.text, emotion: e.emotion };
      if (e.audio) pending = u;
      else player.enqueue(u, null);
      break;
    }
    case "metrics":
      turnMetrics = { ...e, at: performance.now() };
      break;
    case "confirm":
      confirmText.textContent = e.text;
      confirmBox.dataset.id = String(e.id);
      confirmBox.style.display = "block";
      break;
    case "confirm_done":
      confirmBox.style.display = "none";
      break;
    case "interrupt":
      pending = undefined;
      player.interrupt();
      reply.textContent = "";
      break;
    case "error":
      status.textContent = `error: ${e.message}`;
      break;
  }
}

function answerConfirm(ok: boolean) {
  sock?.send(JSON.stringify({ type: "confirm_reply", id: Number(confirmBox.dataset.id), ok }));
  confirmBox.style.display = "none";
}
document.getElementById("confirm-yes")!.onclick = () => answerConfirm(true);
document.getElementById("confirm-no")!.onclick = () => answerConfirm(false);

function open() {
  sock = connect(
    "ws://127.0.0.1:8765/ws",
    onEvent,
    (data) => {
      if (!pending) return;
      player.enqueue(pending, data);
      pending = undefined;
    },
    () => {
      status.textContent = "disconnected, retrying…";
      setTimeout(open, 1000);
    },
  );
}
open();

// Mic level meter + "is the mic actually giving us sound?" check.
const DEAD_PEAK = 0.0005; // ~16/32768: digital silence, e.g. a muted device
const DEAD_AFTER_MS = 5000;
let lastSound = performance.now();
let micRunning = false;

function handleLevel(peak: number, rms: number) {
  if (mic.muted) {
    meterFill.style.width = "0%";
    lastSound = performance.now();
    return;
  }
  if (peak > DEAD_PEAK) lastSound = performance.now();
  meterFill.style.width = `${Math.min(100, Math.sqrt(rms) * 220)}%`;
}

setInterval(() => {
  const dead = micRunning && !mic.muted && performance.now() - lastSound > DEAD_AFTER_MS;
  micHint.style.display = dead ? "block" : "none";
}, 1000);

const mic = new Mic();
mic
  .start(
    (pcm) => {
      if (sock?.readyState === WebSocket.OPEN) sock.send(pcm);
    },
    handleLevel,
  )
  .then(() => (micRunning = true))
  .catch((err) => {
    console.error(err);
    transcript.textContent = `microphone unavailable: ${err?.message ?? err}`;
  });

if (import.meta.env.DEV) {
  Object.assign(window, { __level: handleLevel, __forceMicRunning: () => (micRunning = true), __mic: mic });
}

// The mic is off when the user muted it OR the window is hidden in the background.
let manualMute = false;
let hidden = false;
function applyMute() {
  mic.muted = manualMute || hidden;
  muteBtn.textContent = manualMute ? "unmute" : "mute";
}
function toggleMute() {
  manualMute = !manualMute;
  applyMute();
}
muteBtn.onclick = toggleMute;
type Bridge = {
  onToggleMute(cb: () => void): void;
  onVisibility(cb: (visible: boolean) => void): void;
  hide(): void;
  quit(): void;
};
const bridge = (window as unknown as { mintBridge?: Bridge }).mintBridge;
bridge?.onToggleMute(toggleMute);
bridge?.onVisibility((visible) => {
  hidden = !visible;
  applyMute();
});
document.getElementById("hide")!.onclick = () => (bridge ? bridge.hide() : window.close());
document.getElementById("power")!.onclick = () => (bridge ? bridge.quit() : window.close());
window.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "q") bridge?.quit();
  if (e.target === textBox) return;
  if (e.key === "m") toggleMute();
  if (e.key === "l") latencyBox.style.display = latencyBox.style.display === "block" ? "none" : "block";
});

textBox.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !textBox.value.trim()) return;
  sock?.send(JSON.stringify({ type: "user_text", text: textBox.value }));
  textBox.value = "";
});

Avatar.load(document.getElementById("stage") as HTMLCanvasElement)
  .then((a) => {
    avatar = a;
    mountDebugPanel(a);
    let mouth = 0;
    a.app.ticker.add(() => {
      if (!player.busy && mouth < 0.01) return; // leave the debug slider alone when idle
      mouth += (player.level() - mouth) * 0.5; // smooth so the mouth doesn't flutter
      a.setMouthOpen(mouth);
    });
    if (import.meta.env.DEV) (window as unknown as { __player: SpeechPlayer }).__player = player;
  })
  .catch((err) => {
    console.error(err);
    status.textContent = `model error: ${err?.message ?? err}`;
  });
