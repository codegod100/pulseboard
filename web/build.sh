#!/usr/bin/env bash
# Build the web client into web/dist/, which the Worker serves as static assets.
#
# Needs pixi (https://pixi.sh). The ultra toolchain (LPython 0.22) comes from a
# checkout of codegod100/ultra at the pinned commit, kept in web/.ultra, or
# from $ULTRA if set.
set -euo pipefail
cd "$(dirname "$0")"

ULTRA_REPO=https://github.com/codegod100/ultra
ULTRA_REV=265c0d40073161230b18ce9499e378924eaa2caf
ULTRA=${ULTRA:-$PWD/.ultra}

if [ ! -d "$ULTRA/.git" ]; then
  git clone --quiet "$ULTRA_REPO" "$ULTRA"
fi
if [ "${ULTRA_PIN:-1}" = 1 ]; then
  git -C "$ULTRA" fetch --quiet origin "$ULTRA_REV" 2>/dev/null || true
  git -C "$ULTRA" checkout --quiet "$ULTRA_REV"
fi

rm -rf dist
mkdir -p dist
cp -R static/. dist/
# compiles app.py, and copies ultra.js and ui.css next to app.wasm
pixi run --manifest-path "$ULTRA/pixi.toml" python "$ULTRA/tools/ultra.py" build "$PWD/app.py" -o "$PWD/dist/app.wasm"
