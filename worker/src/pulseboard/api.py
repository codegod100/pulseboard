"""Routes, as a FastAPI app. The same JSON API the Nim reader served, so
clients need not care which one is behind them.

`create_api` takes a function from the request to an `App`, so the Worker can
build one over D1 and fetch while the tests build one over SQLite. Nothing here
is Workers-specific: entry.py hands requests over through the Workers ASGI
adapter.

The Qt web client's files are not served from here. A route that wants a
static file answers with an empty response carrying `ASSET_HEADER`, and
entry.py swaps in the file from the assets binding, so a multi-megabyte wasm
bundle never passes through Python.
"""

import logging
import secrets
import time
from collections.abc import Callable
from urllib.parse import parse_qsl

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import oauth, pages
from .app import (COOKIE, FRESH_MINUTES, SESSION_COOKIE_MAX_AGE, SESSION_IDLE_LIMIT,
                  App, article_json, feed_json)
from .feeds import USER_AGENT
from .htmlclean import ScrapeError, extract_article
from .opml import OpmlFeed, parse_opml, render_opml

log = logging.getLogger("pulseboard")

ASSET_HEADER = "X-Pulseboard-Asset"
API_ROOTS = {"feeds", "articles", "unread", "opml", "refresh", "read",
             "read-all", "fetch-content"}
# Starlette's own cap on a form field is 1 MB; OPML has its own, below.
MAX_OPML = 1_000_000
MAX_FORM_PART = 2 * MAX_OPML


class Params:
    """Query string and form body together. Clients send parameters in
    either, as they did to the Nim reader, so routes read them from here
    rather than declaring them as one or the other."""

    def __init__(self, items: list[tuple[str, str]]):
        self.items = items

    def get(self, name: str, default: str = "") -> str:
        for k, v in self.items:
            if k == name:
                return v
        return default

    def get_int(self, name: str, default: int) -> int:
        try:
            return int(self.get(name))
        except ValueError:
            return default

    def as_dict(self) -> dict:
        return dict(self.items)


async def params(request: Request) -> Params:
    items = list(request.query_params.multi_items())
    if request.method in ("POST", "PUT", "DELETE"):
        ctype = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
            form = await request.form(max_part_size=MAX_FORM_PART)
            items += [(k, v) for k, v in form.multi_items() if isinstance(v, str)]
        elif not ctype:
            items += parse_qsl((await request.body()).decode("utf-8", "replace"),
                               keep_blank_values=True)
    return Params(items)


# Dependencies and routes are all `async def`: FastAPI runs plain functions
# on a thread pool, and Pyodide has no threads.
async def services(request: Request) -> App:
    return request.app.state.make_app(request)


def origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


class NotSignedIn(Exception):
    pass


async def current_user(request: Request, app: App = Depends(services)) -> str:
    user = await app.session_user(request.cookies.get(COOKIE, ""))
    if not user:
        raise NotSignedIn()
    return user


def fail(status: int, msg: str) -> JSONResponse:
    return JSONResponse({"error": msg}, status)


def asset(path: str) -> Response:
    return Response(status_code=200, headers={ASSET_HEADER: path})


def redirect(location: str, status: int = 303, cookie: str | None = None) -> Response:
    resp = RedirectResponse(location, status)
    if cookie is not None:
        resp.headers["Set-Cookie"] = cookie
    return resp


def session_cookie(token: str, max_age: int) -> str:
    return f"{COOKIE}={token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={max_age}"


def create_api(make_app: Callable[[Request], App]) -> FastAPI:
    # No generated docs: the API is for the Qt client, and /docs would only
    # be one more path to keep behind sign-in.
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    api.state.make_app = make_app
    install_error_handlers(api)
    add_routes(api)
    return api


def install_error_handlers(api: FastAPI):
    # Errors keep the reader's shape, {"error": "..."}, rather than FastAPI's
    # {"detail": ...}: the client shows `error` to the reader.
    @api.exception_handler(NotSignedIn)
    async def not_signed_in(request: Request, exc: NotSignedIn):
        if request.url.path in ("/", "/index.html"):
            return redirect("/auth/login", 307)
        return fail(401, "AT Protocol authentication required")

    @api.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        msg = {404: "not found", 405: "method not allowed"}.get(exc.status_code, str(exc.detail))
        return fail(exc.status_code, msg)

    @api.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        return fail(400, "bad request")

    @api.exception_handler(Exception)
    async def internal(request: Request, exc: Exception):
        log.exception("%s %s failed: %s", request.method, request.url.path, exc)
        return fail(500, "internal error")


