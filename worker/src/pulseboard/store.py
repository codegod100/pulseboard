"""Feeds, subscriptions, articles and read state on D1.

Ported from the Nim reader's stores. Read state is per-user and lives in its
own table, so "the article list" is always a LEFT JOIN: an article with no
read_state row is unread.

`db` is anything with the four async methods below. The Worker passes a D1
adapter; the tests pass one over the standard library's sqlite3.

    all(sql, params) -> list[dict]
    first(sql, params) -> dict | None
    run(sql, params) -> int            rows changed
    batch([(sql, params), ...])        one implicit transaction
"""

from datetime import datetime, timezone

from .feeds import ParsedFeed

SQLITE_TIME = "%Y-%m-%d %H:%M:%S"

ARTICLE_COLUMNS = """
  a.id, a.feed_url, COALESCE(f.title, a.feed_url) AS feed_title,
  f.favicon_url AS feed_favicon_url, a.guid, a.title, a.url, a.author,
  a.summary, a.content, a.full_content, a.published, a.updated,
  COALESCE(r.is_read, 0) AS is_read"""

ARTICLE_FROM = """
  FROM articles a
  LEFT JOIN feeds f ON f.feed_url = a.feed_url
  LEFT JOIN read_state r ON r.article_id = a.id AND r.user_did = ?"""


def sqlite_time(t: datetime | None) -> str | None:
    return t.astimezone(timezone.utc).strftime(SQLITE_TIME) if t else None


def iso_time(s: str | None) -> str:
    """SQLite's "YYYY-MM-DD HH:MM:SS" (UTC) as ISO 8601, which is what the
    clients parse."""
    if not s:
        return ""
    return s.replace(" ", "T", 1) + ("" if s.endswith("Z") else "Z")


