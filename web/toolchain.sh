#!/usr/bin/env bash
# Set up the toolchain build.sh needs, in .qt at the repo root (or $PB_TOOLCHAIN):
#
#   emsdk/                      Emscripten 4.0.7, the version Qt 6.10 is tested with
#   qt/6.10.2/wasm_singlethread Qt 6.10.2 for WebAssembly (official prebuilt)
#   qt/6.10.2/gcc_64            Qt 6.10.2 for this machine, for moc, qmlcachegen …
#
# Both Qts come from download.qt.io through aqtinstall (run with uvx), so this
# takes about a minute. Linux x86-64 only.
set -euo pipefail
cd "$(dirname "$0")"

QT=6.10.2
AQT=3.3.0
# emscripten-releases build for 4.0.7 (see emsdk's emscripten-releases-tags.json)
EMSDK_BUILD=4bdd4bce8dd5cb25c14693aeab8cc977dd1d7a41
T=${PB_TOOLCHAIN:-$(cd .. && pwd)/.qt}
mkdir -p "$T"

if [ ! -x "$T/emsdk/upstream/emscripten/emcc" ]; then
  echo "== Emscripten"
  mkdir -p "$T/emsdk/upstream"
  curl -fsSL "https://storage.googleapis.com/webassembly/emscripten-releases-builds/linux/$EMSDK_BUILD/wasm-binaries.tar.xz" \
    | tar xJ -C "$T/emsdk/upstream" --strip-components=1
  cat > "$T/emsdk/.emscripten" <<CFG
import os
emsdk_path = os.path.dirname(os.getenv('EM_CONFIG') or __file__).replace('\\\\', '/')
NODE_JS = '$(command -v node)'
LLVM_ROOT = emsdk_path + '/upstream/bin'
BINARYEN_ROOT = emsdk_path + '/upstream'
EMSCRIPTEN_ROOT = emsdk_path + '/upstream/emscripten'
CFG
fi

aqt() { uvx --from "aqtinstall==$AQT" aqt "$@"; }

if [ ! -f "$T/qt/$QT/wasm_singlethread/bin/qt-cmake" ]; then
  echo "== Qt $QT for WebAssembly"
  aqt install-qt all_os wasm "$QT" wasm_singlethread -O "$T/qt"
fi
# the all_os archive comes without execute bits
chmod +x "$T/qt/$QT/wasm_singlethread/bin/"*

if [ ! -x "$T/qt/$QT/gcc_64/libexec/moc" ]; then
  echo "== host Qt $QT"
  aqt install-qt linux desktop "$QT" linux_gcc_64 -O "$T/qt" \
    --archives qtbase qtdeclarative qtshadertools icu
fi
echo "Toolchain ready in $T"
