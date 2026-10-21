from conftest import FakeHttp, Res, run

from pulseboard.feeds import FeedError, fetch_feed, parse_feed
from pulseboard.htmlclean import ScrapeError, extract_article, sanitize_fragment
from pulseboard.opml import OpmlFeed, parse_opml, render_opml

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


def test_rss():
    f = parse_feed(RSS, "https://example.com/feed")
    assert (f.title, f.kind, f.favicon_url) == ("Example", "rss", "https://example.com/icon.png")
    a, b = f.articles
    assert a.title == "First & best" and a.author == "Ann"
    assert a.guid == "https://example.com/1"
    assert a.summary == "Short one"
    assert "<script>" in a.content  # raw; sanitised on the way out
    assert a.published.isoformat() == "2025-06-10T09:00:00+00:00"
    assert b.published is None and b.guid == "https://example.com/2"


def test_atom_prefers_alternate_and_falls_back_to_updated():
    f = parse_feed(ATOM, "u")
    assert f.site_url == "https://a.example/"
    (e,) = f.articles
    assert (e.guid, e.url, e.author, e.content) == ("tag:1", "https://a.example/e1", "Bo", "<p>hi</p>")
    assert e.published == e.updated and e.published.year == 2025


def test_rdf_and_json():
    (r,) = parse_feed(RDF, "u").articles
    assert r.guid == "https://r.example/1" and r.published.hour == 5
    (j,) = parse_feed(JSONFEED, "u").articles
    assert (j.guid, j.content, j.author) == ("7", "plain", "Cy")
    assert j.published.hour == 5


def test_not_a_feed():
    for body in ("", "<html><body>x</body></html>", "{nope", "<rss"):
        try:
            parse_feed(body, "u")
        except FeedError:
            continue
        raise AssertionError(body)


def test_fetch_retries_only_5xx():
    attempts = []

    def flaky(method, url, headers, body):
        attempts.append(1)
        return Res(503) if len(attempts) < 2 else Res(200, RSS)

    http = FakeHttp({"https://f.example/a": flaky, "https://f.example/b": Res(404)})
    assert len(run(fetch_feed(http, "https://f.example/a", base_delay=0))[0].articles) == 2
    try:
        run(fetch_feed(http, "https://f.example/b", base_delay=0))
    except FeedError as exc:
        assert exc.status == 404
    assert len([c for c in http.calls if c[1].endswith("/b")]) == 1


def test_sanitize():
    out = sanitize_fragment(
        '<p onclick="x()" class="k">Hi <a href="javascript:alert(1)">bad</a> '
        '<a href="https://ok.example">ok</a><script>evil()</script>'
        '<img src="data:x" data-src="https://img.example/a.png" onerror="x">'
        '<iframe src="https://x"></iframe><style>p{}</style>&lt;b&gt;</p>'
    )
    assert out == (
        '<p class="k">Hi bad <a href="https://ok.example" rel="noopener noreferrer">ok</a>'
        '<img src="https://img.example/a.png">&lt;b&gt;</p>'
    )
    assert sanitize_fragment("") == ""
    assert sanitize_fragment("<p>a<p>b") == "<p>a</p><p>b</p>"


def test_extract_article():
    page = ("<html><head><title>t</title></head><body><nav>menu</nav><article>"
            "<div class='share-button'>share</div><p>" + "words " * 60 + "</p></article>"
            "<footer>f</footer></body></html>")
    out = extract_article(page)
    assert out.startswith("<p>words") and "share" not in out and "menu" not in out
    try:
        extract_article("<html><body><p>tiny</p></body></html>")
    except ScrapeError:
        pass
    else:
        raise AssertionError("short page should fail")


def test_opml_round_trip():
    src = render_opml([OpmlFeed("https://a/feed", "A & co"),
                       OpmlFeed("https://b/feed", "B", category="News")])
    feeds = parse_opml(src)
    assert [(f.url, f.title, f.category) for f in feeds] == [
        ("https://a/feed", "A & co", ""), ("https://b/feed", "B", "News")]


def test_fetch_sends_validators_and_handles_304():
    def cond(method, url, headers, body):
        if headers.get("If-None-Match") == '"v1"':
            return Res(304)
        return Res(200, RSS, {"ETag": '"v1"', "Last-Modified": "Tue, 10 Jun 2025 04:00:00 GMT"})

    http = FakeHttp({"https://f.example/c": cond})
    feed, etag, lm = run(fetch_feed(http, "https://f.example/c"))
    assert feed and etag == '"v1"' and lm.startswith("Tue")
    assert run(fetch_feed(http, "https://f.example/c", etag, lm)) == (None, etag, lm)


def test_refusal_says_who_and_why():
    http = FakeHttp({"https://x.example/rss": Res(
        419, "<html><body><h1>Sorry.</h1> <p>Your request was blocked.</p></body></html>",
        {"Server": "nginx"})})
    try:
        run(fetch_feed(http, "https://x.example/rss"))
    except FeedError as exc:
        assert str(exc) == "fetching https://x.example/rss: HTTP 419 from nginx: Sorry. Your request was blocked."
    else:
        raise AssertionError("expected FeedError")
