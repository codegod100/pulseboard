# The Qt server

The whole Pulseboard server as one Qt 6 C++ program, compiled to a WASI
component with [qt2wasm](https://fileapi.fastapicloud.dev/forge/#nandi.uk/qt2wasm)
and run by `wasmtime serve`. It replaces the Python server in `worker/`
(same JSON API, same sign-in, same Neon schema), so the web client does not
know the difference.

```
wasmtime serve ─▶ wasi:http/incoming-handler ─▶ src/api.cpp (routes)
                                                 │
     feeds, AT Protocol sign-in, Neon ◀── wasi:http/outgoing-handler
```

- **HTTP in and out** is wasi:http 0.2 (`wit/`, the `server` world:
  `wasi:http/proxy`). `src/wasihttp.cpp` turns it into Qt types; `fetchAll`
  runs up to eight outgoing requests at once with wasi:io/poll, follows
  redirects and enforces timeouts.
- **The database** is Neon, over its
  [SQL-over-HTTP endpoint](https://neon.com/docs/serverless/serverless-driver)
  (`src/db.cpp`): a component has no sockets, so each query is an HTTPS POST to
  `https://<host of DATABASE_URL>/sql`. The schema is `migrations/`, compiled
  in and applied at boot.
- **Signing** (DPoP, ES256) uses the vendored
  [p256-m](https://github.com/mpg/p256-m) (`src/3rdparty`), with randomness from
  wasi:random. Qt Core supplies JSON, XML, SHA-256, URLs and dates.
- **The web client's files** (`web/dist`) are served from a directory
  `wasmtime serve` preopens as `/dist`.
- **Feed refresh**: `wasmtime serve` starts a fresh instance per request and
  has no timers, so `fly/entrypoint.sh` calls an internal route every
  `REFRESH_EVERY_MINUTES` (default 30), with a secret it makes up at boot. It
  also applies migrations once the server is up.

| Source | Ported from (`worker/src/pulseboard/`) |
|---|---|
| `src/api.cpp` | `api.py`, `app.py`, `server.py` |
| `src/store.cpp` | `store.py` (the Postgres dialect) |
| `src/feeds.cpp` | `feeds.py` |
| `src/html.cpp` | `htmlclean.py` |
| `src/opml.cpp` | `opml.py` |
| `src/oauth.cpp` | `oauth.py` |
| `src/pages.cpp` | `pages.py` |

## Build, run, test

Everything comes prebuilt from prefix.dev through `server/pixi.toml`
(linux-64):

```
cd server
pixi run build          # build/pulseboard-server.wasm
DATABASE_URL='postgresql://…' pixi run serve   # http://localhost:8080
pixi run -e test test   # build, then tests/ against a throwaway Postgres
```

The tests (`tests/test_server.py`, ported from `worker/tests`) run the built
component under `wasmtime serve`, with `tests/neon_standin.py` playing Neon in
front of a local Postgres and a fake upstream for feeds and sign-in
(`PULSEBOARD_TEST_UPSTREAM`). `PULSEBOARD_TEST_POSTGRES` points them at an
existing server instead of starting one.

## Deploying to Fly.io

`fly.toml` (repository root) and `server/Dockerfile` build the component and
run it on one always-on machine.

```
fly launch --no-deploy --copy-config      # once: creates the app (pick a name)
fly secrets set DATABASE_URL='postgresql://…'
fly deploy
```

| Environment variable | |
|---|---|
| `DATABASE_URL` | the Neon connection string (secret); pooled or direct both work |
| `PUBLIC_ORIGIN` | optional: pins the origin AT Protocol sign-in uses, e.g. `https://pulseboard.fly.dev`; by default it comes from the proxy's `X-Forwarded-*` headers |
| `REFRESH_EVERY_MINUTES` | optional: how often due feeds are refreshed (default 30, 0 for never) |

The [Server workflow](../.github/workflows/server.yml) runs the tests on every
push, and deploys on pushes to `main` once the repository has a
`FLY_API_TOKEN` Actions secret (`fly tokens create deploy`).
