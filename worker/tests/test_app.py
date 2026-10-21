import base64
import json
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from conftest import FakeHttp, Res, SoftCrypto, run
from test_feeds import ATOM, RSS

from pulseboard.app import App, Req

ORIGIN = "https://pulseboard.example.workers.dev"
DID = "did:plc:abc123"
PDS = "https://pds.example"
ISSUER = "https://auth.example"


def b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_dpop(proof, method, url, nonce=None):
    h, p, s = proof.split(".")
    header, payload = json.loads(b64d(h)), json.loads(b64d(p))
    assert header["typ"] == "dpop+jwt" and header["alg"] == "ES256" and "d" not in header["jwk"]
    assert payload["htm"] == method and payload["htu"] == url
    assert payload.get("nonce") == nonce
    jwk = header["jwk"]
    pub = ec.EllipticCurvePublicNumbers(
        int.from_bytes(b64d(jwk["x"]), "big"), int.from_bytes(b64d(jwk["y"]), "big"),
        ec.SECP256R1()).public_key()
    sig = b64d(s)
    pub.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
               f"{h}.{p}".encode(), ec.ECDSA(hashes.SHA256()))
    return jwk


def oauth_server():
    """A PDS and authorization server that demand a DPoP nonce, like Bluesky's."""
    state = {"jwk": None, "revoked": []}

    def nonce_gate(url, headers, ok):
        jwk = verify_dpop(headers["DPoP"], "POST", url,
                          json.loads(b64d(headers["DPoP"].split(".")[1])).get("nonce"))
        if json.loads(b64d(headers["DPoP"].split(".")[1])).get("nonce") != "n1":
            return Res(400, json.dumps({"error": "use_dpop_nonce"}), {"DPoP-Nonce": "n1"})
        if state["jwk"]:
            assert jwk == state["jwk"], "every request must use the same DPoP key"
        state["jwk"] = jwk
        return ok()

    def par(method, url, headers, body):
        form = parse_qs(body)
        assert form["client_id"] == [f"{ORIGIN}/oauth-client-metadata.json"]
        assert form["code_challenge_method"] == ["S256"] and form["scope"] == ["atproto"]
        state["state"] = form["state"][0]
        return nonce_gate(url, headers, lambda: Res(201, json.dumps({"request_uri": "urn:req:1"})))

    def token(method, url, headers, body):
        form = parse_qs(body)
        assert form["code"] == ["the-code"] and form["code_verifier"]
        return nonce_gate(url, headers, lambda: Res(200, json.dumps({
            "access_token": "at", "refresh_token": "rt", "token_type": "DPoP",
            "scope": "atproto", "sub": state.get("sub", DID)})))

    def revoke(method, url, headers, body):
        state["revoked"].append(parse_qs(body)["token"][0])
        return nonce_gate(url, headers, lambda: Res(200, ""))

    http = FakeHttp({
        "https://cloudflare-dns.com/dns-query?name=_atproto.alice.test&type=TXT":
            Res(200, json.dumps({"Answer": [{"data": f'"did={DID}"'}]})),
        f"https://plc.directory/{DID}": Res(200, json.dumps({
            "id": DID, "alsoKnownAs": ["at://alice.test"],
            "service": [{"id": "#atproto_pds", "type": "AtprotoPersonalDataServer",
                         "serviceEndpoint": PDS}]})),
        f"{PDS}/.well-known/oauth-protected-resource":
            Res(200, json.dumps({"authorization_servers": [ISSUER]})),
        f"{ISSUER}/.well-known/oauth-authorization-server": Res(200, json.dumps({
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/oauth/authorize",
            "token_endpoint": f"{ISSUER}/oauth/token",
            "pushed_authorization_request_endpoint": f"{ISSUER}/oauth/par",
            "revocation_endpoint": f"{ISSUER}/oauth/revoke"})),
        f"{ISSUER}/oauth/par": par,
        f"{ISSUER}/oauth/token": token,
        f"{ISSUER}/oauth/revoke": revoke,
        "https://feeds.example/rss": Res(200, RSS),
        "https://feeds.example/atom": Res(200, ATOM),
        "https://feeds.example/dead": Res(404),
        "https://example.com/1": Res(200, "<html><body><article><p>" + "long text " * 40
                                     + "</p><script>x</script></article></body></html>"),
    })
    return http, state


def req(method, path, cookie="", **params):
    return Req(method, path.strip("/"), list(params.items()), cookie, ORIGIN)


