import type { Avatar } from "../live2d/model";
import type { Emotion } from "../live2d/emotions";

const EMOTIONS: Emotion[] = ["neutral", "happy", "shy", "sad", "surprised", "worried", "gloomy"];

export function mountDebugPanel(avatar: Avatar) {
  const panel = document.createElement("div");
  panel.id = "debug";
  panel.innerHTML = `
    <div class="row" id="emo"></div>
    <div class="row"><label>mouth <input id="mouth" type="range" min="0" max="1" step="0.01" value="0"></label></div>
    <div class="row"><button id="talk">fake lip-sync</button></div>`;
  document.body.appendChild(panel);

  const emo = panel.querySelector("#emo")!;
  for (const e of EMOTIONS) {
    const b = document.createElement("button");
    b.textContent = e;
    b.onclick = () => void avatar.setEmotion(e);
    emo.appendChild(b);
  }

  const slider = panel.querySelector<HTMLInputElement>("#mouth")!;
  slider.oninput = () => avatar.setMouthOpen(+slider.value);

  let timer = 0;
  panel.querySelector<HTMLButtonElement>("#talk")!.onclick = () => {
    if (timer) {
      clearInterval(timer);
      timer = 0;
      avatar.setMouthOpen(0);
      return;
    }
    timer = window.setInterval(() => avatar.setMouthOpen(Math.random() * 0.9), 90);
  };

  window.addEventListener("keydown", (e) => {
    if (e.key === "d") panel.style.display = panel.style.display === "none" ? "" : "none";
  });
}
