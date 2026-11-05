# pulseboard

An RSS reader. Two pieces:

| | |
|---|---|
| [`worker`](worker) | the reader: a FastAPI app serving a small JSON API |
| [`web`](web) | the web client, a Qt Quick app (C++ and QML) built with Qt for WebAssembly |

The reader runs in either of two places, from the same routes
(`worker/src/pulseboard/api.py`):

- **FastAPI Cloud**, as an ordinary server (`main.py`, `pyproject.toml` here),
  with [Turso](https://turso.tech) for storage. See below.
- **Cloudflare**, as a Python Worker with D1 for storage. See
  [`worker/readme.md`](worker/readme.md).

Either way the reader serves the client's build (`web/dist`) itself, so the
API and the page share an origin and there is no CORS to arrange, and due
feeds are refreshed every 30 minutes.

Everything runs through [pixi](https://pixi.sh): `pixi run test`,
`pixi run build-web`, `pixi run serve`. See
[`worker/readme.md`](worker/readme.md) for the API and the tests.

## Deploying to FastAPI Cloud

Storage is Turso, hosted libSQL: SQLite with FTS5, so the schema in
`worker/migrations` carries over unchanged and is applied on startup. Create
a database and a token with the [Turso CLI](https://docs.turso.tech/cli):

```
turso db create pulseboard
turso db show pulseboard --url        # libsql://pulseboard-<you>.turso.io
turso db tokens create pulseboard     # the auth token
```

Then set them on the app and deploy (the first deploy signs you in through
the browser and creates the app):

```
uv run fastapi cloud env set TURSO_DATABASE_URL "libsql://pulseboard-<you>.turso.io"
uv run fastapi cloud env set --secret TURSO_AUTH_TOKEN "<token>"
just deploy-cloud                     # git pull, tests, then fastapi deploy
```

| Environment variable | |
|---|---|
| `TURSO_DATABASE_URL` | the database; without it the server uses a local SQLite file (`PULSEBOARD_DB`, default `pulseboard.db`), which FastAPI Cloud does not keep across deploys |
| `TURSO_AUTH_TOKEN` | its token (secret) |
| `PUBLIC_ORIGIN` | optional: pins the origin AT Protocol sign-in uses, e.g. `https://pulseboard.fastapicloud.dev`; by default it comes from the proxy's `X-Forwarded-*` headers |
| `REFRESH_EVERY_MINUTES` | optional: how often the server refreshes due feeds (default 30, 0 for never). An app scaled to zero refreshes only while awake; the client also refreshes whenever it opens |

The [Deploy workflow](.github/workflows/deploy.yml) deploys on every push to
`main` once the repository has `FASTAPI_CLOUD_TOKEN` (a deploy token, from the
app's settings in the FastAPI Cloud dashboard) and `FASTAPI_CLOUD_APP_ID`
Actions secrets. Locally, `pixi run serve` runs the server with reload against
a local SQLite file.

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
