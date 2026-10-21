# The reader, as a Cloudflare Python Worker

One Worker serves the JSON API, the AT Protocol sign-in, and the ultra web
client (static assets from `../web/dist`). Storage is D1. A cron trigger
refreshes due feeds every 30 minutes, so the reader is current before it is
opened.

| | |
|---|---|
| `src/entry.py` | the only Workers-specific code: D1, `fetch`, WebCrypto and assets adapters |
| `src/pulseboard/app.py` | routes; the same API the Nim reader served |
| `src/pulseboard/store.py` | feeds, subscriptions, articles, read state, sessions |
| `src/pulseboard/feeds.py` | fetching, and parsing RSS, RDF, Atom and JSON Feed |
| `src/pulseboard/htmlclean.py` | the sanitiser every article body goes through, and full-text extraction |
| `src/pulseboard/oauth.py` | AT Protocol OAuth: PAR, PKCE, DPoP, then revoke; only the DID is kept |
| `migrations/` | D1 schema |

Only the standard library is used, so there is nothing to vendor.

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
cd worker
uv run --no-project --with pytest --with cryptography pytest -q tests
cd tests/pyodide && npm ci && npm test
```

The first suite runs the reader under CPython against SQLite with canned HTTP
and a fake AT Protocol authorization server. The second runs `entry.py` under
Pyodide in Node, against stand-ins for D1 and the assets binding, and checks
that a DPoP proof signed with WebCrypto verifies.

## Deploying

The [Deploy workflow](../.github/workflows/deploy.yml) runs both suites, then
creates the `pulseboard` D1 database if it does not exist, applies migrations
and runs `wrangler deploy`, on every push to `main`. It needs two Actions
secrets: `CLOUDFLARE_API_TOKEN` (the "Edit Cloudflare Workers" template plus
D1 Edit) and `CLOUDFLARE_ACCOUNT_ID`.

## Limits worth knowing

Workers cap subrequests per invocation, so `/refresh` and an OPML import fetch
at most 40 feeds per request; the cron trigger picks up the rest.