class Store:
    def __init__(self, db):
        self.db = db

    # --- articles ------------------------------------------------------------

    async def get_article(self, user_did: str, article_id: int) -> dict | None:
        return await self.db.first(
            f"SELECT {ARTICLE_COLUMNS} {ARTICLE_FROM} WHERE a.id = ?",
            [user_did, article_id],
        )

    async def list_articles(self, user_did: str, status: str = "unread",
                            feed_url: str = "", limit: int = 50) -> list[dict]:
        sql = f"""SELECT {ARTICLE_COLUMNS} {ARTICLE_FROM}
          JOIN subscriptions s ON s.feed_url = a.feed_url AND s.user_did = ?
          WHERE 1=1"""
        params: list = [user_did, user_did]
        if status == "unread":
            sql += " AND COALESCE(r.is_read, 0) = 0"
        elif status == "read":
            sql += " AND COALESCE(r.is_read, 0) = 1"
        if feed_url:
            sql += " AND a.feed_url = ?"
            params.append(feed_url)
        # NULL published sorts last: an undated article is almost always a
        # parse failure, and burying it beats putting it at the top.
        sql += " ORDER BY a.published IS NULL, a.published DESC, a.id DESC LIMIT ?"
        params.append(limit)
        return await self.db.all(sql, params)

    async def search_articles(self, user_did: str, query: str, limit: int = 50) -> list[dict]:
        """Full-text search over the user's subscriptions. The query goes to
        FTS5 as-is, so a stray quote is a syntax error: callers treat an error
        as no results."""
        if not query.strip():
            return []
        return await self.db.all(
            f"""SELECT {ARTICLE_COLUMNS} {ARTICLE_FROM}
              JOIN subscriptions s ON s.feed_url = a.feed_url AND s.user_did = ?
              JOIN (SELECT rowid, rank FROM articles_fts
                    WHERE articles_fts MATCH ?) m ON m.rowid = a.id
              ORDER BY m.rank LIMIT ?""",
            [user_did, user_did, query, limit],
        )

    async def upsert_articles(self, feed_url: str, parsed: ParsedFeed):
        stmts = []
        for a in parsed.articles:
            if not a.guid:
                continue
            stmts.append((
                """INSERT INTO articles
                   (feed_url, guid, title, url, author, summary, content, published, updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(feed_url, guid) DO NOTHING""",
                [feed_url, a.guid, a.title, a.url or None, a.author or None,
                 a.summary or None, a.content or None,
                 sqlite_time(a.published), sqlite_time(a.updated)],
            ))
        # Read state carried over from elsewhere (an import) is keyed on
        # (feed_url, guid); attach it to whatever ids the articles got.
        stmts.append((
            """INSERT INTO read_state (user_did, article_id, is_read, read_at)
               SELECT h.user_did, a.id, h.is_read, h.read_at
               FROM read_state_history h
               JOIN articles a ON a.feed_url = h.feed_url AND a.guid = h.guid
               WHERE h.feed_url = ?
               ON CONFLICT(user_did, article_id) DO NOTHING""",
            [feed_url],
        ))
        for i in range(0, len(stmts), 50):
            await self.db.batch(stmts[i:i + 50])

    async def update_full_content(self, article_id: int, content: str):
        await self.db.run("UPDATE articles SET full_content = ? WHERE id = ?",
                          [content or None, article_id])

    # --- read state ----------------------------------------------------------

    async def set_read(self, user_did: str, article_id: int, is_read: bool):
        await self.db.run(
            """INSERT INTO read_state (user_did, article_id, is_read, read_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_did, article_id) DO UPDATE SET
                 is_read = excluded.is_read, read_at = excluded.read_at""",
            [user_did, article_id, 1 if is_read else 0],
        )

    async def mark_all_read(self, user_did: str, feed_url: str = ""):
        # Two statements, not one with an optional predicate: getting this scope
        # wrong clears the whole account instead of one feed.
        if feed_url:
            await self.db.run(
                """INSERT INTO read_state (user_did, article_id, is_read, read_at)
                   SELECT ?, a.id, 1, CURRENT_TIMESTAMP FROM articles a
                   WHERE a.feed_url = ?
                   ON CONFLICT(user_did, article_id) DO UPDATE SET
                     is_read = 1, read_at = CURRENT_TIMESTAMP""",
                [user_did, feed_url],
            )
        else:
            await self.db.run(
                """INSERT INTO read_state (user_did, article_id, is_read, read_at)
                   SELECT ?, a.id, 1, CURRENT_TIMESTAMP FROM articles a
                   JOIN subscriptions s ON s.feed_url = a.feed_url AND s.user_did = ?
                   ON CONFLICT(user_did, article_id) DO UPDATE SET
                     is_read = 1, read_at = CURRENT_TIMESTAMP""",
                [user_did, user_did],
            )

    async def unread_count(self, user_did: str, feed_url: str = "") -> int:
        sql = """SELECT count(*) AS n FROM articles a
          JOIN subscriptions s ON s.feed_url = a.feed_url AND s.user_did = ?
          LEFT JOIN read_state r ON r.article_id = a.id AND r.user_did = ?
          WHERE COALESCE(r.is_read, 0) = 0"""
        params: list = [user_did, user_did]
        if feed_url:
            sql += " AND a.feed_url = ?"
            params.append(feed_url)
        row = await self.db.first(sql, params)
        return int(row["n"]) if row else 0

    # --- feeds ---------------------------------------------------------------

    async def upsert_feed(self, feed_url: str, title: str = "", site_url: str = "",
                          description: str = "", feed_type: str = "",
                          favicon_url: str = ""):
        # subscriber_count and the error columns are owned by subscribe and by
        # the fetcher; a metadata refresh that reset them would revive dead feeds.
        await self.db.run(
            """INSERT INTO feeds (feed_url, title, site_url, description, feed_type, favicon_url)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(feed_url) DO UPDATE SET
                 title = COALESCE(excluded.title, feeds.title),
                 site_url = COALESCE(excluded.site_url, feeds.site_url),
                 description = COALESCE(excluded.description, feeds.description),
                 feed_type = COALESCE(excluded.feed_type, feeds.feed_type),
                 favicon_url = COALESCE(excluded.favicon_url, feeds.favicon_url)""",
            [feed_url, title or None, site_url or None, description or None,
             feed_type or None, favicon_url or None],
        )

    async def mark_fetched(self, feed_url: str, etag: str = "", last_modified: str = ""):
        await self.db.run(
            """UPDATE feeds SET last_fetched_at = CURRENT_TIMESTAMP,
                 last_error = NULL, error_count = 0,
                 etag = ?, last_modified = ? WHERE feed_url = ?""",
            [etag or None, last_modified or None, feed_url],
        )

    async def validators(self, feed_url: str) -> tuple[str, str]:
        row = await self.db.first(
            "SELECT etag, last_modified FROM feeds WHERE feed_url = ?", [feed_url])
        return ((row["etag"] or "", row["last_modified"] or "") if row else ("", ""))

    async def count_articles(self, feed_url: str) -> int:
        row = await self.db.first(
            "SELECT count(*) AS n FROM articles WHERE feed_url = ?", [feed_url])
        return int(row["n"]) if row else 0

    async def stale_subscriptions(self, user_did: str, minutes: int | None) -> list[str]:
        """The user's feeds not fetched in the last `minutes` (all of them for
        None), least recently fetched first."""
        sql = """SELECT s.feed_url FROM subscriptions s
               LEFT JOIN feeds f ON f.feed_url = s.feed_url
               WHERE s.user_did = ?"""
        params: list = [user_did]
        if minutes is not None:
            sql += """ AND (f.last_fetched_at IS NULL
                            OR f.last_fetched_at < datetime('now', ?))"""
            params.append(f"-{int(minutes)} minutes")
        sql += " ORDER BY f.last_fetched_at IS NOT NULL, f.last_fetched_at"
        rows = await self.db.all(sql, params)
        return [r["feed_url"] for r in rows]

    async def mark_fetch_error(self, feed_url: str, error: str):
        await self.db.run(
            """UPDATE feeds SET last_fetched_at = CURRENT_TIMESTAMP,
                 last_error = ?, error_count = error_count + 1 WHERE feed_url = ?""",
            [error, feed_url],
        )

    async def feeds_to_fetch(self, older_than_minutes: int, limit: int) -> list[str]:
        """Feeds due for a refresh, oldest first. Feeds that keep failing drop
        out so a dead URL does not take a slot every cycle."""
        rows = await self.db.all(
            """SELECT feed_url FROM feeds
               WHERE subscriber_count > 0 AND error_count < 10
                 AND (last_fetched_at IS NULL
                      OR last_fetched_at < datetime('now', ?))
               ORDER BY last_fetched_at IS NOT NULL, last_fetched_at
               LIMIT ?""",
            [f"-{int(older_than_minutes)} minutes", limit],
        )
        return [r["feed_url"] for r in rows]

    # --- subscriptions -------------------------------------------------------

    async def _recount(self, feed_url: str):
        await self.db.run(
            """UPDATE feeds SET subscriber_count = (
                 SELECT count(*) FROM subscriptions WHERE feed_url = ?)
               WHERE feed_url = ?""",
            [feed_url, feed_url],
        )

    async def subscribe(self, user_did: str, feed_url: str, title: str = "",
                        category: str = "") -> bool:
        """Returns whether this was a new subscription."""
        existing = await self.get_subscription(user_did, feed_url)
        await self.db.run(
            """INSERT INTO subscriptions (user_did, feed_url, title, category)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_did, feed_url) DO UPDATE SET
                 title = COALESCE(excluded.title, subscriptions.title),
                 category = COALESCE(excluded.category, subscriptions.category)""",
            [user_did, feed_url, title or None, category or None],
        )
        await self._recount(feed_url)
        return existing is None

    async def unsubscribe(self, user_did: str, feed_url: str):
        await self.db.batch([
            ("DELETE FROM subscriptions WHERE user_did = ? AND feed_url = ?",
             [user_did, feed_url]),
            ("""UPDATE feeds SET subscriber_count = (
                  SELECT count(*) FROM subscriptions WHERE feed_url = ?)
                WHERE feed_url = ?""", [feed_url, feed_url]),
        ])

    async def update_subscription(self, user_did: str, feed_url: str, new_url: str,
                                  title: str, category: str):
        """Rename, recategorise, or move a subscription to another feed URL.
        An empty title falls back to the feed's own. On a move, the user's
        read state goes into read_state_history under the new URL, so articles
        the new feed shares with the old one (same guid) arrive already read."""
        stmts = []
        if new_url != feed_url:
            stmts.append((
                """INSERT INTO read_state_history (user_did, feed_url, guid, is_read, read_at)
                   SELECT r.user_did, ?, a.guid, r.is_read, r.read_at
                   FROM read_state r JOIN articles a ON a.id = r.article_id
                   WHERE r.user_did = ? AND a.feed_url = ?
                   ON CONFLICT(user_did, feed_url, guid) DO NOTHING""",
                [new_url, user_did, feed_url],
            ))
        stmts.append((
            """UPDATE subscriptions SET feed_url = ?, title = ?, category = ?
               WHERE user_did = ? AND feed_url = ?""",
            [new_url, title or None, category or None, user_did, feed_url],
        ))
        if new_url != feed_url:
            for url in (feed_url, new_url):
                stmts.append(("""UPDATE feeds SET subscriber_count = (
                      SELECT count(*) FROM subscriptions WHERE feed_url = ?)
                    WHERE feed_url = ?""", [url, url]))
        await self.db.batch(stmts)

    async def get_subscription(self, user_did: str, feed_url: str) -> dict | None:
        return await self.db.first(
            "SELECT id FROM subscriptions WHERE user_did = ? AND feed_url = ?",
            [user_did, feed_url],
        )

    async def list_subscriptions(self, user_did: str, limit: int = 500) -> list[dict]:
        """The unread count is computed per row rather than stored: it is
        per-user and changes constantly."""
        return await self.db.all(
            """SELECT s.feed_url,
                 COALESCE(s.title, f.title, s.feed_url) AS title,
                 COALESCE(s.category, '') AS category,
                 f.site_url, f.description, f.favicon_url, f.last_error,
                 (SELECT count(*) FROM articles a
                  LEFT JOIN read_state r
                    ON r.article_id = a.id AND r.user_did = s.user_did
                  WHERE a.feed_url = s.feed_url AND COALESCE(r.is_read, 0) = 0) AS unread
               FROM subscriptions s
               LEFT JOIN feeds f ON f.feed_url = s.feed_url
               WHERE s.user_did = ?
               ORDER BY COALESCE(s.title, f.title, s.feed_url) COLLATE NOCASE
               LIMIT ?""",
            [user_did, limit],
        )

    # --- users and sessions --------------------------------------------------

    async def create_session(self, token: str, did: str, expires_at: int):
        await self.db.batch([
            ("INSERT OR IGNORE INTO users (did) VALUES (?)", [did]),
            ("INSERT INTO web_sessions (token, user_did, expires_at) VALUES (?, ?, ?)",
             [token, did, expires_at]),
        ])

    async def session_user(self, token: str, now: int, idle_limit: int,
                           renew_every: int) -> str:
        """The session's DID, pushing its expiry forward at most once per
        `renew_every` seconds so a regular reader is never sent to sign in."""
        row = await self.db.first(
            "SELECT user_did, expires_at FROM web_sessions WHERE token = ? AND expires_at > ?",
            [token, now],
        )
        if not row:
            return ""
        if int(row["expires_at"]) < now + idle_limit - renew_every:
            await self.db.run("UPDATE web_sessions SET expires_at = ? WHERE token = ?",
                              [now + idle_limit, token])
        return row["user_did"]

    async def delete_session(self, token: str):
        await self.db.run("DELETE FROM web_sessions WHERE token = ?", [token])

    async def put_oauth_state(self, state: str, data: str, expires_at: int):
        await self.db.run(
            "INSERT INTO oauth_states (state, data, expires_at) VALUES (?, ?, ?)",
            [state, data, expires_at],
        )

    async def take_oauth_state(self, state: str, now: int) -> str | None:
        """Single use: the row is deleted whether or not it was still valid."""
        row = await self.db.first(
            "SELECT data, expires_at FROM oauth_states WHERE state = ?", [state])
        if not row:
            return None
        await self.db.run("DELETE FROM oauth_states WHERE state = ?", [state])
        return row["data"] if int(row["expires_at"]) > now else None

    async def purge_expired(self, now: int):
        await self.db.batch([
            ("DELETE FROM web_sessions WHERE expires_at <= ?", [now]),
            ("DELETE FROM oauth_states WHERE expires_at <= ?", [now]),
        ])
