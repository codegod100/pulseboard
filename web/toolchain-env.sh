# Source this to put the toolchain from toolchain.sh on PATH.
T=${PB_TOOLCHAIN:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.qt}
export EMSDK="$T/emsdk"
export EM_CONFIG="$EMSDK/.emscripten"
export EM_CACHE="$T/emcache"
export PATH="$EMSDK/upstream/emscripten:$EMSDK/upstream/bin:$PATH"
export QT_WASM="$T/qt/6.10.2/wasm_singlethread"
