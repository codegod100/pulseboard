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
"$QT_WASM/bin/qt-cmake" -S . -B "$B" -G Ninja -DCMAKE_BUILD_TYPE=MinSizeRel -DQT_HOST_PATH="$QT_HOST"
cmake --build "$B"

# The wasm ships gzipped (FastAPI Cloud warns about files over 10 MB) and the
# page unpacks it in the browser. Names carry a hash of the build, so a
# browser can never pair one build's pulseboard.js with another's wasm.
H=$(cat "$B/pulseboard.js" "$B/pulseboard.wasm" | sha256sum | cut -c1-10)
rm -rf dist
mkdir -p dist
cp -R static/. dist/
cp "$B/pulseboard.js" "dist/pulseboard.$H.js"
cp "$B/qtloader.js" "dist/qtloader.$H.js"
gzip -9 -n -c "$B/pulseboard.wasm" > "dist/pulseboard.$H.wasm.gz"
sed -i "s/qtloader\.js/qtloader.$H.js/; s/pulseboard\.js/pulseboard.$H.js/; s/pulseboard\.wasm\.gz/pulseboard.$H.wasm.gz/" dist/index.html
echo "dist/: $(du -sh dist | cut -f1), pulseboard.wasm $(du -h "$B/pulseboard.wasm" | cut -f1), gzipped $(du -h "dist/pulseboard.$H.wasm.gz" | cut -f1)"
