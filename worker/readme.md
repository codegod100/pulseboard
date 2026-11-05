# The reader, as a Cloudflare Python Worker

One Worker serves the JSON API, the AT Protocol sign-in, and the Qt web
client (static assets from `../web/dist`). Storage is D1. A cron trigger
refreshes due feeds every 30 minutes, so the reader is current before it is
opened.

| | |
|---|---|
| `src/entry.py` | the only Workers-specific code: D1, `fetch`, WebCrypto and assets adapters, and the hand-off to FastAPI through the Workers ASGI adapter |
| `src/pulseboard/api.py` | routes, as a FastAPI app; the same API the Nim reader served |
| `src/pulseboard/app.py` | feed refresh, sessions, and the JSON shapes the routes return |
| `src/pulseboard/server.py` | the same routes as an ordinary server (FastAPI Cloud): Turso or SQLite, httpx, web/dist, a refresh loop |
| `src/pulseboard/databases.py` | Turso over its HTTP API, a local SQLite file, and the migration runner the server uses |
| `src/pulseboard/store.py` | feeds, subscriptions, articles, read state, sessions |
| `src/pulseboard/feeds.py` | fetching, and parsing RSS, RDF, Atom and JSON Feed |
| `src/pulseboard/htmlclean.py` | the sanitiser every article body goes through, and full-text extraction |
| `src/pulseboard/oauth.py` | AT Protocol OAuth: PAR, PKCE, DPoP, then revoke; only the DID is kept |
| `migrations/` | D1 schema |

The routes are a [FastAPI](https://fastapi.tiangolo.com) app, run by the
Workers Python runtime through its ASGI adapter. `pyproject.toml` lists FastAPI
and python-multipart (for form bodies); pywrangler vendors them on `dev` and
`deploy`. Everything else is the standard library.

Two things keep it working under Pyodide. Every route and dependency is
`async def`, because FastAPI runs plain functions on a thread pool and Pyodide
has no threads. And the Qt client's files never go through FastAPI: a route
that serves one answers with an empty response carrying `X-Pulseboard-Asset`,
and `entry.py` swaps in the file from the assets binding.

## API

```
GET    /feeds                       subscriptions, with unread counts
POST   /feeds          url=…        subscribe and fetch immediately
DELETE /feeds?url=…                 unsubscribe
GET    /opml                        export subscriptions
POST   /opml           opml=…       import subscriptions

GET    /articles                    unread, newest first
GET    /articles?status=all|read    …or everything, or just the read ones
GET    /articles?feed=…             …scoped to one feed
GET    /articles?q=…                full-text search (FTS5)
GET    /articles/:id                one article

POST   /read           id=…         mark read (undo=1 to reverse)
POST   /read-all       [feed=…]     mark a feed, or everything, read
POST   /refresh                     fetch every subscribed feed
POST   /fetch-content  id=…         scrape the full article text

GET    /unread                      unread count
```

Parameters come from the query string or a form body. Everything except
`/health`, `/auth/*`, `/oauth-client-metadata.json` and the client's static
files needs the `pulseboard_session` cookie; API routes answer 401 without it
and `/` redirects to `/auth/login`.

## Tests

```
pixi run test           # both suites below
pixi run test-worker    # CPython
pixi run test-pyodide   # Pyodide in Node
```

The first suite sends requests through the FastAPI app (with httpx) under
CPython, against SQLite with canned HTTP
and a fake AT Protocol authorization server. The second runs `entry.py` under
Pyodide in Node, with FastAPI and the real Workers Python SDK installed by
micropip, against stand-ins for D1 and the assets binding, and checks that a
DPoP proof signed with WebCrypto verifies. It needs network access to PyPI and
the Pyodide CDN.

## Deploying

The toolchain (Python, Node, pytest) comes from the [pixi](https://pixi.sh)
manifest at the repository root; wrangler runs through `npx`.

```
pixi run login          # once: sign wrangler in to Cloudflare
pixi run db-create      # once: prints database_id; put it in wrangler.toml
just deploy             # git pull, tests, D1 migrations, then wrangler deploy (same as `pixi run deploy`)
pixi run dev            # local Worker with a local D1
```

The [Deploy workflow](../.github/workflows/deploy.yml) does the same on every
push to `main` when the repository has `CLOUDFLARE_API_TOKEN` (the "Edit
Cloudflare Workers" template plus D1 Edit) and `CLOUDFLARE_ACCOUNT_ID` Actions
secrets; without them it runs the tests and skips the deploy.

## Limits worth knowing

Feeds are fetched 8 at a time, with `If-None-Match`/`If-Modified-Since`, so an
unchanged feed costs a 304. `/refresh` skips feeds fetched in the last 10
minutes (`force=1` fetches them all). Workers cap subrequests per invocation, so
one request fetches at most 40 feeds; the cron trigger picks up the rest.

Each feed's last error is kept on the feed (`error` in `/feeds`):

```
npx wrangler@4 d1 execute pulseboard --remote --command \
  "SELECT feed_url, error_count, last_error FROM feeds WHERE last_error IS NOT NULL"
```
