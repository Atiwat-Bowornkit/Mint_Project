# One-time setup for development on Windows. Run from the repo root:  .\scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command uv -ErrorAction SilentlyContinue))   { throw "uv is required: https://docs.astral.sh/uv/" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js is required: https://nodejs.org" }

Push-Location backend; uv sync; Pop-Location
Push-Location app; npm install; node scripts/fetch-cubism-core.mjs; Pop-Location

Write-Host @"

Setup done. Still needed (not part of the repo):
  1. Ollama + a model:      ollama pull qwen2.5:3b
  2. A Live2D model:        see app\public\models\README.md
  3. Run:                   cd app; npm run dev
"@
