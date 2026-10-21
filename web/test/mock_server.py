"""A stand-in for the reader's API, serving web/dist, for the browser test.

  python web/test/mock_server.py PORT
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from os.path import abspath, dirname, join
from urllib.parse import parse_qs, urlparse

DIST = join(dirname(dirname(abspath(__file__))), "dist")
NOW = datetime.now(timezone.utc)

feeds = [
    {"feed_url": "https://a.example/feed", "title": "Alpha News", "category": "", "favicon_url": ""},
    {"feed_url": "https://b.example/rss", "title": "Beta Blog", "category": "", "favicon_url": ""},
    {"feed_url": "https://d.example/x", "title": "Delta, a feed whose title is far too long for the sidebar", "category": "", "favicon_url": "",
     "extra_unread": 332},
]
articles = []
next_id = 1
refreshes = 0
signed_in = True


def add_article(feed, title, hours_ago, url=None):
    global next_id
    articles.insert(0, {
        "id": next_id, "feed_url": feed["feed_url"], "feed_title": feed["title"],
        "title": title, "url": url or f"https://example.com/{next_id}", "author": "",
        "summary": f"<p>Summary of <b>{title}</b> &amp; more</p>", "content": "",
        "published": (NOW - timedelta(hours=hours_ago)).isoformat(), "is_read": False,
    })
    next_id += 1


for i in range(5):
    add_article(feeds[i % 2], f"Old story {i + 1}", 10 - i)
add_article(feeds[0], "Broken link story", 1, url="javascript:alert(1)")


def unread_of(url=None):
    return sum(1 for a in articles if not a["is_read"] and (url is None or a["feed_url"] == url))


class H(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".wasm": "application/wasm"}

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=DIST, **kw)

    def log_message(self, *a):
        pass

    def send_json(self, v, code=200):
        b = json.dumps(v).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def form(self):
        n = int(self.headers.get("content-length") or 0)
        return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}

    def api(self, method):
        global refreshes, signed_in
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        if p == "/__signout":
            signed_in = False
            return self.send_json({})
        if p == "/auth/login":
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>login page</h1>")
            return True
        if p not in ("/feeds", "/unread", "/articles", "/read", "/read-all", "/refresh", "/opml"):
            return False
        if not signed_in:
            return self.send_json({"error": "sign in"}, 401)
        f = self.form() if method in ("POST", "PUT") else {}
        if p == "/feeds" and method == "GET":
            return self.send_json([{**x, "unread": unread_of(x["feed_url"]) + x.get("extra_unread", 0)} for x in feeds])
        if p == "/feeds" and method == "POST":
            url = f.get("url", "")
            if not url.startswith("http"):
                return self.send_json({"error": "Not a feed URL."}, 400)
            feeds.append({"feed_url": url, "title": "Gamma " + url, "category": "", "favicon_url": ""})
            return self.send_json({"added": 0})
        if p == "/feeds" and method == "PUT":
            old = next((x for x in feeds if x["feed_url"] == f.get("url")), None)
            if old is None:
                return self.send_json({"error": "no such subscription"}, 404)
            new = f.get("new_url") or old["feed_url"]
            for a in articles:
                if a["feed_url"] == old["feed_url"]:
                    a["feed_url"] = new
            old.update(feed_url=new, title=f.get("title") or new, category=f.get("category", ""))
            if "fail" in new:
                old["error"] = f"fetching {new}: HTTP 403"
                return self.send_json({"feed_url": new, "added": 0, "fetch_error": old["error"]})
            old.pop("error", None)
            return self.send_json({"feed_url": new, "added": 2})
        if p == "/feeds" and method == "DELETE":
            feeds[:] = [x for x in feeds if x["feed_url"] != q.get("url")]
            return self.send_json({"ok": True})
        if p == "/unread":
            return self.send_json({"count": unread_of()})
        if p == "/articles":
            items = articles
            if "q" in q:
                items = [a for a in items if q["q"].lower() in a["title"].lower()]
            else:
                st = q.get("status", "unread")
                if st == "unread":
                    items = [a for a in items if not a["is_read"]]
                elif st == "read":
                    items = [a for a in items if a["is_read"]]
                if q.get("feed"):
                    items = [a for a in items if a["feed_url"] == q["feed"]]
            return self.send_json(items[: int(q.get("limit", 50))])
        if p == "/read":
            for a in articles:
                if a["id"] == int(f["id"]):
                    a["is_read"] = f.get("undo") != "1"
            return self.send_json({"ok": True})
        if p == "/read-all":
            for x in feeds:
                if not f.get("feed") or x["feed_url"] == f["feed"]:
                    x["extra_unread"] = 0
            for a in articles:
                if not f.get("feed") or a["feed_url"] == f["feed"]:
                    a["is_read"] = True
            return self.send_json({"unread": unread_of()})
        if p == "/refresh":
            refreshes += 1
            add_article(feeds[1], f"Fresh story {refreshes}", 0)
            return self.send_json({"added": 1, "errors": []})
        if p == "/opml" and method == "GET":
            b = b"<opml version='2.0'><body/></opml>"
            self.send_response(200)
            self.send_header("content-type", "text/x-opml")
            self.end_headers()
            self.wfile.write(b)
            return True
        if p == "/opml":
            return self.send_json({"imported": 1, "added": 1, "errors": []})
        return False

    def do_GET(self):
        if not self.api("GET"):
            super().do_GET()

    def do_POST(self):
        if not self.api("POST"):
            self.send_json({"error": "not found"}, 404)

    def do_PUT(self):
        if not self.api("PUT"):
            self.send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        if not self.api("DELETE"):
            self.send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
