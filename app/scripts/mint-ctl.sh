#!/bin/sh
# Start Mint, or control the running instance:
#   mint-ctl.sh            start (or show if already running)
#   mint-ctl.sh --toggle   show/hide        (bind this to a key)
#   mint-ctl.sh --show | --hide | --quit
# Needs `npm run build` once when not started through `npm run dev`.
DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec "$DIR/node_modules/electron/dist/electron" "$DIR" --no-sandbox "$@"