def sign_in(app, state, handle="alice.test"):
    resp = run(app.handle(req("GET", "auth/authorize", identity=handle)))
    assert resp.status == 303, resp.body
    loc = urlsplit(resp.headers["Location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == f"{ISSUER}/oauth/authorize"
    assert parse_qs(loc.query)["request_uri"] == ["urn:req:1"]
    return run(app.handle(req("GET", "auth/callback", state=state["state"], iss=ISSUER, code="the-code")))


def test_unauthenticated(db):
    http, _ = oauth_server()
    app = App(db, http, SoftCrypto())
    assert run(app.handle(req("GET", "/"))).headers["Location"] == "/auth/login"
    assert run(app.handle(req("GET", "feeds"))).status == 401
    assert run(app.handle(req("GET", "app.wasm"))).asset == "/app.wasm"
    assert run(app.handle(req("GET", "health"))).status == 200
    meta = json.loads(run(app.handle(req("GET", "oauth-client-metadata.json"))).body)
    assert meta["redirect_uris"] == [f"{ORIGIN}/auth/callback"]
    assert run(app.handle(req("GET", "auth/login"))).status == 200


def test_sign_in_and_read(db):
    http, state = oauth_server()
    app = App(db, http, SoftCrypto())
    resp = sign_in(app, state)
    assert resp.status == 303 and resp.headers["Location"] == "/"
    cookie = resp.headers["Set-Cookie"].split(";")[0]
    assert sorted(state["revoked"]) == ["at", "rt"]
    # The state is single use.
    again = run(app.handle(req("GET", "auth/callback", state=state["state"], iss=ISSUER, code="the-code")))
    assert again.status == 401

    assert run(app.handle(req("GET", "/", cookie))).asset == "/"

    added = json.loads(run(app.handle(req("POST", "feeds", cookie, url="https://feeds.example/rss"))).body)
    assert added == {"feed_url": "https://feeds.example/rss", "added": 2}
    dead = json.loads(run(app.handle(req("POST", "feeds", cookie, url="https://feeds.example/dead"))).body)
    assert "HTTP 404" in dead["error"]

    feeds = json.loads(run(app.handle(req("GET", "feeds", cookie))).body)
    assert [(f["title"], f["unread"]) for f in feeds] == [("Example", 2), ("https://feeds.example/dead", 0)]
    assert "HTTP 404" in feeds[1]["error"]

    arts = json.loads(run(app.handle(req("GET", "articles", cookie))).body)
    assert [a["title"] for a in arts] == ["First & best", "No guid"]
    first = arts[0]
    assert first["published"] == "2025-06-10T09:00:00Z"
    assert "<script>" not in first["content"] and "<b>body</b>" in first["content"]

    run(app.handle(req("POST", "read", cookie, id=str(first["id"]))))
    assert json.loads(run(app.handle(req("GET", "unread", cookie))).body) == {"count": 1}
    read = json.loads(run(app.handle(req("GET", "articles", cookie, status="read"))).body)
    assert [a["id"] for a in read] == [first["id"]] and read[0]["is_read"] is True
    run(app.handle(req("POST", "read", cookie, id=str(first["id"]), undo="1")))
    assert json.loads(run(app.handle(req("GET", "unread", cookie))).body) == {"count": 2}

    hits = json.loads(run(app.handle(req("GET", "articles", cookie, q="best"))).body)
    assert [a["id"] for a in hits] == [first["id"]]
    assert json.loads(run(app.handle(req("GET", "articles", cookie, q='"'))).body) == []

    full = json.loads(run(app.handle(req("POST", "fetch-content", cookie, id=str(first["id"])))).body)
    assert full["content"].startswith("<p>long text") and "script" not in full["content"]
    one = json.loads(run(app.handle(req("GET", f"articles/{first['id']}", cookie))).body)
    assert one["content"] == full["content"]

    assert json.loads(run(app.handle(req("POST", "read-all", cookie))).body) == {"unread": 0}

    refreshed = json.loads(run(app.handle(req("POST", "refresh", cookie))).body)
    assert refreshed["added"] == 0 and len(refreshed["errors"]) == 1

    opml = run(app.handle(req("GET", "opml", cookie))).body
    assert 'xmlUrl="https://feeds.example/rss"' in opml

    run(app.handle(req("DELETE", "feeds", cookie, url="https://feeds.example/dead")))
    assert len(json.loads(run(app.handle(req("GET", "feeds", cookie))).body)) == 1

    out = run(app.handle(req("GET", "auth/logout", cookie)))
    assert out.headers["Location"] == "/auth/login"
    assert run(app.handle(req("GET", "feeds", cookie))).status == 401


def test_users_are_isolated(db):
    http, state = oauth_server()
    app = App(db, http, SoftCrypto())
    a = sign_in(app, state).headers["Set-Cookie"].split(";")[0]
    run(app.handle(req("POST", "feeds", a, url="https://feeds.example/rss")))
    run(db.run("INSERT INTO web_sessions VALUES ('other', 'did:plc:other', 9999999999)"))
    b = "pulseboard_session=other"
    assert json.loads(run(app.handle(req("GET", "feeds", b))).body) == []
    assert json.loads(run(app.handle(req("GET", "articles", b))).body) == []
    run(app.handle(req("POST", "read-all", b)))
    assert json.loads(run(app.handle(req("GET", "unread", a))).body) == {"count": 2}


def test_opml_import_and_cron(db):
    http, state = oauth_server()
    app = App(db, http, SoftCrypto())
    cookie = sign_in(app, state).headers["Set-Cookie"].split(";")[0]
    src = ('<opml version="2.0"><body><outline text="News">'
           '<outline text="A" xmlUrl="https://feeds.example/atom"/></outline>'
           '<outline text="R" xmlUrl="https://feeds.example/rss"/></body></opml>')
    res = json.loads(run(app.handle(req("POST", "opml", cookie, opml=src))).body)
    assert res == {"imported": 2, "added": 2, "errors": []}
    feeds = json.loads(run(app.handle(req("GET", "feeds", cookie))).body)
    assert {f["title"]: f["category"] for f in feeds} == {"A": "News", "R": ""}
    # Everything was just fetched, so the cron run finds nothing due...
    before = len(http.calls)
    run(app.scheduled())
    assert len(http.calls) == before
    # ...until it is.
    run(db.run("UPDATE feeds SET last_fetched_at = datetime('now', '-2 hours')"))
    run(app.scheduled())
    assert len(http.calls) == before + 2


def test_sign_in_rejects_wrong_account(db):
    http, state = oauth_server()
    state["sub"] = "did:plc:mallory"
    app = App(db, http, SoftCrypto())
    resp = sign_in(app, state)
    assert resp.status == 401 and "Set-Cookie" not in resp.headers


def test_sign_in_rejects_bad_handle(db):
    http, _ = oauth_server()
    app = App(db, http, SoftCrypto())
    assert run(app.handle(req("GET", "auth/authorize", identity="not a handle"))).status == 400
    assert run(app.handle(req("GET", "auth/authorize", identity="nobody.test"))).status == 400


def test_import_from_modal(db, tmp_path):
    """The import script's SQL brings subscriptions back, and read state
    reattaches to articles when their feed is fetched again."""
    import sqlite3
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "scripts"))
    import import_modal

    old = sqlite3.connect(tmp_path / "old.db")
    old.executescript("""
      CREATE TABLE feeds (feed_url TEXT, title TEXT, site_url TEXT, description TEXT,
                          feed_type TEXT, favicon_url TEXT);
      CREATE TABLE subscriptions (user_did TEXT, feed_url TEXT, title TEXT, category TEXT,
                                  added_at TEXT);
      CREATE TABLE articles (id INTEGER PRIMARY KEY, feed_url TEXT, guid TEXT);
      CREATE TABLE read_state (user_did TEXT, article_id INTEGER, is_read INTEGER, read_at TEXT);
      INSERT INTO feeds VALUES ('https://feeds.example/rss', 'Ex''ample', NULL, NULL, 'rss', NULL);
      INSERT INTO subscriptions VALUES ('did:plc:abc123', 'https://feeds.example/rss', NULL, 'News',
                                        '2026-01-01 00:00:00');
      INSERT INTO articles VALUES (90, 'https://feeds.example/rss', 'https://example.com/1');
      INSERT INTO read_state VALUES ('did:plc:abc123', 90, 1, '2026-02-02 00:00:00');
    """)
    old.commit()
    old.close()
    sql = "\n".join(import_modal.statements(sqlite3.connect(tmp_path / "old.db")))
    db.conn.executescript(sql)
    db.conn.executescript(sql)  # idempotent

    http, state = oauth_server()
    app = App(db, http, SoftCrypto())
    cookie = sign_in(app, state).headers["Set-Cookie"].split(";")[0]
    feeds = json.loads(run(app.handle(req("GET", "feeds", cookie))).body)
    assert [(f["title"], f["category"]) for f in feeds] == [("Ex'ample", "News")]
    run(app.handle(req("POST", "refresh", cookie)))
    arts = json.loads(run(app.handle(req("GET", "articles", cookie, status="all"))).body)
    assert {a["url"]: a["is_read"] for a in arts} == {
        "https://example.com/1": True, "https://example.com/2": False}
