#!/usr/bin/env bash
# Build the web client into web/dist/, which the Worker serves as static assets.
#
# Needs Qt 6.10 for WebAssembly and Emscripten 4.0.7: run ./toolchain.sh once
# to put both in web/.qt, or point PB_TOOLCHAIN at a copy made elsewhere.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=/dev/null
. ./toolchain-env.sh

if [ ! -x "$QT_WASM/bin/qt-cmake" ]; then
  echo "No Qt for WebAssembly in $QT_WASM: run ./toolchain.sh first." >&2
  exit 1
fi

B=${BUILD_DIR:-$PWD/.build}
"$QT_WASM/bin/qt-cmake" -S . -B "$B" -G Ninja -DCMAKE_BUILD_TYPE=MinSizeRel
cmake --build "$B"

rm -rf dist
mkdir -p dist
cp -R static/. dist/
cp "$B/pulseboard.js" "$B/pulseboard.wasm" "$B/qtloader.js" dist/
echo "dist/: $(du -sh dist | cut -f1), pulseboard.wasm $(du -h dist/pulseboard.wasm | cut -f1)"
