/** Loudness of one int16 frame: peak and rms, both 0..1. */
export function frameLevel(pcm: ArrayBuffer): { peak: number; rms: number } {
  const x = new Int16Array(pcm);
  let peak = 0;
  let sum = 0;
  for (const v of x) {
    const a = Math.abs(v);
    if (a > peak) peak = a;
    sum += v * v;
  }
  return { peak: peak / 32768, rms: Math.sqrt(sum / x.length) / 32768 };
}

/** Captures the microphone as 16 kHz mono int16 frames of 512 samples. */
export class Mic {
  private ctx?: AudioContext;
  private stream?: MediaStream;
  muted = false;

  async start(onFrame: (pcm: ArrayBuffer) => void, onLevel?: (peak: number, rms: number) => void): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    // Chromium resamples the mic stream to the context rate for us.
    this.ctx = new AudioContext({ sampleRate: 16000 });
    await this.ctx.audioWorklet.addModule("./mic-worklet.js");
    const node = new AudioWorkletNode(this.ctx, "mic-processor");
    node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      if (onLevel) {
        const { peak, rms } = frameLevel(e.data);
        onLevel(peak, rms);
      }
      if (!this.muted) onFrame(e.data);
    };
    this.ctx.createMediaStreamSource(this.stream).connect(node);
  }

  stop() {
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close();
  }
}
