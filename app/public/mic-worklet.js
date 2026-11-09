// Collects mic samples into 512-sample int16 frames (what the backend VAD expects).
class MicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Int16Array(512);
    this.n = 0;
  }
  process(inputs) {
    const ch = inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      const s = Math.max(-1, Math.min(1, ch[i]));
      this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.n === 512) {
        const out = this.buf.slice().buffer;
        this.port.postMessage(out, [out]);
        this.n = 0;
      }
    }
    return true;
  }
}
registerProcessor("mic-processor", MicProcessor);
