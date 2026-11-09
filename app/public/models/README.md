# Live2D models

Put your Live2D model here, one folder per model (not tracked by git: models belong to their
authors and often have their own usage terms).

```
app/public/models/<name>/
  <anything>.moc3, textures, physics ...      # the model files
  mint.model3.json                            # model3.json that Mint loads (see below)
  mint.emotions.json                          # which expressions to use for each emotion
```

## mint.model3.json
A normal Cubism 3+ `.model3.json`, plus:
- `Groups` contains `{"Target":"Parameter","Name":"LipSync","Ids":["ParamMouthOpenY"]}` so the mouth follows the voice.
- `FileReferences.Expressions` lists the expressions you want to use (`{"Name": "...", "File": "..."}`).

## mint.emotions.json
Maps Mint's emotions to expression names from `mint.model3.json` (first one is applied):

```json
{
  "neutral": [],
  "happy": ["Fanged Smile", "Blush"],
  "shy": ["Blush"],
  "sad": ["Tears"],
  "surprised": ["Star"],
  "worried": ["Sweat Drop"],
  "gloomy": ["Gloom"]
}
```

## Pointing the app at your model
Create `app/.env.local` (git-ignored):

```
VITE_MODEL_URL=models/<name>/mint.model3.json
```

Cubism **Core** (`app/public/lib/live2dcubismcore.min.js`) is also not in the repo. Fetch it with
`node scripts/fetch-cubism-core.mjs` from the `app` folder. It is covered by Live2D's license:
https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html
