"""The Qt server end to end, ported from the Python server's tests
(worker/tests): sign-in, the reader's API, feeds, OPML, the cron run and
static files, against the real component under `wasmtime serve`."""

import base64
import json
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from conftest import Res

ORIGIN = "https://pulseboard.example"
DID = "did:plc:abc123"
PDS = "https://pds.example"
ISSUER = "https://auth.example"

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>Example</title><link>https://example.com/</link>
<image><url>https://example.com/icon.png</url></image>
<item><title>First &amp; best</title><link>https://example.com/1</link>
<description>Short&nbsp;one</description>
<content:encoded><![CDATA[<p>Full <b>body</b></p><script>alert(1)</script>]]></content:encoded>
<dc:creator>Ann</dc:creator><pubDate>Tue, 10 Jun 2025 04:00:00 EST</pubDate></item>
<item><title>No guid</title><link>https://example.com/2</link><pubDate>garbage</pubDate></item>
</channel></rss>"""

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title>
<link rel="self" href="https://a.example/feed"/><link href="https://a.example/"/>
<icon>https://a.example/i.png</icon>
<entry><id>tag:1</id><title>E1</title><link rel="self" href="https://a.example/self"/>
<link rel="alternate" href="https://a.example/e1"/><updated>2025-01-02T03:04:05Z</updated>
<author><name>Bo</name></author><content type="html">&lt;p&gt;hi&lt;/p&gt;</content></entry></feed>"""

RDF = """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
 xmlns:dc="http://purl.org/dc/elements/1.1/"><channel rdf:about="x"><title>R</title></channel>
<item rdf:about="https://r.example/1"><title>R1</title><link>https://r.example/1</link>
<dc:date>2024-05-06T07:08:09+02:00</dc:date></item></rdf:RDF>"""

JSONFEED = """{"version":"https://jsonfeed.org/version/1.1","title":"J","home_page_url":"https://j.example",
"items":[{"id":7,"url":"https://j.example/7","content_text":"plain","authors":[{"name":"Cy"}],
"date_published":"2024-01-01T00:00:00-05:00"}]}"""


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


