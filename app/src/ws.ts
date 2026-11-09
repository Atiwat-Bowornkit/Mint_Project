import type { Emotion } from "./live2d/emotions";

export type ServerEvent =
  | { type: "state"; value: "idle" | "listening" | "thinking" | "speaking" }
  | { type: "transcript"; text: string; stt_ms: number }
  | { type: "reply"; text: string; emotion: Emotion; audio: boolean }
  | { type: "interrupt" }
  | {
      type: "metrics";
      endpoint_ms: number;
      stt_ms: number | null;
      llm_ms: number | null;
      tts_ms: number;
      server_ms: number;
    }
  | { type: "confirm"; id: number; text: string }
  | { type: "confirm_done"; id: number }
  | { type: "error"; message: string }
  | { type: "pong" };

export function connect(
  url: string,
  onEvent: (e: ServerEvent) => void,
  onAudio: (data: ArrayBuffer) => void,
  onClose: () => void,
) {
  const sock = new WebSocket(url);
  sock.binaryType = "arraybuffer";
  sock.onmessage = (m) => {
    if (typeof m.data === "string") onEvent(JSON.parse(m.data));
    else onAudio(m.data as ArrayBuffer);
  };
  sock.onclose = onClose;
  return sock;
}
