"""The standalone server (FastAPI Cloud): startup migrations, static files from
web/dist, proxy-aware origin, on SQLite and on Postgres."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import new_postgres_database, run
from test_feeds import RSS

from pulseboard import databases
from pulseboard.server import build

ORIGIN = "https://pulseboard.example"


def web(request: httpx.Request):
    if str(request.url) == "https://feeds.example/rss":
        return httpx.Response(200, text=RSS, headers={"Content-Type": "application/rss+xml"})
    return httpx.Response(404, text="nope")


def static_dir(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "index.html").write_text("<!doctype html>client")
    (tmp_path / "pulseboard.wasm").write_bytes(b"\0asm")
    (tmp_path.parent / "secret.txt").write_text("no")
    return tmp_path


def test_migrate_is_recorded(tmp_path):
    db = databases.SqliteDb(str(tmp_path / "x.db"))
    names = sorted(p.name for p in databases.MIGRATIONS.glob("*.sql"))
    assert run(databases.migrate(db)) == names
    assert run(databases.migrate(db)) == []


@pytest.fixture(params=["sqlite", "postgres"])
def server_db(request, tmp_path):
    """An unopened, unmigrated database: the server's startup does both."""
    if request.param == "sqlite":
        return databases.SqliteDb(str(tmp_path / "server.db"))
    return databases.PostgresDb(new_postgres_database(request))


def test_server(server_db, tmp_path):
    api = build(db=server_db, http_client=httpx.AsyncClient(transport=httpx.MockTransport(web)),
                static=static_dir(tmp_path / "dist"), refresh_minutes=0)
    with TestClient(api, base_url=ORIGIN, follow_redirects=False) as client:
        # Startup migrated the database.
        expected = len(list(server_db.migrations.glob("*.sql")))
        assert client.portal.call(server_db.first, "SELECT count(*) AS n FROM _migrations")["n"] == expected

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

        client.portal.call(server_db.run, "INSERT INTO web_sessions VALUES ('tok', 'did:plc:me', 9999999999)")
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
    api = build(db=databases.SqliteDb(), static=static_dir(tmp_path / "dist"), refresh_minutes=0)
    with TestClient(api, base_url=ORIGIN) as client:
        meta = client.get("/oauth-client-metadata.json", headers={"x-forwarded-host": "evil.example"}).json()
        assert meta["redirect_uris"] == ["https://reader.example/auth/callback"]


def test_copy_from_d1(request, tmp_path):
    """scripts/d1_to_postgres.py, from a SQLite file shaped like D1 (the same
    schema and data the reader writes), into a fresh Postgres database."""
    import sys
    sys.path.insert(0, str(databases.MIGRATIONS.parent / "scripts"))
    import d1_to_postgres
    from conftest import Api, SoftCrypto
    from test_app import ORIGIN as APP_ORIGIN, oauth_server, sign_in

    url = new_postgres_database(request)
    path = tmp_path / "d1.db"
    src = databases.SqliteDb(str(path))
    run(databases.migrate(src))
    http, state = oauth_server()
    api = Api(APP_ORIGIN, src, http, SoftCrypto())
    cookie = sign_in(api, state).headers["Set-Cookie"].split(";")[0]
    run(api.handle(("POST", "feeds", cookie, {"url": "https://feeds.example/rss"})))
    run(api.handle(("POST", "feeds", cookie, {"url": "https://feeds.example/atom"})))
    first = json.loads(run(api.handle(("GET", "articles", cookie, {}))).body)[0]
    run(api.handle(("POST", "read", cookie, {"id": str(first["id"])})))
    src.conn.commit()

    lines = []
    counts = run(d1_to_postgres.copy(d1_to_postgres.SqliteSource(str(path)), url,
                                     log=lambda *a, **k: lines.append(a)))
    expected = {t: src.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t, _ in d1_to_postgres.TABLES}
    assert counts == expected and expected["articles"] == 3 and expected["read_state"] == 1
    # Again: nothing new.
    assert set(run(d1_to_postgres.copy(d1_to_postgres.SqliteSource(str(path)), url,
                                       log=lambda *a, **k: None)).values()) == {0}

    # The reader on Postgres sees the same account, and new ids follow the copied ones.
    pg = databases.PostgresDb(url)
    run(pg.open())
    try:
        api = Api(APP_ORIGIN, pg, http, SoftCrypto())
        run(pg.run("INSERT INTO web_sessions VALUES ('t', 'did:plc:abc123', 9999999999)"))
        c = "pulseboard_session=t"
        feeds = json.loads(run(api.handle(("GET", "feeds", c, {}))).body)
        assert sorted(f["unread"] for f in feeds) == [1, 1]
        hits = json.loads(run(api.handle(("GET", "articles", c, {"q": "best", "status": "all"}))).body)
        assert [a["id"] for a in hits] == [first["id"]] and hits[0]["is_read"] is True
        run(pg.run("INSERT INTO subscriptions (user_did, feed_url) VALUES ('did:plc:x', 'https://x')"))
        assert run(pg.first("SELECT max(id) AS m FROM subscriptions"))["m"] == 3
    finally:
        run(pg.close())
