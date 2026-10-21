"""Turn the Modal-era reader's article database into SQL for D1.

    python scripts/import_modal.py pulseboard_articles > import.sql

Carries over feeds, subscriptions and which articles were read. Articles
themselves are not copied: the feeds are fetched again, and read state is
matched to them by (feed_url, guid) through read_state_history as they arrive.
Safe to run more than once; nothing already in D1 is overwritten.
"""

import sqlite3
import sys


def q(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def statements(db: sqlite3.Connection):
    for row in db.execute(
            "SELECT feed_url, title, site_url, description, feed_type, favicon_url FROM feeds"):
        yield ("INSERT INTO feeds (feed_url, title, site_url, description, feed_type, favicon_url) "
               f"VALUES ({', '.join(map(q, row))}) ON CONFLICT(feed_url) DO NOTHING;")
    for row in db.execute(
            "SELECT user_did, feed_url, title, category, added_at FROM subscriptions"):
        yield ("INSERT INTO subscriptions (user_did, feed_url, title, category, added_at) "
               f"VALUES ({', '.join(map(q, row))}) ON CONFLICT(user_did, feed_url) DO NOTHING;")
    for row in db.execute(
            """SELECT r.user_did, a.feed_url, a.guid, r.is_read, r.read_at
               FROM read_state r JOIN articles a ON a.id = r.article_id
               WHERE r.is_read = 1"""):
        yield ("INSERT INTO read_state_history (user_did, feed_url, guid, is_read, read_at) "
               f"VALUES ({', '.join(map(q, row))}) ON CONFLICT DO NOTHING;")
    yield ("UPDATE feeds SET subscriber_count = "
           "(SELECT count(*) FROM subscriptions s WHERE s.feed_url = feeds.feed_url);")


def main(path: str):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    for stmt in statements(db):
        print(stmt)


if __name__ == "__main__":
    main(sys.argv[1])
