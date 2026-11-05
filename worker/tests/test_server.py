"""The standalone server (FastAPI Cloud): startup migrations, static files from
web/dist, proxy-aware origin, and Turso over its HTTP API, here against a
stand-in that speaks the same protocol over SQLite."""

import base64
import json
import sqlite3

import httpx
from fastapi.testclient import TestClient

from conftest import run
from test_feeds import RSS

from pulseboard import databases
from pulseboard.server import build

ORIGIN = "https://pulseboard.example"


class FakeTurso:
    """Enough of Hrana over HTTP (/v2/pipeline) to run the reader: execute,
    sequence, and batch with ok/not conditions."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.auth = []

    @staticmethod
    def arg(a):
        return {"null": lambda: None, "integer": lambda: int(a["value"]),
                "float": lambda: float(a["value"]), "text": lambda: a["value"],
                "blob": lambda: base64.b64decode(a["base64"])}[a["type"]]()

    @staticmethod
    def cell(v):
        if v is None:
            return {"type": "null"}
        if isinstance(v, int):
            return {"type": "integer", "value": str(v)}
        if isinstance(v, float):
            return {"type": "float", "value": v}
        if isinstance(v, bytes):
            return {"type": "blob", "base64": base64.b64encode(v).decode()}
        return {"type": "text", "value": v}

    def execute(self, stmt):
        cur = self.conn.execute(stmt["sql"], [self.arg(a) for a in stmt.get("args", [])])
        rows = cur.fetchall()
        return {"cols": [{"name": d[0]} for d in cur.description or []],
                "rows": [[self.cell(v) for v in r] for r in rows],
                "affected_row_count": max(cur.rowcount, 0)}

    def batch(self, steps):
        ok, results, errors = {}, [], []

        def holds(c):
            if c is None:
                return True
            if c["type"] == "ok":
                return ok.get(c["step"], False)
            if c["type"] == "not":
                return not holds(c["cond"])
            raise AssertionError(c)

        for i, step in enumerate(steps):
            if not holds(step.get("condition")):
                results.append(None)
                errors.append(None)
                continue
            try:
                results.append(self.execute(step["stmt"]))
                errors.append(None)
                ok[i] = True
            except sqlite3.Error as exc:
                results.append(None)
                errors.append({"message": str(exc)})
        return {"step_results": results, "step_errors": errors}

    def __call__(self, request: httpx.Request):
        assert request.url.path == "/v2/pipeline"
        self.auth.append(request.headers.get("authorization"))
        out = []
        for r in json.loads(request.content)["requests"]:
            try:
                if r["type"] == "execute":
                    out.append({"type": "ok", "response": {"type": "execute", "result": self.execute(r["stmt"])}})
                elif r["type"] == "sequence":
                    self.conn.executescript(r["sql"])
                    out.append({"type": "ok", "response": {"type": "sequence"}})
                elif r["type"] == "batch":
                    out.append({"type": "ok", "response": {"type": "batch", "result": self.batch(r["batch"]["steps"])}})
                elif r["type"] == "close":
                    out.append({"type": "ok", "response": {"type": "close"}})
            except sqlite3.Error as exc:
                out.append({"type": "error", "error": {"message": str(exc)}})
        return httpx.Response(200, json={"baton": None, "base_url": None, "results": out})


def web(request: httpx.Request):
    if str(request.url) == "https://feeds.example/rss":
        return httpx.Response(200, text=RSS, headers={"Content-Type": "application/rss+xml"})
    return httpx.Response(404, text="nope")


def static_dir(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html>client")
    (tmp_path / "pulseboard.wasm").write_bytes(b"\0asm")
    (tmp_path.parent / "secret.txt").write_text("no")
    return tmp_path


def test_libsql_client():
    turso = FakeTurso()
    client = httpx.AsyncClient(transport=httpx.MockTransport(turso))
    db = databases.LibsqlDb(client, "libsql://db.example.turso.io", "tok")
    assert db.endpoint == "https://db.example.turso.io/v2/pipeline"

    async def go():
        assert await databases.migrate(db) == sorted(
            p.name for p in databases.MIGRATIONS.glob("*.sql"))
        assert await databases.migrate(db) == []  # recorded, so not again
        await db.run("INSERT INTO users (did) VALUES (?)", ["did:plc:a"])
        assert (await db.first("SELECT did FROM users"))["did"] == "did:plc:a"
        assert await db.run("UPDATE users SET did = ? WHERE did = ?", ["did:plc:b", "did:plc:a"]) == 1
        # A failing batch leaves nothing behind.
        try:
            await db.batch([("INSERT INTO users (did) VALUES (?)", ["did:plc:c"]),
                            ("INSERT INTO nope VALUES (1)", [])])
        except databases.LibsqlError:
            pass
        else:
            raise AssertionError("batch should fail")
        assert [r["did"] for r in await db.all("SELECT did FROM users")] == ["did:plc:b"]
        await db.batch([("INSERT INTO users (did) VALUES (?)", ["did:plc:c"])])
        assert len(await db.all("SELECT did FROM users")) == 2
        row = await db.first("SELECT ? AS n, ? AS f, ? AS z, ? AS b", [3, 1.5, None, b"\x01"])
        assert row == {"n": 3, "f": 1.5, "z": None, "b": b"\x01"}

    run(go())
    assert set(turso.auth) == {"Bearer tok"}


def test_server_on_turso(tmp_path):
    turso = FakeTurso()
    db = databases.LibsqlDb(httpx.AsyncClient(transport=httpx.MockTransport(turso)),
                            "https://db.example", "tok")
    api = build(db=db, http_client=httpx.AsyncClient(transport=httpx.MockTransport(web)),
                static=static_dir(tmp_path), refresh_minutes=0)
    with TestClient(api, base_url=ORIGIN, follow_redirects=False) as client:
        # Startup migrated the database.
        assert turso.conn.execute("SELECT count(*) FROM _migrations").fetchone()[0] == 3

        assert client.get("/health").json() == {"ok": True}
        assert client.get("/").headers["location"] == "/auth/login"
        assert client.get("/feeds").status_code == 401

        wasm = client.get("/pulseboard.wasm")
        assert wasm.content == b"\0asm" and wasm.headers["content-type"] == "application/wasm"
        assert client.get("/nothing.js").status_code == 404
        assert client.get("/%2e%2e/secret.txt").status_code == 404

        # Behind FastAPI Cloud's proxy the origin comes from X-Forwarded-*.
        meta = client.get("/oauth-client-metadata.json",
                          headers={"x-forwarded-proto": "https", "x-forwarded-host": "pb.fastapicloud.dev"}).json()
        assert meta["client_id"] == "https://pb.fastapicloud.dev/oauth-client-metadata.json"

        turso.conn.execute("INSERT INTO web_sessions VALUES ('tok', 'did:plc:me', 9999999999)")
        client.cookies.set("pulseboard_session", "tok", domain="pulseboard.example")
        assert client.get("/").text == "<!doctype html>client"
        added = client.post("/feeds", data={"url": "https://feeds.example/rss"}).json()
        assert added == {"feed_url": "https://feeds.example/rss", "added": 2}
        arts = client.get("/articles").json()
        assert [a["title"] for a in arts] == ["First & best", "No guid"]
        assert client.get("/articles", params={"q": "best"}).json()[0]["id"] == arts[0]["id"]
        assert client.post("/read", data={"id": arts[0]["id"]}).json() == {"id": arts[0]["id"]}
        assert client.get("/unread").json() == {"count": 1}


def test_public_origin_pins_sign_in(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://reader.example/")
    api = build(db=databases.SqliteDb(), static=static_dir(tmp_path), refresh_minutes=0)
    with TestClient(api, base_url=ORIGIN) as client:
        meta = client.get("/oauth-client-metadata.json", headers={"x-forwarded-host": "evil.example"}).json()
        assert meta["redirect_uris"] == ["https://reader.example/auth/callback"]
