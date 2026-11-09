export type Emotion = "neutral" | "happy" | "shy" | "sad" | "surprised" | "worried" | "gloomy";
export type EmotionMap = Record<Emotion, string[]>;

export const EMOTIONS: Emotion[] = ["neutral", "happy", "shy", "sad", "surprised", "worried", "gloomy"];

/** Set VITE_MODEL_URL in app/.env.local, e.g. models/<name>/mint.model3.json (see models/README.md). */
export const MODEL_URL: string = import.meta.env.VITE_MODEL_URL ?? "models/default/mint.model3.json";

const EMPTY: EmotionMap = Object.fromEntries(EMOTIONS.map((e) => [e, []])) as unknown as EmotionMap;

/**
 * Which expressions each emotion triggers is model-specific, so it lives next to the model in
 * `mint.emotions.json`. Without it the avatar still works, it just keeps a neutral face.
 */
export async function loadEmotionMap(modelUrl: string): Promise<EmotionMap> {
  const url = modelUrl.replace(/[^/]*$/, "mint.emotions.json");
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return { ...EMPTY, ...(await res.json()) };
  } catch (e) {
    console.warn(`no emotion map at ${url} (${e}); expressions disabled`);
    return EMPTY;
  }
}