def oauth_world(up):
    """A PDS and authorization server that demand a DPoP nonce, like Bluesky's."""
    state = {"jwk": None, "revoked": []}

    def nonce_gate(url, headers, ok):
        nonce = json.loads(b64d(headers["DPoP"].split(".")[1])).get("nonce")
        jwk = verify_dpop(headers["DPoP"], "POST", url, nonce)
        if nonce != "n1":
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

    up.routes.update({
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
    return state


def sign_in(server, state, handle="alice.test"):
    resp = server.request("GET", "auth/authorize", identity=handle)
    assert resp.status_code == 303, resp.text
    loc = urlsplit(resp.headers["Location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == f"{ISSUER}/oauth/authorize"
    assert parse_qs(loc.query)["request_uri"] == ["urn:req:1"]
    return server.request("GET", "auth/callback", state=state["state"], iss=ISSUER, code="the-code")


def signed_in(server):
    state = oauth_world(server.upstream)
    resp = sign_in(server, state)
    assert resp.status_code == 303, resp.text
    return resp.headers["Set-Cookie"].split(";")[0], state


def body(resp):
    return json.loads(resp.text)


# --- the server -------------------------------------------------------------------


def test_migrations_and_static_files(make_server):
    server = make_server(migrate=False)
    assert server.internal("migrate") == {"applied": ["0001_init.sql"]}
    assert server.internal("migrate") == {"applied": []}
    # The internal routes want the machine's secret.
    assert server.request("POST", "internal/migrate").status_code == 404

    assert body(server.request("GET", "health")) == {"ok": True}
    assert server.request("GET", "/").headers["location"] == "/auth/login"
    assert server.request("GET", "feeds").status_code == 401

    wasm = server.request("GET", "pulseboard.wasm")
    assert wasm.content == b"\0asm" and wasm.headers["content-type"] == "application/wasm"
    assert server.request("GET", "nothing.js").status_code == 404
    assert server.request("GET", "%2e%2e/secret.txt").status_code == 404

    server.sql("INSERT INTO web_sessions VALUES ('tok', 'did:plc:me', 9999999999)")
    assert server.request("GET", "/", "pulseboard_session=tok").text == "<!doctype html>client"


def test_origin_from_proxy_and_pinned(make_server):
    server = make_server()
    meta = body(server.request("GET", "oauth-client-metadata.json",
                               headers={"x-forwarded-proto": "https", "x-forwarded-host": "pb.fly.dev"}))
    assert meta["client_id"] == "https://pb.fly.dev/oauth-client-metadata.json"
    pinned = make_server(env={"PUBLIC_ORIGIN": "https://reader.example/"})
    meta = body(pinned.request("GET", "oauth-client-metadata.json", headers={"x-forwarded-host": "evil.example"}))
    assert meta["redirect_uris"] == ["https://reader.example/auth/callback"]


def test_unauthenticated(server):
    oauth_world(server.upstream)
    assert server.request("GET", "/").headers["Location"] == "/auth/login"
    denied = server.request("GET", "feeds")
    assert denied.status_code == 401 and body(denied) == {"error": "AT Protocol authentication required"}
    assert server.request("POST", "read", id="1").status_code == 401
    meta = body(server.request("GET", "oauth-client-metadata.json"))
    assert meta["redirect_uris"] == [f"{ORIGIN}/auth/callback"]
    assert meta["dpop_bound_access_tokens"] is True
    assert server.request("GET", "auth/login").status_code == 200


def test_sign_in_and_read(server):
    up = server.upstream
    state = oauth_world(up)
    resp = sign_in(server, state)
    assert resp.status_code == 303 and resp.headers["Location"] == "/"
    cookie = resp.headers["Set-Cookie"].split(";")[0]
    assert "HttpOnly" in resp.headers["Set-Cookie"]
    assert sorted(state["revoked"]) == ["at", "rt"]
    # The state is single use.
    again = server.request("GET", "auth/callback", state=state["state"], iss=ISSUER, code="the-code")
    assert again.status_code == 401

    assert server.request("GET", "/", cookie).text == "<!doctype html>client"
    # Paths under the API are never static files.
    missing = server.request("GET", "feeds/nope", cookie)
    assert missing.status_code == 404 and body(missing) == {"error": "not found"}
    assert body(server.request("GET", "articles/x", cookie)) == {"error": "no such article"}

    added = body(server.request("POST", "feeds", cookie, url="https://feeds.example/rss"))
    assert added == {"feed_url": "https://feeds.example/rss", "added": 2}
    dead = body(server.request("POST", "feeds", cookie, url="https://feeds.example/dead"))
    assert "HTTP 404" in dead["error"]

    feeds = body(server.request("GET", "feeds", cookie))
    assert [(f["title"], f["unread"]) for f in feeds] == [("Example", 2), ("https://feeds.example/dead", 0)]
    assert feeds[0]["favicon_url"] == "https://example.com/icon.png"
    assert "HTTP 404" in feeds[1]["error"]

    arts = body(server.request("GET", "articles", cookie))
    assert [a["title"] for a in arts] == ["First & best", "No guid"]
    first = arts[0]
    assert first["published"] == "2025-06-10T09:00:00Z"
    assert arts[1]["published"] == ""
    assert "<script>" not in first["content"] and "<b>body</b>" in first["content"]
    assert first["summary"] == "Short one" and first["author"] == "Ann"

    server.request("POST", "read", cookie, id=str(first["id"]))
    assert body(server.request("GET", "unread", cookie)) == {"count": 1}
    read = body(server.request("GET", "articles", cookie, status="read"))
    assert [a["id"] for a in read] == [first["id"]] and read[0]["is_read"] is True
    server.request("POST", "read", cookie, id=str(first["id"]), undo="1")
    assert body(server.request("GET", "unread", cookie)) == {"count": 2}

    hits = body(server.request("GET", "articles", cookie, q="best"))
    assert [a["id"] for a in hits] == [first["id"]]
    assert body(server.request("GET", "articles", cookie, q='"')) == []

    full = body(server.request("POST", "fetch-content", cookie, id=str(first["id"])))
    assert full["content"].startswith("<p>long text") and "script" not in full["content"]
    one = body(server.request("GET", f"articles/{first['id']}", cookie))
    assert one["content"] == full["content"]

    assert body(server.request("POST", "read-all", cookie)) == {"unread": 0}

    # Both feeds were fetched moments ago, so a plain refresh skips them...
    calls = len(up.calls)
    assert body(server.request("POST", "refresh", cookie)) == {"added": 0, "errors": []}
    assert len(up.calls) == calls
    # ...and a forced one fetches them again.
    refreshed = body(server.request("POST", "refresh", cookie, force="1"))
    assert refreshed["added"] == 0 and len(refreshed["errors"]) == 1

    opml = server.request("GET", "opml", cookie)
    assert 'xmlUrl="https://feeds.example/rss"' in opml.text
    assert opml.headers["content-disposition"].startswith("attachment")

    server.request("DELETE", "feeds", cookie, url="https://feeds.example/dead")
    assert len(body(server.request("GET", "feeds", cookie))) == 1

    out = server.request("GET", "auth/logout", cookie)
    assert out.headers["Location"] == "/auth/login"
    assert server.request("GET", "feeds", cookie).status_code == 401


def test_edit_subscription(server):
    up = server.upstream
    cookie, _ = signed_in(server)
    up.routes["https://feeds.example/moved"] = Res(200, RSS)
    server.request("POST", "feeds", cookie, url="https://feeds.example/rss")
    server.request("POST", "feeds", cookie, url="https://feeds.example/atom")
    first = body(server.request("GET", "articles", cookie, feed="https://feeds.example/rss"))[0]
    server.request("POST", "read", cookie, id=str(first["id"]))

    def feeds():
        return {f["feed_url"]: f for f in body(server.request("GET", "feeds", cookie))}

    ok = server.request("PUT", "feeds", cookie, url="https://feeds.example/rss", title="My example", category="news")
    assert ok.status_code == 200, ok.text
    f = feeds()["https://feeds.example/rss"]
    assert (f["title"], f["category"], f["unread"]) == ("My example", "news", 1)

    assert server.request("PUT", "feeds", cookie, url="https://feeds.example/rss",
                          new_url="https://feeds.example/atom").status_code == 409
    assert server.request("PUT", "feeds", cookie, url="https://feeds.example/rss",
                          new_url="ftp://x").status_code == 400
    assert server.request("PUT", "feeds", cookie, url="https://feeds.example/nope", title="x").status_code == 404

    moved = body(server.request("PUT", "feeds", cookie, url="https://feeds.example/rss",
                                new_url="https://feeds.example/moved", title="My example", category="news"))
    assert moved == {"feed_url": "https://feeds.example/moved", "added": 2}
    f = feeds()
    assert "https://feeds.example/rss" not in f
    assert (f["https://feeds.example/moved"]["title"], f["https://feeds.example/moved"]["unread"]) == ("My example", 1)
    read = body(server.request("GET", "articles", cookie, status="read"))
    assert [(a["feed_url"], a["title"]) for a in read] == [("https://feeds.example/moved", first["title"])]
    assert server.sql("SELECT subscriber_count FROM feeds WHERE feed_url = %s",
                      ["https://feeds.example/rss"]) == [(0,)]

    server.request("PUT", "feeds", cookie, url="https://feeds.example/moved", title="")
    assert feeds()["https://feeds.example/moved"]["title"] == "Example"


def test_users_are_isolated(server):
    a, _ = signed_in(server)
    server.request("POST", "feeds", a, url="https://feeds.example/rss")
    server.sql("INSERT INTO web_sessions VALUES ('other', 'did:plc:other', 9999999999)")
    b = "pulseboard_session=other"
    assert body(server.request("GET", "feeds", b)) == []
    assert body(server.request("GET", "articles", b)) == []
    server.request("POST", "read-all", b)
    assert body(server.request("GET", "unread", a)) == {"count": 2}


def test_opml_import_and_cron(server):
    up = server.upstream
    cookie, _ = signed_in(server)
    src = ('<opml version="2.0"><body><outline text="News">'
           '<outline text="A" xmlUrl="https://feeds.example/atom"/></outline>'
           '<outline text="R" xmlUrl="https://feeds.example/rss"/>'
           '<outline text="F" xmlUrl="ftp://nope"/></body></opml>')
    res = body(server.request("POST", "opml", cookie, opml=src))
    assert res == {"imported": 3, "added": 2, "errors": [{"feed_url": "ftp://nope", "error": "not an http(s) URL"}]}
    feeds = body(server.request("GET", "feeds", cookie))
    assert {f["title"]: f["category"] for f in feeds} == {"A": "News", "R": ""}
    assert server.request("POST", "opml", cookie, opml="<html/>").status_code == 400
    # Everything was just fetched, so the cron run finds nothing due...
    before = len(up.calls)
    server.internal("cron")
    assert len(up.calls) == before
    # ...until it is.
    server.sql("UPDATE feeds SET last_fetched_at = '2000-01-01 00:00:00'")
    server.internal("cron")
    assert len(up.calls) == before + 2


def test_sign_in_rejects_wrong_account(server):
    state = oauth_world(server.upstream)
    state["sub"] = "did:plc:mallory"
    resp = sign_in(server, state)
    assert resp.status_code == 401 and "Set-Cookie" not in resp.headers


def test_sign_in_rejects_bad_handle(server):
    oauth_world(server.upstream)
    assert server.request("GET", "auth/authorize", identity="not a handle").status_code == 400
    assert server.request("GET", "auth/authorize", identity="nobody.test").status_code == 400
    assert server.request("GET", "auth/authorize", identity="did:plc:x").status_code == 400


# --- feeds ------------------------------------------------------------------------


def parse(server, text):
    return body(server.request("POST", "internal/test/parse-feed", headers={"x-pulseboard-cron": "test-cron-secret"},
                               content=text))


def test_parse_formats(server):
    f = parse(server, RSS)
    assert (f["title"], f["kind"], f["favicon_url"]) == ("Example", "rss", "https://example.com/icon.png")
    a, b = f["articles"]
    assert a["title"] == "First & best" and a["author"] == "Ann" and a["guid"] == "https://example.com/1"
    assert "<script>" in a["content"]  # raw; sanitised on the way out
    assert a["published"] == "2025-06-10 09:00:00"
    assert b["published"] == "" and b["guid"] == "https://example.com/2"

    f = parse(server, ATOM)
    assert f["site_url"] == "https://a.example/"
    (e,) = f["articles"]
    assert (e["guid"], e["url"], e["author"], e["content"]) == ("tag:1", "https://a.example/e1", "Bo", "<p>hi</p>")
    assert e["published"] == e["updated"] == "2025-01-02 03:04:05"

    (r,) = parse(server, RDF)["articles"]
    assert r["guid"] == "https://r.example/1" and r["published"] == "2024-05-06 05:08:09"
    (j,) = parse(server, JSONFEED)["articles"]
    assert (j["guid"], j["content"], j["author"]) == ("7", "plain", "Cy")
    assert j["published"] == "2024-01-01 05:00:00"

    for bad in ("", "<html><body>x</body></html>", "{nope", "<rss"):
        assert "error" in parse(server, bad), bad


def test_fetch_retries_only_5xx(server):
    up = server.upstream
    cookie, _ = signed_in(server)
    attempts = []

    def flaky(method, url, headers, body):
        attempts.append(1)
        return Res(503) if len(attempts) < 2 else Res(200, RSS)

    up.routes["https://f.example/a"] = flaky
    up.routes["https://f.example/b"] = Res(404)
    assert body(server.request("POST", "feeds", cookie, url="https://f.example/a"))["added"] == 2
    assert "HTTP 404" in body(server.request("POST", "feeds", cookie, url="https://f.example/b"))["error"]
    assert len(up.fetched("https://f.example/b")) == 1


def test_validators_and_304(server):
    up = server.upstream
    cookie, _ = signed_in(server)

    def cond(method, url, headers, body):
        if headers.get("If-None-Match") == '"v1"':
            return Res(304)
        return Res(200, RSS, {"ETag": '"v1"', "Last-Modified": "Tue, 10 Jun 2025 04:00:00 GMT"})

    up.routes["https://f.example/c"] = cond
    server.request("POST", "feeds", cookie, url="https://f.example/c")
    assert body(server.request("POST", "refresh", cookie, force="1")) == {"added": 0, "errors": []}
    last = up.fetched("https://f.example/c")[-1][2]
    assert last["If-None-Match"] == '"v1"' and last["If-Modified-Since"].startswith("Tue")
    assert "pulseboard" in last["User-Agent"]


def test_refusals_say_who_and_why(server):
    up = server.upstream
    cookie, _ = signed_in(server)
    up.routes["https://x.example/rss"] = Res(
        419, "<html><body><h1>Sorry.</h1> <p>Your request was blocked.</p></body></html>", {"Server": "nginx"})
    up.routes["https://cf.example/rss"] = Res(
        503, "<title>Just a moment...</title>", {"Server": "cloudflare", "cf-mitigated": "challenge"})
    err = body(server.request("POST", "feeds", cookie, url="https://x.example/rss"))["error"]
    assert err == "fetching https://x.example/rss: HTTP 419 from nginx: Sorry. Your request was blocked."
    err = body(server.request("POST", "feeds", cookie, url="https://cf.example/rss"))["error"]
    assert "Cloudflare bot protection" in err
    assert len(up.fetched("https://cf.example/rss")) == 1


def test_redirects_are_followed(server):
    up = server.upstream
    cookie, _ = signed_in(server)
    up.routes["https://old.example/feed"] = Res(301, "", {"Location": "https://new.example/feed"})
    up.routes["https://new.example/feed"] = Res(200, ATOM)
    assert body(server.request("POST", "feeds", cookie, url="https://old.example/feed"))["added"] == 1


# --- markup -----------------------------------------------------------------------


def hook(server, what, text):
    return body(server.request("POST", "internal/test/" + what, headers={"x-pulseboard-cron": "test-cron-secret"},
                               content=text))


def test_sanitize(server):
    out = hook(server, "sanitize",
               '<p onclick="x()" class="k">Hi <a href="javascript:alert(1)">bad</a> '
               '<a href="https://ok.example">ok</a><script>evil()</script>'
               '<img src="data:x" data-src="https://img.example/a.png" onerror="x">'
               '<iframe src="https://x"></iframe><style>p{}</style>&lt;b&gt;</p>')["out"]
    assert out == ('<p class="k">Hi bad <a href="https://ok.example" rel="noopener noreferrer">ok</a>'
                   '<img src="https://img.example/a.png">&lt;b&gt;</p>')
    assert hook(server, "sanitize", "")["out"] == ""
    assert hook(server, "sanitize", "<p>a<p>b")["out"] == "<p>a</p><p>b</p>"
    assert hook(server, "sanitize", "caf&eacute; &amp; &#x263A; &nosuch;")["out"] == "café &amp; ☺ &amp;nosuch;"


def test_extract_article(server):
    page = ("<html><head><title>t</title></head><body><nav>menu</nav><article>"
            "<div class='share-button'>share</div><p>" + "words " * 60 + "</p></article>"
            "<footer>f</footer></body></html>")
    got = hook(server, "extract", page)
    assert got["out"].startswith("<p>words") and "share" not in got["out"] and "menu" not in got["out"]
    assert hook(server, "extract", "<html><body><p>tiny</p></body></html>")["error"] == "no article content found"


def test_opml_round_trip(server):
    src = ('<opml version="2.0"><body><outline text="A &amp; co" xmlUrl="https://a/feed"/>'
           '<outline text="News"><outline title="B" xmlUrl="https://b/feed"/></outline></body></opml>')
    got = hook(server, "opml", src)
    assert [(f["url"], f["title"], f["category"]) for f in got["feeds"]] == [
        ("https://a/feed", "A & co", ""), ("https://b/feed", "B", "News")]
    again = hook(server, "opml", got["rendered"])
    assert again["feeds"] == got["feeds"]
