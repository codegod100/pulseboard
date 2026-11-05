"""Copy the reader's data from Cloudflare D1 (or a local SQLite file) into
Postgres (Neon).

    DATABASE_URL=postgresql://… python scripts/d1_to_postgres.py --d1 pulseboard
    DATABASE_URL=postgresql://… python scripts/d1_to_postgres.py --sqlite pulseboard.db

D1 is read with `npx wrangler d1 execute --remote --json`; if wrangler is not
signed in, it signs in through the browser first. A Cloudflare account with no
such database has nothing to copy, which is not an error. The Postgres schema is applied first if it
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
import tempfile

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
WRANGLER = ["npx", "--yes", "wrangler@4"]


class NoSuchDatabase(Exception):
    pass


class D1Source:
    """D1 through wrangler. Wrangler runs from an empty directory: next to
    worker/wrangler.toml it would take that file's placeholder database_id
    for a database of the same name instead of looking the name up."""

    def __init__(self, name: str):
        self.name = name
        self.cwd = tempfile.mkdtemp(prefix="pulseboard-d1-")
        who = self._wrangler("whoami", check=False)
        if "not authenticated" in (who.stdout + who.stderr).lower() or who.returncode:
            print("Signing in to Cloudflare (a browser window opens)...")
            subprocess.run(WRANGLER + ["login"], cwd=self.cwd, check=True)
        dbs = json.loads(self._wrangler("d1", "list", "--json").stdout)
        if not any(d.get("name") == name for d in dbs):
            names = ", ".join(d.get("name", "?") for d in dbs) or "none"
            raise NoSuchDatabase(
                f"This Cloudflare account has no D1 database called {name!r} "
                f"(it has: {names}), so there is nothing to copy.")

    def _wrangler(self, *args, check=True):
        res = subprocess.run(WRANGLER + list(args), cwd=self.cwd,
                             capture_output=True, text=True)
        if check and res.returncode:
            raise RuntimeError(f"wrangler {' '.join(args[:2])} failed:\n{res.stderr or res.stdout}")
        return res

    def query(self, sql: str) -> list[dict]:
        out = self._wrangler("d1", "execute", self.name, "--remote", "--json",
                             "--command", sql).stdout
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
    try:
        source = D1Source(args.d1) if args.d1 else SqliteSource(args.sqlite)
    except NoSuchDatabase as exc:
        print(exc)
        return
    try:
        asyncio.run(copy(source, url))
    except RuntimeError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
