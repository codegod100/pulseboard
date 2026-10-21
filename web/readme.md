# Web client

Pulseboard's browser app, written with [ultra](https://github.com/codegod100/ultra):
LPython compiled to WebAssembly, with an Elm-style update/view loop.

- `app.py` is the whole app: model, `update()`, `view()`.
- `static/` holds the page (`index.html`, with the app's own JS imports for
  requests and formatting), the stylesheet and the PWA files.
- `dist/` is the build output, committed, which the Worker serves as static
  assets from the same origin as the API.

Build with `./build.sh` (needs [pixi](https://pixi.sh); it fetches ultra at a
pinned commit into `.ultra/`). Test in a browser against a stand-in API:

```sh
python3 test/mock_server.py 8765 &
BASE=http://127.0.0.1:8765 node test/e2e.cjs   # needs playwright
```
