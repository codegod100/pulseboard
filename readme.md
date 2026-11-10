# pulseboard

An RSS reader. Three pieces:

| | |
|---|---|
| [`server`](server) | the reader: a Qt 6 C++ server compiled to a WASI component with [qt2wasm](https://fileapi.fastapicloud.dev/forge/#nandi.uk/qt2wasm), run by `wasmtime serve` on [Fly.io](https://fly.io) with Postgres on [Neon](https://neon.tech) |
| [`web`](web) | the web client, a Qt Quick app (C++ and QML) built with Qt for WebAssembly |
| [`worker`](worker) | the previous reader, a FastAPI app (FastAPI Cloud, or a Cloudflare Python Worker with D1), which the Qt server replaces |

The server serves the client's build (`web/dist`) itself, so the API and the
page share an origin and there is no CORS to arrange, and due feeds are
refreshed every 30 minutes. See [`server/README.md`](server/README.md) for how
it is built, tested and deployed (`cd server && pixi run -e test test`, then
`fly deploy` from here).

The rest of this file describes the Python server, which still works as
before: `pixi run test`, `pixi run build-web`, `pixi run serve`. See
[`worker/readme.md`](worker/readme.md) for the API and its tests.

## Deploying to FastAPI Cloud

Storage is Postgres on [Neon](https://neon.tech); the schema
(`worker/migrations-postgres`) is applied on startup. One command does the
whole setup:

```
just deploy
```

There is nothing to paste: every sign-in happens in the browser. It pulls
main and runs the tests, signs you in to Neon (`neonctl login`) and looks up
the **pooled** connection string of the Neon project named `pulseboard`
itself, creating that project if it doesn't exist (`NEON_PROJECT=<name>` or
`NEON_PROJECT_ID=<id>` uses another), offers to copy the existing data from
Cloudflare D1 (signing you in to Cloudflare if needed), then deploys to
FastAPI Cloud (signing you in there the first time), stores the string on the
app as the secret `DATABASE_URL`, and deploys again so the app picks it up.
It needs Node (for `npx neonctl` and `npx wrangler`), pixi and uv.

Later deploys can use `just redeploy` (pull, test, deploy, no questions). To copy D1 into Neon on its own:
`DATABASE_URL=… just migrate-d1` (wrangler signs in to Cloudflare if needed;
it is safe to run again, and sessions are not copied, so you sign in once on
the new address).

| Environment variable | |
|---|---|
| `DATABASE_URL` | Neon's pooled connection string (secret). Without it the server uses a local SQLite file (`PULSEBOARD_DB`, default `pulseboard.db`), which FastAPI Cloud does not keep across deploys |
| `PUBLIC_ORIGIN` | optional: pins the origin AT Protocol sign-in uses, e.g. `https://pulseboard.fastapicloud.dev`; by default it comes from the proxy's `X-Forwarded-*` headers |
| `REFRESH_EVERY_MINUTES` | optional: how often the server refreshes due feeds (default 30, 0 for never). An app scaled to zero refreshes only while awake; the client also refreshes whenever it opens |

The [Deploy workflow](.github/workflows/deploy.yml) deploys on every push to
`main` once the repository has `FASTAPI_CLOUD_TOKEN` (a deploy token, from the
app's settings in the FastAPI Cloud dashboard) and `FASTAPI_CLOUD_APP_ID`
Actions secrets. Locally, `pixi run serve` runs the server with reload against
a local SQLite file, or against Postgres if `DATABASE_URL` is set.

## Why there is a server at all

A browser cannot fetch most feeds directly: almost none send the CORS
headers that would allow it. Something outside the browser has to do the
fetching, which is what the reader is. It also does the work that wants to
happen once rather than per client — parsing four feed formats, full-text
search, and pulling readable article text out of pages that only syndicate
an excerpt.

## Security

The reader requires AT Protocol OAuth: a pushed authorization request with
PKCE and DPoP, after which the tokens are revoked at once. Pulseboard keeps
only the verified DID in a short-lived, opaque web session. Subscriptions and
read state are scoped to that DID.

Article bodies are markup from other people's servers, so every body the API
serves — scraped and straight-from-the-feed alike — goes through a
whitelist: `script`, `style` and `iframe` never survive, attributes are
allowed rather than denied, and links that are not http(s) are flattened to
text.

## History

This began as a port of a social RSS reader built on the AT Protocol — Go
backend, SvelteKit frontend, accounts, annotations, a recommendation engine.
It then became a Nim binary with a Flutter client, deployed on Modal, before
moving to Cloudflare, and then to FastAPI Cloud. The [git history](../../commits/main) has all of it.
