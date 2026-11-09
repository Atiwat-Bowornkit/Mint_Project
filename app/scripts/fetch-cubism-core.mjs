// Downloads Live2D Cubism Core into public/lib (it is not redistributed with this repo).
// Usage: node scripts/fetch-cubism-core.mjs      (run from the app folder)
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const URL_ = "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js";
const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../public/lib/live2dcubismcore.min.js");

console.log("Live2D Cubism Core is licensed by Live2D Inc.:");
console.log("  https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html");
console.log(`Downloading ${URL_}`);
const res = await fetch(URL_);
if (!res.ok) throw new Error(`download failed: HTTP ${res.status}`);
const text = await res.text();
if (!text.includes("Live2D Cubism Core")) throw new Error("unexpected file content, not saving it");
await mkdir(path.dirname(out), { recursive: true });
await writeFile(out, text);
console.log(`saved ${out} (${(text.length / 1024).toFixed(0)} KiB)`);
