"""The reader's services: feed refresh, sessions, and the JSON shapes the API
returns. The routes themselves are in api.py.

This module knows nothing about Workers or HTTP frameworks: `App` takes a
database, an HTTP client and a signer, which entry.py (D1, fetch, WebCrypto)
and the tests (SQLite, canned responses, `cryptography`) each provide.
"""

import asyncio
import logging
import time

from .feeds import FeedError, fetch_feed
from .htmlclean import sanitize_fragment
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

# How many feeds one request may fetch. Workers cap subrequests per invocation,
# and each feed is one or more of them.
MAX_FEEDS_PER_REQUEST = 40
# Feeds fetched at once. Most of a refresh is waiting on other people's
# servers, so doing them one after another is what made it slow.
FETCH_CONCURRENCY = 8
# The client refreshes every time it opens; a feed fetched this recently (by
# that or by the cron trigger) is not fetched again.
FRESH_MINUTES = 10


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
        refresh of the others. Returns (new articles, error)."""
        etag, last_modified = await self.store.validators(feed_url)
        try:
            parsed, etag, last_modified = await fetch_feed(
                self.http, feed_url, etag, last_modified)
        except FeedError as exc:
            log.warning("feed %s failed: %s", feed_url, exc)
            await self.store.mark_fetch_error(feed_url, str(exc))
            return 0, str(exc)
        except Exception as exc:
            log.exception("feed %s failed: %s", feed_url, exc)
            await self.store.mark_fetch_error(feed_url, f"internal error: {exc}")
            return 0, f"internal error: {exc}"
        if parsed is None:  # 304 Not Modified
            await self.store.mark_fetched(feed_url, etag, last_modified)
            return 0, ""
        before = await self.store.count_articles(feed_url)
        await self.store.upsert_articles(feed_url, parsed)
        await self.store.upsert_feed(
            feed_url, parsed.title, parsed.site_url, parsed.description,
            parsed.kind, parsed.favicon_url)
        await self.store.mark_fetched(feed_url, etag, last_modified)
        return max(await self.store.count_articles(feed_url) - before, 0), ""

    async def refresh_many(self, urls: list[str]) -> list[tuple[str, int, str]]:
        """Refresh several feeds concurrently. Returns (url, added, error)."""
        gate = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def one(url):
            async with gate:
                added, err = await self.refresh_feed(url)
                return url, added, err

        return list(await asyncio.gather(*(one(u) for u in urls[:MAX_FEEDS_PER_REQUEST])))

    async def scheduled(self, older_than_minutes: int = 30, limit: int = MAX_FEEDS_PER_REQUEST):
        """The cron trigger: refresh whatever is due, oldest first."""
        await self.store.purge_expired(int(time.time()))
        await self.refresh_many(await self.store.feeds_to_fetch(older_than_minutes, limit))

    # --- auth ----------------------------------------------------------------

    async def session_user(self, token: str) -> str:
        if not token:
            return ""
        return await self.store.session_user(
            token, int(time.time()), SESSION_IDLE_LIMIT, SESSION_RENEW_EVERY)
