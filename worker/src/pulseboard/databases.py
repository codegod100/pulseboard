"""Databases for running outside Cloudflare: Turso (hosted libSQL, which is
SQLite with FTS5, so the D1 schema and queries carry over unchanged) over its
HTTP API, and a local SQLite file for development and tests.

Both have the interface `Store` expects, the same one entry.py gives D1:
`all`, `first`, `run`, `batch`, plus `script` for migrations.
"""

import base64
import pathlib
import sqlite3

MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent.parent / "migrations"


class SqliteDb:
    """A local SQLite file (or ":memory:"). Calls are synchronous inside the
    async methods: fine for development and tests, not for production."""

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

    async def close(self):
        self.conn.close()


class LibsqlError(Exception):
    pass


def _arg(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode()}
    return {"type": "text", "value": str(value)}


def _value(cell):
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "blob":
        return base64.b64decode(cell.get("base64", ""))
    return cell.get("value")


def _stmt(sql, params=()):
    return {"sql": sql, "args": [_arg(p) for p in params]}


class LibsqlDb:
    """Turso over its HTTP API (Hrana over HTTP, /v2/pipeline). One request
    per call, no connection to hold open, so it suits a server that scales
    to zero."""

    def __init__(self, http, url: str, token: str):
        # Turso hands out libsql:// URLs; the HTTP API is the same host.
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        self.http = http  # an httpx.AsyncClient
        self.endpoint = url.rstrip("/") + "/v2/pipeline"
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def _pipeline(self, requests):
        res = await self.http.post(self.endpoint, headers=self.headers,
                                   json={"requests": [*requests, {"type": "close"}]})
        if res.status_code != 200:
            raise LibsqlError(f"Turso answered HTTP {res.status_code}: {res.text[:300]}")
        results = res.json()["results"]
        for r in results:
            if r.get("type") == "error":
                raise LibsqlError(r.get("error", {}).get("message", "unknown error"))
        return [r["response"] for r in results[:len(requests)]]

    async def _execute(self, sql, params):
        (resp,) = await self._pipeline([{"type": "execute", "stmt": _stmt(sql, params)}])
        return resp["result"]

    async def all(self, sql, params=()):
        result = await self._execute(sql, params)
        cols = [c.get("name") for c in result["cols"]]
        return [dict(zip(cols, (_value(c) for c in row))) for row in result["rows"]]

    async def first(self, sql, params=()):
        rows = await self.all(sql, params)
        return rows[0] if rows else None

    async def run(self, sql, params=()):
        return int((await self._execute(sql, params)).get("affected_row_count", 0))

    async def batch(self, statements):
        """All or nothing: each step runs only if the one before succeeded,
        and a failure rolls the transaction back."""
        if not statements:
            return
        steps = [{"stmt": {"sql": "BEGIN"}}]
        for sql, params in statements:
            steps.append({"stmt": _stmt(sql, params),
                          "condition": {"type": "ok", "step": len(steps) - 1}})
        commit = len(steps)
        steps.append({"stmt": {"sql": "COMMIT"}, "condition": {"type": "ok", "step": commit - 1}})
        steps.append({"stmt": {"sql": "ROLLBACK"},
                      "condition": {"type": "not", "cond": {"type": "ok", "step": commit}}})
        (resp,) = await self._pipeline([{"type": "batch", "batch": {"steps": steps}}])
        result = resp["result"]
        errors = [e for e in result.get("step_errors", []) if e]
        if errors:
            raise LibsqlError(errors[0].get("message", "batch failed"))

    async def script(self, sql):
        await self._pipeline([{"type": "sequence", "sql": sql}])

    async def close(self):
        pass


async def migrate(db, directory: pathlib.Path = MIGRATIONS) -> list[str]:
    """Apply the migrations in `directory` not yet recorded in the database,
    in name order. Returns the names applied."""
    await db.run("CREATE TABLE IF NOT EXISTS _migrations ("
                 "name TEXT PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    done = {r["name"] for r in await db.all("SELECT name FROM _migrations")}
    applied = []
    for path in sorted(directory.glob("*.sql")):
        if path.name in done:
            continue
        await db.script(path.read_text())
        await db.run("INSERT OR IGNORE INTO _migrations (name) VALUES (?)", [path.name])
        applied.append(path.name)
    return applied