def add_routes(api: FastAPI):  # noqa: C901 - one function per route, below
    # --- auth ----------------------------------------------------------------

    @api.get("/health")
    async def health():
        return {"ok": True}

    @api.get("/oauth-client-metadata.json")
    async def client_metadata(request: Request):
        return oauth.client_metadata(origin(request))

    @api.get("/auth/login")
    async def login():
        return HTMLResponse(pages.login_page())

    @api.get("/auth/authorize")
    async def authorize(request: Request, p: Params = Depends(params),
                        app: App = Depends(services)):
        identity = p.get("identity").strip()
        if not identity or identity.startswith("did:"):
            return HTMLResponse(pages.login_page(identity, "Enter a handle, like you.bsky.social."), 400)
        try:
            url = await oauth.authorize(app.http, app.crypto, app.store, origin(request), identity)
        except oauth.OAuthError as exc:
            log.warning("auth/authorize failed for %s: %s", identity, exc)
            return HTMLResponse(pages.login_page(identity, str(exc)), 400)
        except Exception as exc:
            log.exception("auth/authorize failed for %s: %s", identity, exc)
            return HTMLResponse(pages.login_page(
                identity, "Couldn't start sign-in for that handle. Check it and try again."), 502)
        return redirect(url)

    @api.get("/auth/callback")
    async def callback(request: Request, p: Params = Depends(params),
                       app: App = Depends(services)):
        try:
            did = await oauth.callback(app.http, app.crypto, app.store, origin(request), p.as_dict())
        except oauth.OAuthError as exc:
            log.warning("auth/callback failed: %s", exc)
            return HTMLResponse(pages.retry_page(), 401)
        except Exception as exc:
            log.exception("auth/callback failed: %s", exc)
            return HTMLResponse(pages.login_page(error="Sign-in failed. Please try again."), 401)
        token = secrets.token_urlsafe(32)
        await app.store.create_session(token, did, int(time.time()) + SESSION_IDLE_LIMIT)
        return redirect("/", cookie=session_cookie(token, SESSION_COOKIE_MAX_AGE))

    @api.get("/auth/logout")
    async def logout(request: Request, app: App = Depends(services)):
        token = request.cookies.get(COOKIE, "")
        if token:
            await app.store.delete_session(token)
        return redirect("/auth/login", cookie=session_cookie("", 0))

    # --- the client ----------------------------------------------------------

    @api.get("/")
    @api.get("/index.html")
    async def client(user: str = Depends(current_user)):
        return asset("/")

    # --- feeds ---------------------------------------------------------------

    @api.get("/feeds")
    async def list_feeds(user: str = Depends(current_user), app: App = Depends(services)):
        return [feed_json(s) for s in await app.store.list_subscriptions(user)]

    @api.post("/feeds")
    async def subscribe(user: str = Depends(current_user), p: Params = Depends(params),
                        app: App = Depends(services)):
        url = p.get("url").strip()
        if not url:
            return fail(400, "url required")
        if not url.startswith(("http://", "https://")):
            return fail(400, "url must be http(s)")
        # Subscribe first so a feed that fails to fetch is still listed,
        # with its error visible, rather than vanishing.
        await app.store.upsert_feed(url)
        await app.store.subscribe(user, url, "", p.get("category"))
        added, err = await app.refresh_feed(url)
        if err:
            return {"feed_url": url, "added": 0, "error": err}
        return {"feed_url": url, "added": added}

    @api.put("/feeds")
    async def edit_feed(user: str = Depends(current_user), p: Params = Depends(params),
                        app: App = Depends(services)):
        """url names the subscription; new_url, title and category replace its
        fields (new_url defaults to url, so a rename leaves it)."""
        url = p.get("url").strip()
        if not url or not await app.store.get_subscription(user, url):
            return fail(404, "no such subscription")
        new_url = p.get("new_url").strip() or url
        if not new_url.startswith(("http://", "https://")):
            return fail(400, "url must be http(s)")
        if new_url != url and await app.store.get_subscription(user, new_url):
            return fail(409, "already subscribed to that URL")
        if new_url != url:
            await app.store.upsert_feed(new_url)
        await app.store.update_subscription(
            user, url, new_url, p.get("title").strip(), p.get("category").strip())
        if new_url == url:
            return {"feed_url": url, "added": 0}
        # The edit is saved either way; a fetch failure is reported alongside
        # rather than as "error", which the client takes to mean nothing changed.
        added, err = await app.refresh_feed(new_url)
        if err:
            return {"feed_url": new_url, "added": 0, "fetch_error": err}
        return {"feed_url": new_url, "added": added}

    @api.delete("/feeds")
    async def unsubscribe(user: str = Depends(current_user), p: Params = Depends(params),
                          app: App = Depends(services)):
        if not p.get("url"):
            return fail(400, "url required")
        await app.store.unsubscribe(user, p.get("url"))
        return {"ok": True}

    # --- OPML ----------------------------------------------------------------

    @api.get("/opml")
    async def export_opml(user: str = Depends(current_user), app: App = Depends(services)):
        subs = await app.store.list_subscriptions(user, 5000)
        body = render_opml([OpmlFeed(url=s["feed_url"], title=s["title"] or "",
                                     site_url=s["site_url"] or "",
                                     category=s["category"] or "") for s in subs])
        return Response(body, 200, {
            "Content-Disposition": "attachment; filename=pulseboard-subscriptions.opml",
        }, media_type="application/xml; charset=utf-8")

    @api.post("/opml")
    async def import_opml(user: str = Depends(current_user), p: Params = Depends(params),
                          app: App = Depends(services)):
        source = p.get("opml")
        if not source:
            return fail(400, "OPML required")
        if len(source) > MAX_OPML:
            return fail(413, "OPML is too large")
        try:
            imported = parse_opml(source)
        except ValueError as exc:
            return fail(400, f"invalid OPML: {exc}")
        added, errors, urls = 0, [], []
        for f in imported:
            if not f.url.startswith(("http://", "https://")):
                errors.append({"feed_url": f.url, "error": "not an http(s) URL"})
                continue
            await app.store.upsert_feed(f.url, f.title, f.site_url, f.description)
            if await app.store.subscribe(user, f.url, f.title, f.category):
                added += 1
            urls.append(f.url)
        # Past the per-request cap, the next refresh or cron run fetches them.
        errors += [{"feed_url": u, "error": e} for u, _, e in await app.refresh_many(urls) if e]
        return {"imported": len(imported), "added": added, "errors": errors}

    # --- articles ------------------------------------------------------------

    @api.get("/articles")
    async def list_articles(user: str = Depends(current_user), p: Params = Depends(params),
                            app: App = Depends(services)):
        limit = max(1, min(p.get_int("limit", 50), 500))
        q = p.get("q")
        if q:
            try:
                rows = await app.store.search_articles(user, q, limit)
            except Exception:
                rows = []  # FTS5 syntax error: no results, not a failure
        else:
            status = p.get("status")
            rows = await app.store.list_articles(
                user, status if status in ("all", "read") else "unread", p.get("feed"), limit)
        return [article_json(a) for a in rows]

    @api.get("/articles/{article_id}")
    async def get_article(article_id: str, user: str = Depends(current_user),
                          app: App = Depends(services)):
        try:
            a = await app.store.get_article(user, int(article_id))
        except ValueError:
            a = None
        return article_json(a) if a else fail(404, "no such article")

    @api.get("/unread")
    async def unread(user: str = Depends(current_user), app: App = Depends(services)):
        return {"count": await app.store.unread_count(user)}

    @api.post("/read")
    async def mark_read(user: str = Depends(current_user), p: Params = Depends(params),
                        app: App = Depends(services)):
        article_id = p.get_int("id", 0)
        if not article_id:
            return fail(400, "id required")
        await app.store.set_read(user, article_id, p.get("undo") != "1")
        return {"id": article_id}

    @api.post("/read-all")
    async def mark_all_read(user: str = Depends(current_user), p: Params = Depends(params),
                            app: App = Depends(services)):
        await app.store.mark_all_read(user, p.get("feed"))
        return {"unread": await app.store.unread_count(user)}

    @api.post("/refresh")
    async def refresh(user: str = Depends(current_user), p: Params = Depends(params),
                      app: App = Depends(services)):
        minutes = None if p.get("force") == "1" else FRESH_MINUTES
        results = await app.refresh_many(await app.store.stale_subscriptions(user, minutes))
        return {
            "added": sum(added for _, added, _ in results),
            "errors": [{"feed_url": u, "error": e} for u, _, e in results if e],
        }

    @api.post("/fetch-content")
    async def fetch_content(user: str = Depends(current_user), p: Params = Depends(params),
                            app: App = Depends(services)):
        article_id = p.get_int("id", 0)
        a = await app.store.get_article(user, article_id)
        if not a or not a["url"]:
            return fail(404, "no such article")
        if not a["url"].startswith(("http://", "https://")):
            return fail(400, "article has no http(s) URL")
        try:
            res = await app.http.request("GET", a["url"], headers={"User-Agent": USER_AGENT})
            if res.status != 200:
                return fail(502, f"HTTP {res.status}")
            text = extract_article(res.body.decode("utf-8", errors="replace"))
        except ScrapeError as exc:
            return fail(502, str(exc))
        except Exception as exc:
            return fail(502, f"fetching {a['url']}: {exc}")
        await app.store.update_full_content(article_id, text)
        return {"id": article_id, "content": text}

    # --- everything else: the client's own files -------------------------------

    @api.api_route("/{path:path}", methods=["GET", "HEAD"])
    async def static(path: str):
        # The client's files (wasm, js, css, icons) are public: they are code,
        # not data, and the browser must load them to show the sign-in
        # redirect at all. Unknown paths under an API root stay JSON 404s.
        if path.split("/", 1)[0] in API_ROOTS:
            raise HTTPException(404)
        return asset("/" + path)

