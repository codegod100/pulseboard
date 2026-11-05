"""Databases for running outside Cloudflare: Postgres (Neon) for production,
and a local SQLite file for development and tests.

Both have the interface `Store` expects, the same one entry.py gives D1:
`all`, `first`, `run`, `batch`, plus `script` for migrations, `dialect` for
the SQL that differs, and `migrations`, the schema directory for that dialect.
"""

import datetime
import pathlib
import sqlite3

from .store import PostgresDialect, SqliteDialect

MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent.parent / "migrations"
MIGRATIONS_POSTGRES = MIGRATIONS.parent / "migrations-postgres"


class SqliteDb:
    """A local SQLite file (or ":memory:"). Calls are synchronous inside the
    async methods: fine for development and tests, not for production."""

    dialect = SqliteDialect()
    migrations = MIGRATIONS

    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    async def all(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, list(params)).fetchall()]

    async def first(self, sql, params=()):
        rows = await self.all(sql, params)
        return rows[0] if rows else None

    async def run(self, sql, params=()):
        cur = self.conn.execute(sql, list(params))
        self.conn.commit()
        return cur.rowcount

    async def batch(self, statements):
        with self.conn:
            for sql, params in statements:
                self.conn.execute(sql, list(params))

    async def script(self, sql):
        self.conn.executescript(sql)

    async def open(self):
        pass

    async def close(self):
        self.conn.close()


def _pg_sql(sql: str) -> str:
    """`?` placeholders to psycopg's `%s` (no query has a literal `?`)."""
    return sql.replace("%", "%%").replace("?", "%s")


def _pg_value(v):
    # Timestamps read back the way SQLite gives them, which is what
    # store.iso_time and the rest expect.
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return v


class PostgresDb:
    """Postgres (Neon) through a psycopg connection pool. Server-side prepared
    statements are off, so Neon's pooled (PgBouncer) endpoint works."""

    dialect = PostgresDialect()
    migrations = MIGRATIONS_POSTGRES

    def __init__(self, url: str, max_size: int = 5):
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        self.pool = AsyncConnectionPool(
            url, min_size=1, max_size=max_size, open=False,
            kwargs={"row_factory": dict_row, "prepare_threshold": None, "autocommit": True})

    async def open(self):
        await self.pool.open(wait=True, timeout=30)

    async def all(self, sql, params=()):
        async with self.pool.connection() as conn:
            cur = await conn.execute(_pg_sql(sql), list(params))
            rows = await cur.fetchall() if cur.description else []
        return [{k: _pg_value(v) for k, v in r.items()} for r in rows]

    async def first(self, sql, params=()):
        rows = await self.all(sql, params)
        return rows[0] if rows else None

    async def run(self, sql, params=()):
        async with self.pool.connection() as conn:
            cur = await conn.execute(_pg_sql(sql), list(params))
            return max(cur.rowcount, 0)

    async def batch(self, statements):
        if not statements:
            return
        async with self.pool.connection() as conn, conn.transaction():
            for sql, params in statements:
                await conn.execute(_pg_sql(sql), list(params))

    async def script(self, sql):
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute(sql)

    async def close(self):
        await self.pool.close()


async def migrate(db, directory: pathlib.Path | None = None) -> list[str]:
    """Apply the migrations in `directory` (the database's own schema
    directory by default) not yet recorded in it, in name order. Returns the
    names applied."""
    directory = directory or db.migrations
    await db.run("CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY)")
    done = {r["name"] for r in await db.all("SELECT name FROM _migrations")}
    applied = []
    for path in sorted(directory.glob("*.sql")):
        if path.name in done:
            continue
        await db.script(path.read_text())
        await db.run("INSERT INTO _migrations (name) VALUES (?) ON CONFLICT DO NOTHING", [path.name])
        applied.append(path.name)
    return applied
