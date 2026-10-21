# pulseboard

An RSS reader on Cloudflare. Two pieces, one Worker:

| | |
|---|---|
| [`worker`](worker) | the reader: a Python Worker serving a small JSON API, with D1 for storage |
| [`web`](web) | the web client, an [ultra](https://github.com/codegod100/ultra) app (LPython compiled to wasm) |

The Worker serves the client's build (`web/dist`) as static assets, so the API
and the page share an origin and there is no CORS to arrange. A cron trigger
refreshes feeds every 30 minutes.

Every push to `main` runs the tests and deploys; see
[`worker/readme.md`](worker/readme.md) for the API, the tests and what the
deploy needs.

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
moving to Cloudflare. The [git history](../../commits/main) has all of it.
