# Web client

Pulseboard's browser app: C++ and QML, built with
[Qt for WebAssembly](https://doc.qt.io/qt-6/wasm.html). The whole UI is a Qt
Quick scene drawn into one canvas.

- `src/` is the C++: `reader.*` holds the state and every action, `api.*`
  talks to the reader's JSON API, `models.*` are the feed and article lists
  the views draw, and `platform.*` is the little it asks of the browser
  (opening a tab, the clipboard, the sign-in redirect).
- `qml/` is the look: the article list (`ReaderPage`), Manage feeds
  (`ManagePage`), the dialogs and toast (`Main`), and small components. Icons
  are lucide's SVG paths drawn with Qt Quick Shapes.
- `static/` holds the page that loads the app (`index.html`), its stylesheet
  and the PWA files.
- `dist/` is the build output, committed, which the Worker serves as static
  assets from the same origin as the API.

## Building

```sh
./toolchain.sh   # once: Emscripten 4.0.7 and Qt 6.10.2 for wasm, into ../.qt/
./build.sh       # compiles into dist/
```

`toolchain.sh` fetches the official prebuilt Qt for WebAssembly and the host
Qt it needs (via aqtinstall, run with `uvx`) plus the matching Emscripten, in
about a minute. If you already have them, lay them out as `emsdk/` and
`qt/6.10.2/{wasm_singlethread,gcc_64}` in one directory and point
`PB_TOOLCHAIN` at it.

## Testing

Against a stand-in API, in a browser:

```sh
python3 test/mock_server.py 8765 &
BASE=http://127.0.0.1:8765 node test/e2e.cjs   # needs playwright
```

The canvas has no DOM to query, so the test reads the app's state through
`pbSnapshot()` and calls its actions through `pbCall()` (both exported from
`src/main.cpp`), and clicks and types into the real UI where it can.
