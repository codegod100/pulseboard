"""Routes. The same JSON API the Nim reader served, so clients need not care
which one is behind them.

This module knows nothing about Workers: `handle` takes a `Req` and returns a
`Resp`, and entry.py converts both ways. A `Resp` with `asset` set means "serve
this path from the static assets" (the ultra web client).
"""

import json
import logging
import secrets
import time
from dataclasses import dataclass, field

from . import oauth, pages
from .feeds import FeedError, fetch_feed, USER_AGENT
from .htmlclean import ScrapeError, extract_article, sanitize_fragment
from .opml import OpmlFeed, parse_opml, render_opml
from .store import Store, iso_time

log = logging.getLogger("pulseboard")

# A session ends after this long without use; every authenticated request
# pushes the expiry forward, at most once a day.
SESSION_IDLE_LIMIT = 30 * 24 * 60 * 60
SESSION_RENEW_EVERY = 24 * 60 * 60
# The cookie only carries the token; the row decides whether it is still good.
# Browsers cap Max-Age at 400 days.
SESSION_COOKIE_MAX_AGE = 400 * 24 * 60 * 60
COOKIE = "pulseboard_session"

API_ROOTS = {"feeds", "articles", "unread", "opml", "refresh", "read",
             "read-all", "fetch-content"}

# How many feeds one request may fetch. Workers cap subrequests per invocation,
# and each feed is one or more of them.
MAX_FEEDS_PER_REQUEST = 40


@dataclass
class Req:
    method: str
    path: str  # without the leading or trailing slash
    params: list[tuple[str, str]] = field(default_factory=list)  # query + form
    cookie: str = ""
    origin: str = ""

    def param(self, name: str, default: str = "") -> str:
        for k, v in self.params:
            if k == name:
                return v
        return default

    def int_param(self, name: str, default: int) -> int:
        try:
            return int(self.param(name))
        except ValueError:
            return default

    def cookie_value(self, name: str) -> str:
        for part in self.cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""


@dataclass
class Resp:
    status: int = 200
    body: str | bytes = ""
    headers: dict = field(default_factory=dict)
    asset: str | None = None


def json_resp(data, status: int = 200) -> Resp:
    return Resp(status, json.dumps(data), {"Content-Type": "application/json"})


def fail(status: int, msg: str) -> Resp:
    return json_resp({"error": msg}, status)


def html_resp(markup: str, status: int = 200) -> Resp:
    return Resp(status, markup, {"Content-Type": "text/html; charset=utf-8"})


def redirect(location: str, status: int = 303, **headers) -> Resp:
    return Resp(status, "", {"Location": location, **headers})


def article_json(a: dict) -> dict:
    return {
        "id": a["id"],
        "feed_url": a["feed_url"],
        "feed_title": a["feed_title"] or a["feed_url"],
        "title": a["title"] or "",
        "url": a["url"] or "",
        "author": a["author"] or "",
        "summary": a["summary"] or "",
        # Sanitised on the way out, whichever source it came from.
        "content": sanitize_fragment(a["full_content"] or a["content"] or ""),
        "published": iso_time(a["published"]),
        "is_read": bool(a["is_read"]),
    }


def feed_json(s: dict) -> dict:
    return {
        "feed_url": s["feed_url"],
        "title": s["title"] or s["feed_url"],
        "category": s["category"] or "",
        "unread": int(s["unread"] or 0),
        "favicon_url": s["favicon_url"] or "",
        "site_url": s["site_url"] or "",
        "error": s["last_error"] or "",
    }


