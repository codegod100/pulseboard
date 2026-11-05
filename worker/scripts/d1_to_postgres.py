"""Copy the reader's data from Cloudflare D1 (or a local SQLite file) into
Postgres (Neon).

    DATABASE_URL=postgresql://… python scripts/d1_to_postgres.py --d1 pulseboard
    DATABASE_URL=postgresql://… python scripts/d1_to_postgres.py --sqlite pulseboard.db

D1 is read with `npx wrangler d1 execute --remote --json`, so wrangler must be
signed in (`npx wrangler login`). The Postgres schema is applied first if it
is missing. Rows that already exist are left alone, so it is safe to run
again. Sessions and pending sign-ins are not copied: the new deployment has a
new origin, so everyone signs in again anyway.
"""

import argparse
import asyncio
import json
import os
import pathlib
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from pulseboard.databases import PostgresDb, _pg_sql, migrate  # noqa: E402

# Parents before children; (table, ordering) for stable paging.
TABLES = [
    ("users", "did"),
    ("feeds", "feed_url"),
    ("subscriptions", "id"),
    ("articles", "id"),
    ("read_state", "user_did, article_id"),
    ("read_state_history", "user_did, feed_url, guid"),
]
IDENTITY = ["subscriptions", "articles"]
PAGE = 200


class D1Source:
    def __init__(self, name: str):
        self.name = name

    def query(self, sql: str) -> list[dict]:
        out = subprocess.run(
            ["npx", "--yes", "wrangler@4", "d1", "execute", self.name, "--remote",
             "--json", "--command", sql],
            check=True, capture_output=True, text=True).stdout
        return json.loads(out)[0]["results"]


class SqliteSource:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    def query(self, sql: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql).fetchall()]


async def copy(source, database_url: str, log=print) -> dict[str, int]:
    """Returns the rows inserted per table."""
    pg = PostgresDb(database_url, max_size=2)
    await pg.open()
    try:
        applied = await migrate(pg)
        if applied:
            log(f"applied the Postgres schema: {', '.join(applied)}")
        counts = {}
        for table, order in TABLES:
            cols = {r["column_name"] for r in await pg.all(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = ? AND is_generated = 'NEVER'", [table])}
            inserted, offset = 0, 0
            while True:
                rows = source.query(f"SELECT * FROM {table} ORDER BY {order} LIMIT {PAGE} OFFSET {offset}")
                if not rows:
                    break
                names = [c for c in rows[0] if c in cols]
                sql = (f"INSERT INTO {table} ({', '.join(names)}) "
                       f"VALUES ({', '.join('?' for _ in names)}) ON CONFLICT DO NOTHING")
                async with pg.pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
                    await cur.executemany(_pg_sql(sql), [[row[c] for c in names] for row in rows])
                    inserted += max(cur.rowcount, 0)
                offset += len(rows)
                log(f"{table}: {offset} read, {inserted} new", end="\r")
            log(f"{table}: {offset} read, {inserted} new")
            counts[table] = inserted
        # Copied ids came with the rows; new ones must start after them.
        for table in IDENTITY:
            await pg.run(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                         f"GREATEST((SELECT max(id) FROM {table}), 1))")
        return counts
    finally:
        await pg.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--d1", metavar="NAME", help="the D1 database's name (pulseboard)")
    src.add_argument("--sqlite", metavar="PATH", help="a local SQLite file")
    args = ap.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL to the Neon connection string.")
    source = D1Source(args.d1) if args.d1 else SqliteSource(args.sqlite)
    asyncio.run(copy(source, url))


if __name__ == "__main__":
    main()
