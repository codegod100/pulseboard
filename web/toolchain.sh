#!/usr/bin/env bash
# Set up the toolchain build.sh needs, in web/.qt (or $PB_TOOLCHAIN):
#
#   emsdk/    Emscripten 4.0.7, the version Qt 6.10 is tested with
#   host/     Qt 6.10.2 for this machine (conda-forge), for moc, qmlcachegen …
#   wasm/     Qt 6.10.2 for WebAssembly: qtbase, qtshadertools, qtdeclarative,
#             compiled here from source (an hour or so on four cores)
#
# Only the official Qt installer ships a prebuilt Qt for WebAssembly; this
# builds the same thing from plain downloads, so it also works where
# download.qt.io is out of reach. Linux x86-64 only.
set -euo pipefail
cd "$(dirname "$0")"

QT=6.10.2
# emscripten-releases build for 4.0.7 (see emsdk's emscripten-releases-tags.json)
EMSDK_BUILD=4bdd4bce8dd5cb25c14693aeab8cc977dd1d7a41
MICROMAMBA=2.9.0
T=${PB_TOOLCHAIN:-$PWD/.qt}
J=${JOBS:-$(nproc)}
mkdir -p "$T/src"

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

if [ ! -x "$T/host/lib/qt6/moc" ]; then
  echo "== host Qt $QT"
  mkdir -p "$T/mamba"
  curl -fsSL "https://conda.anaconda.org/conda-forge/linux-64/micromamba-$MICROMAMBA-0.tar.bz2" \
    | tar xj -C "$T/mamba" bin/micromamba
  MAMBA_ROOT_PREFIX="$T/mamba" "$T/mamba/bin/micromamba" create -y -q -p "$T/host" \
    -c conda-forge "qt6-main=$QT" libgl-devel libegl-devel libopengl-devel
fi

# shellcheck source=/dev/null
. "$PWD/toolchain-env.sh"

fetch() {  # Ubuntu's copies of the Qt source releases
  local pkg=$1 name=$2
  if [ ! -d "$T/src/$name-everywhere-src-$QT" ]; then
    curl -fsSL "https://archive.ubuntu.com/ubuntu/pool/universe/q/$pkg/${pkg}_$QT$3.orig.tar.xz" | tar xJ -C "$T/src"
  fi
}

if [ ! -f "$T/wasm/lib/cmake/Qt6Core/Qt6CoreConfig.cmake" ]; then
  echo "== qtbase for wasm"
  fetch qt6-base qtbase +dfsg
  rm -rf "$T/build/qtbase" && mkdir -p "$T/build/qtbase" && cd "$T/build/qtbase"
  # (Ubuntu's tarball drops the bundled SQLite, so Qt SQL is left out.)
  "$T/src/qtbase-everywhere-src-$QT/configure" -platform wasm-emscripten -qt-host-path "$T/host" \
    -prefix "$T/wasm" -release -optimize-size -no-widgets -no-feature-sql -nomake tests -nomake examples
  cmake --build . --parallel "$J" && cmake --install .
  cd - >/dev/null
fi

for m in "qt6-shadertools qtshadertools" "qt6-declarative qtdeclarative +dfsg"; do
  set -- $m
  if [ ! -f "$T/build/$2/.installed" ]; then
    echo "== $2 for wasm"
    fetch "$1" "$2" "${3:-}"
    rm -rf "$T/build/$2" && mkdir -p "$T/build/$2" && cd "$T/build/$2"
    "$T/wasm/bin/qt-configure-module" "$T/src/$2-everywhere-src-$QT" -- -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF
    cmake --build . --parallel "$J" && cmake --install . && touch .installed
    cd - >/dev/null
  fi
done
echo "Toolchain ready in $T"