class App:
    def __init__(self, db, http, crypto):
        self.store = Store(db)
        self.http = http
        self.crypto = crypto

    # --- feed refresh --------------------------------------------------------

    async def refresh_feed(self, feed_url: str) -> tuple[int, str]:
        """Fetch one feed and store what came back. A failure is recorded on
        the feed rather than raised: one unreachable feed should not stop a
        refresh of the others. Returns (articles seen, error)."""
        try:
            parsed = await fetch_feed(self.http, feed_url)
        except FeedError as exc:
            await self.store.mark_fetch_error(feed_url, str(exc))
            return 0, str(exc)
        await self.store.upsert_articles(feed_url, parsed)
        await self.store.upsert_feed(
            feed_url, parsed.title, parsed.site_url, parsed.description,
            parsed.kind, parsed.favicon_url)
        await self.store.mark_fetched(feed_url)
        return len(parsed.articles), ""

    async def refresh_for_user(self, user_did: str, feed_url: str) -> tuple[int, str]:
        before = await self.store.unread_count(user_did, feed_url)
        _, err = await self.refresh_feed(feed_url)
        if err:
            return 0, err
        return max(await self.store.unread_count(user_did, feed_url) - before, 0), ""

    async def scheduled(self, older_than_minutes: int = 30, limit: int = MAX_FEEDS_PER_REQUEST):
        """The cron trigger: refresh whatever is due, oldest first."""
        await self.store.purge_expired(int(time.time()))
        for url in await self.store.feeds_to_fetch(older_than_minutes, limit):
            await self.refresh_feed(url)

    # --- auth ----------------------------------------------------------------

    async def session_user(self, req: Req) -> str:
        token = req.cookie_value(COOKIE)
        if not token:
            return ""
        return await self.store.session_user(
            token, int(time.time()), SESSION_IDLE_LIMIT, SESSION_RENEW_EVERY)

    async def auth_routes(self, req: Req) -> Resp | None:
        path = req.path
        if req.method != "GET":
            return None
        if path == "oauth-client-metadata.json":
            return json_resp(oauth.client_metadata(req.origin))
        if path == "auth/login":
            return html_resp(pages.login_page())
        if path == "auth/authorize":
            identity = req.param("identity").strip()
            if not identity or identity.startswith("did:"):
                return html_resp(pages.login_page(identity, "Enter a handle, like you.bsky.social."), 400)
            try:
                url = await oauth.authorize(self.http, self.crypto, self.store, req.origin, identity)
            except oauth.OAuthError as exc:
                log.warning("auth/authorize failed for %s: %s", identity, exc)
                return html_resp(pages.login_page(identity, str(exc)), 400)
            except Exception as exc:
                log.exception("auth/authorize failed for %s: %s", identity, exc)
                return html_resp(pages.login_page(
                    identity, "Couldn't start sign-in for that handle. Check it and try again."), 502)
            return redirect(url)
        if path == "auth/callback":
            try:
                did = await oauth.callback(self.http, self.crypto, self.store, req.origin, dict(req.params))
            except oauth.OAuthError as exc:
                log.warning("auth/callback failed: %s", exc)
                return html_resp(pages.retry_page(), 401)
            except Exception as exc:
                log.exception("auth/callback failed: %s", exc)
                return html_resp(pages.login_page(error="Sign-in failed. Please try again."), 401)
            token = secrets.token_urlsafe(32)
            await self.store.create_session(token, did, int(time.time()) + SESSION_IDLE_LIMIT)
            return redirect("/", **{"Set-Cookie": (
                f"{COOKIE}={token}; Path=/; HttpOnly; Secure; SameSite=Lax; "
                f"Max-Age={SESSION_COOKIE_MAX_AGE}")})
        if path == "auth/logout":
            token = req.cookie_value(COOKIE)
            if token:
                await self.store.delete_session(token)
            return redirect("/auth/login", **{"Set-Cookie": (
                f"{COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0")})
        if path == "health":
            return json_resp({"ok": True})
        return None

    # --- routes --------------------------------------------------------------

    async def handle(self, req: Req) -> Resp:
        resp = await self.auth_routes(req)
        if resp is not None:
            return resp

        root = req.path.split("/", 1)[0]
        is_app = req.path in ("", "index.html")
        if root not in API_ROOTS and not is_app:
            # The client's own files (wasm, js, css, icons) are public: they
            # are code, not data, and the browser must be able to load them
            # to show the sign-in redirect at all.
            return Resp(asset="/" + req.path) if req.method in ("GET", "HEAD") else fail(404, "not found")

        user = await self.session_user(req)
        if not user:
            if is_app:
                return redirect("/auth/login", 307)
            return fail(401, "AT Protocol authentication required")
        if is_app:
            return Resp(asset="/")

        method = req.method
        try:
            if method == "GET":
                return await self.get(req, user)
            if method == "POST":
                return await self.post(req, user)
            if method == "DELETE":
                if root == "feeds" and req.param("url"):
                    await self.store.unsubscribe(user, req.param("url"))
                    return json_resp({"ok": True})
                return fail(400, "url required")
        except Exception as exc:
            log.exception("%s /%s failed: %s", method, req.path, exc)
            return fail(500, "internal error")
        return fail(405, "method not allowed")

    async def get(self, req: Req, user: str) -> Resp:
        segs = req.path.split("/")
        root = segs[0]
        if root == "feeds":
            return json_resp([feed_json(s) for s in await self.store.list_subscriptions(user)])
        if root == "opml":
            subs = await self.store.list_subscriptions(user, 5000)
            body = render_opml([OpmlFeed(url=s["feed_url"], title=s["title"] or "",
                                         site_url=s["site_url"] or "",
                                         category=s["category"] or "") for s in subs])
            return Resp(200, body, {
                "Content-Type": "application/xml; charset=utf-8",
                "Content-Disposition": "attachment; filename=pulseboard-subscriptions.opml",
            })
        if root == "articles":
            if len(segs) == 2:
                try:
                    article_id = int(segs[1])
                except ValueError:
                    return fail(404, "no such article")
                a = await self.store.get_article(user, article_id)
                return json_resp(article_json(a)) if a else fail(404, "no such article")
            limit = max(1, min(req.int_param("limit", 50), 500))
            q = req.param("q")
            if q:
                try:
                    rows = await self.store.search_articles(user, q, limit)
                except Exception:
                    rows = []  # FTS5 syntax error: no results, not a failure
            else:
                status = req.param("status")
                rows = await self.store.list_articles(
                    user, status if status in ("all", "read") else "unread",
                    req.param("feed"), limit)
            return json_resp([article_json(a) for a in rows])
        if root == "unread":
            return json_resp({"count": await self.store.unread_count(user)})
        return fail(404, "not found")

    async def post(self, req: Req, user: str) -> Resp:
        root = req.path.split("/", 1)[0]
        if root == "feeds":
            url = req.param("url").strip()
            if not url:
                return fail(400, "url required")
            if not url.startswith(("http://", "https://")):
                return fail(400, "url must be http(s)")
            # Subscribe first so a feed that fails to fetch is still listed,
            # with its error visible, rather than vanishing.
            await self.store.upsert_feed(url)
            await self.store.subscribe(user, url, "", req.param("category"))
            added, err = await self.refresh_for_user(user, url)
            if err:
                return json_resp({"feed_url": url, "added": 0, "error": err})
            return json_resp({"feed_url": url, "added": added})

        if root == "opml":
            source = req.param("opml")
            if not source:
                return fail(400, "OPML required")
            if len(source) > 1_000_000:
                return fail(413, "OPML is too large")
            try:
                imported = parse_opml(source)
            except ValueError as exc:
                return fail(400, f"invalid OPML: {exc}")
            added, errors = 0, []
            for i, f in enumerate(imported):
                if not f.url.startswith(("http://", "https://")):
                    errors.append({"feed_url": f.url, "error": "not an http(s) URL"})
                    continue
                await self.store.upsert_feed(f.url, f.title, f.site_url, f.description)
                if await self.store.subscribe(user, f.url, f.title, f.category):
                    added += 1
                # The rest are fetched by the next refresh or cron run.
                if i < MAX_FEEDS_PER_REQUEST:
                    _, err = await self.refresh_feed(f.url)
                    if err:
                        errors.append({"feed_url": f.url, "error": err})
            return json_resp({"imported": len(imported), "added": added, "errors": errors})

        if root == "refresh":
            total, errors = 0, []
            subs = await self.store.list_subscriptions(user)
            for s in subs[:MAX_FEEDS_PER_REQUEST]:
                added, err = await self.refresh_for_user(user, s["feed_url"])
                total += added
                if err:
                    errors.append({"feed_url": s["feed_url"], "error": err})
            return json_resp({"added": total, "errors": errors})

        if root == "read":
            article_id = req.int_param("id", 0)
            if not article_id:
                return fail(400, "id required")
            await self.store.set_read(user, article_id, req.param("undo") != "1")
            return json_resp({"id": article_id})

        if root == "read-all":
            await self.store.mark_all_read(user, req.param("feed"))
            return json_resp({"unread": await self.store.unread_count(user)})

        if root == "fetch-content":
            article_id = req.int_param("id", 0)
            a = await self.store.get_article(user, article_id)
            if not a or not a["url"]:
                return fail(404, "no such article")
            if not a["url"].startswith(("http://", "https://")):
                return fail(400, "article has no http(s) URL")
            try:
                res = await self.http.request("GET", a["url"], headers={"User-Agent": USER_AGENT})
                if res.status != 200:
                    return fail(502, f"HTTP {res.status}")
                text = extract_article(res.body.decode("utf-8", errors="replace"))
            except ScrapeError as exc:
                return fail(502, str(exc))
            except Exception as exc:
                return fail(502, f"fetching {a['url']}: {exc}")
            await self.store.update_full_content(article_id, text)
            return json_resp({"id": article_id, "content": text})

        return fail(404, "not found")
