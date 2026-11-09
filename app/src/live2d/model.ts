import * as PIXI from "pixi.js";
import { install } from "@pixi/unsafe-eval";
import { Live2DModel } from "pixi-live2d-display/cubism4";
import { loadEmotionMap, MODEL_URL, type Emotion, type EmotionMap } from "./emotions";

install(PIXI as unknown as Parameters<typeof install>[0]); // CSP forbids eval-compiled shaders
(window as unknown as { PIXI: typeof PIXI }).PIXI = PIXI;

const MOUTH = "ParamMouthOpenY";
type CoreModel = { setParameterValueById(id: string, v: number): void };

export class Avatar {
  private mouth = 0;
  private active: string[] = [];

  private constructor(
    readonly app: PIXI.Application,
    readonly model: Live2DModel,
    private readonly emotions: EmotionMap,
  ) {}

  static async load(canvas: HTMLCanvasElement): Promise<Avatar> {
    const app = new PIXI.Application({
      view: canvas,
      backgroundAlpha: 0,
      resizeTo: window,
      antialias: true,
      autoDensity: true,
      resolution: Math.min(window.devicePixelRatio || 1, 1.5),
    });
    app.ticker.maxFPS = 30; // plenty for a talking avatar; leaves CPU to STT/LLM/TTS
    const [model, emotions] = await Promise.all([
      Live2DModel.from(MODEL_URL, { autoInteract: false }),
      loadEmotionMap(MODEL_URL),
    ]);
    app.stage.addChild(model);
    const avatar = new Avatar(app, model, emotions);
    avatar.fit();
    if (import.meta.env.DEV) (window as unknown as { __avatar: Avatar }).__avatar = avatar;
    window.addEventListener("resize", () => avatar.fit());
    window.addEventListener("mousemove", (e) => model.focus(e.clientX, e.clientY));

    // Write the mouth param inside the model update so motions/physics can't overwrite it.
    model.internalModel.on("beforeModelUpdate", () => {
      (model.internalModel.coreModel as unknown as CoreModel).setParameterValueById(MOUTH, avatar.mouth);
    });
    return avatar;
  }

  private fit() {
    const { model, app } = this;
    model.scale.set(1);
    const s = Math.min(app.screen.width / model.width, app.screen.height / model.height) * 0.95;
    model.scale.set(s);
    model.anchor.set(0.5, 0.5);
    model.position.set(app.screen.width / 2, app.screen.height / 2);
  }

  /** 0..1, applied every frame. */
  setMouthOpen(v: number) {
    this.mouth = Math.max(0, Math.min(1, v));
  }

  get expressionNames(): string[] {
    return Object.values(this.emotions).flat().filter((n, i, a) => a.indexOf(n) === i);
  }

  async setEmotion(e: Emotion) {
    const em = this.model.internalModel.motionManager.expressionManager;
    if (!em) return;
    em.resetExpression();
    this.active = this.emotions[e];
    // The expression manager holds one expression at a time; the first entry is the primary.
    if (this.active.length) await this.model.expression(this.active[0]);
  }

  async setExpression(name: string) {
    await this.model.expression(name);
  }
}
