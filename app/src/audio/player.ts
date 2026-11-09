import type { Emotion } from "../live2d/emotions";

export interface Utterance {
  text: string;
  emotion: Emotion;
}

interface Item extends Utterance {
  buffer: Promise<AudioBuffer | null>;
}

/**
 * Plays sentences strictly in order. `onStart` fires when a sentence actually begins playing,
 * so subtitles and expressions line up with the voice. level() feeds lip-sync.
 */
export class SpeechPlayer {
  private ctx = new AudioContext();
  private analyser = this.ctx.createAnalyser();
  private samples: Float32Array<ArrayBuffer>;
  private queue: Item[] = [];
  private current?: AudioBufferSourceNode;
  private timer?: number;
  private epoch = 0;
  busy = false;
  /** True while the server is still producing sentences, so gaps between them aren't "idle". */
  private expecting = false;

  onStart: (u: Utterance) => void = () => {};
  onIdle: () => void = () => {};

  constructor() {
    this.analyser.fftSize = 1024;
    this.samples = new Float32Array(this.analyser.fftSize);
    this.analyser.connect(this.ctx.destination);
  }

  /** `audio` is a whole mp3/wav file, or null when TTS failed (text is still shown). */
  enqueue(u: Utterance, audio: ArrayBuffer | null) {
    const epoch = this.epoch;
    const buffer = audio
      ? this.ctx.decodeAudioData(audio).catch((e) => {
          console.warn("decode failed", e);
          return null;
        })
      : Promise.resolve(null);
    this.queue.push({ ...u, buffer });
    void buffer.then(() => epoch === this.epoch && this.pump());
    this.pump();
  }

  setExpecting(v: boolean) {
    this.expecting = v;
    if (!v && !this.current && !this.timer && !this.queue.length) this.finish();
  }

  interrupt() {
    this.expecting = false;
    this.epoch++;
    this.queue = [];
    clearTimeout(this.timer);
    if (this.current) {
      this.current.onended = null;
      try {
        this.current.stop();
      } catch {
        /* already stopped */
      }
      this.current = undefined;
    }
    this.finish();
  }

  /** Current output loudness mapped to a 0..1 mouth opening. */
  level(): number {
    if (!this.busy) return 0;
    this.analyser.getFloatTimeDomainData(this.samples);
    let sum = 0;
    for (const v of this.samples) sum += v * v;
    const rms = Math.sqrt(sum / this.samples.length);
    return Math.min(1, Math.max(0, (rms - 0.01) * 6));
  }

  private pump() {
    if (this.current || this.timer || !this.queue.length) return;
    const item = this.queue[0];
    const epoch = this.epoch;
    this.busy = true;
    void item.buffer.then((buf) => {
      if (epoch !== this.epoch || this.queue[0] !== item) return;
      this.queue.shift();
      void this.ctx.resume();
      this.onStart(item);
      if (!buf) {
        // no audio: keep the text on screen for roughly the time it would take to say
        this.timer = window.setTimeout(() => this.next(epoch), Math.max(1200, item.text.length * 90));
        return;
      }
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.connect(this.analyser);
      src.onended = () => this.next(epoch);
      this.current = src;
      src.start();
    });
  }

  private next(epoch: number) {
    if (epoch !== this.epoch) return;
    this.current = undefined;
    this.timer = undefined;
    if (this.queue.length) this.pump();
    else if (!this.expecting) this.finish();
  }

  private finish() {
    if (!this.busy) return;
    this.busy = false;
    this.onIdle();
  }
}
