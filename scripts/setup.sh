#!/bin/sh
# One-time setup for development on Linux/macOS. Run from the repo root: ./scripts/setup.sh
set -e
cd "$(dirname "$0")/.."

command -v uv >/dev/null   || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
command -v node >/dev/null || { echo "Node.js is required: https://nodejs.org"; exit 1; }

(cd backend && uv sync)
(cd app && npm install && node scripts/fetch-cubism-core.mjs)

cat <<'MSG'

Setup done. Still needed (not part of the repo):
  1. Ollama + a model:      ollama pull qwen2.5:3b
  2. A Live2D model:        see app/public/models/README.md
  3. Run:                   cd app && npm run dev
MSG
