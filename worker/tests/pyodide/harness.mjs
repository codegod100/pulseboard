// Runs worker/src/entry.py under Pyodide in Node with a D1 stand-in over
// node:sqlite, a canned fetch, and the real Workers Python SDK (its ASGI
// adapter is what hands requests to FastAPI), with stand-ins for the two
// modules only the Workers runtime provides.
import { loadPyodide } from "pyodide";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import path from "node:path";

const src = process.argv[2];
const repo = path.resolve(src, "..");
const sqlite = new DatabaseSync(":memory:");
for (const m of fs.readdirSync(path.join(repo, "migrations")).filter(f => f.endsWith(".sql")).sort()) {
  sqlite.exec(fs.readFileSync(path.join(repo, "migrations", m), "utf8"));
}

class Stmt {
  constructor(sql, args = []) { this.sql = sql; this.args = args; }
  bind(...args) {
    for (const a of args) if (a === undefined) throw new Error("D1_TYPE_ERROR: undefined bound");
    return new Stmt(this.sql, args);
  }
  async all() { return { results: sqlite.prepare(this.sql).all(...this.args), meta: {} }; }
  async run() { const r = sqlite.prepare(this.sql).run(...this.args); return { results: [], meta: { changes: Number(r.changes) } }; }
}
const DB = {
  prepare: (sql) => new Stmt(sql),
  batch: async (stmts) => { sqlite.exec("BEGIN"); try { const out = []; for (const s of stmts) out.push(await s.run()); sqlite.exec("COMMIT"); return out; } catch (e) { sqlite.exec("ROLLBACK"); throw e; } },
};
const ASSETS = { fetch: async (req) => new Response(`asset:${new URL(req.url).pathname}`, { status: 200 }) };

const RSS = `<?xml version="1.0"?><rss><channel><title>T</title><item><title>Hello &amp; bye</title><link>https://x.example/1</link><guid>g1</guid><description>&lt;b&gt;hi&lt;/b&gt;&lt;script&gt;x&lt;/script&gt;</description><pubDate>Tue, 10 Jun 2025 04:00:00 GMT</pubDate></item></channel></rss>`;
const fakeFetch = async (url, init) => {
  url = String(url);
  if (url === "https://feeds.example/rss") {
    if (!(init.signal instanceof AbortSignal)) throw new Error("no signal");
    if (init.headers["User-Agent"] === undefined) throw new Error("no UA: " + JSON.stringify(init.headers));
    return new Response(RSS, { headers: { "Content-Type": "application/rss+xml", "X-Test": "1" } });
  }
  return new Response("nope", { status: 404 });
};

const py = await loadPyodide();
// Pyodide's own builds of pydantic-core and friends come from its CDN;
// fastapi, starlette and the Workers SDK are pure Python, from PyPI.
// The Worker's dependencies, as pyproject.toml lists them for pywrangler.
const pyproject = fs.readFileSync(path.join(repo, "pyproject.toml"), "utf8");
const deps = ["workers-runtime-sdk", ...JSON.parse(pyproject.match(/^dependencies\s*=\s*(\[[^\]]*\])/m)[1])];
await py.loadPackage("micropip");
py.globals.set("DEPS", py.toPy(deps));
await py.runPythonAsync(`
import micropip
await micropip.install(list(DEPS))
`);
globalThis.fetch = fakeFetch;
for (const f of ["entry.py", ...fs.readdirSync(path.join(src, "pulseboard")).filter(f => f.endsWith(".py")).map(f => "pulseboard/" + f)]) {
  py.FS.mkdirTree("/w/pulseboard");
  py.FS.writeFile("/w/" + f, fs.readFileSync(path.join(src, f), "utf8"));
}
// What workerd provides to the SDK. waitUntil only runs a promise to the end.
globalThis.__cfWorkers = { waitUntil: (p) => { Promise.resolve(p).catch((e) => { console.error(e); process.exitCode = 1; }); } };
py.FS.writeFile("/w/_cloudflare_compat_flags.py", "def __getattr__(name):\n    return False\n");
py.FS.writeFile("/w/_pyodide_entrypoint_helper.py", `
import js
cloudflareWorkersModule = js.__cfWorkers
cloudflareSocketsModule = None
async def doAnImport(name):
    if name == "cloudflare:workers":
        return js.__cfWorkers
    raise ImportError(name)
def patch_env_helper(kwds):
    yield
def patchWaitUntil(ctx):
    pass
`);
py.globals.set("ENV", { DB, ASSETS });
// Workers requests carry Host, which the app reads its origin from; Node's
// Request does not add one, so put it back.
py.globals.set("JSREQ", (u, init) => {
  const req = new Request(u, init);
  req.headers.set("host", new URL(u).host);
  return req;
});
await py.runPythonAsync(`
import sys; sys.path.insert(0, "/w")
import js, json
from entry import Default, WebCrypto, Http, app_for
from pyodide.ffi import to_js
from pulseboard import oauth

w = Default(None, ENV)
O = "https://pb.example"
async def call(method, path, body=None, cookie=None, ctype="application/x-www-form-urlencoded"):
    headers = {"content-type": ctype} if body is not None else {}
    if cookie: headers["cookie"] = cookie
    init = {"method": method, "headers": headers}
    if body is not None: init["body"] = body
    r = await w.fetch(JSREQ(O + path, to_js(init, dict_converter=js.Object.fromEntries)))
    return int(r.status), str(await r.text()), r.headers

s, b, h = await call("GET", "/")
assert s == 307 and h.get("location") == "/auth/login", (s, b)
s, b, h = await call("GET", "/pulseboard.wasm"); assert (s, b) == (200, "asset:/pulseboard.wasm"), (s, b)
s, b, h = await call("GET", "/feeds"); assert s == 401 and "error" in json.loads(b), (s, b)
s, b, h = await call("GET", "/oauth-client-metadata.json")
assert json.loads(b)["client_id"] == O + "/oauth-client-metadata.json"

# A session, as the callback would create it.
await app_for(ENV).store.create_session("tok", "did:plc:me", 9999999999)
c = "a=b; pulseboard_session=tok"
s, b, h = await call("GET", "/", cookie=c); assert (s, b) == (200, "asset:/"), (s, b)
s, b, h = await call("POST", "/feeds", "url=https%3A%2F%2Ffeeds.example%2Frss", c)
assert json.loads(b) == {"feed_url": "https://feeds.example/rss", "added": 1}, b
s, b, h = await call("POST", "/feeds", "url=https%3A%2F%2Ffeeds.example%2Fgone&category=", c)
assert "404" in json.loads(b)["error"], b
s, b, h = await call("GET", "/feeds", cookie=c)
feeds = json.loads(b); assert feeds[1]["title"] == "T" and feeds[0]["favicon_url"] == "", feeds
s, b, h = await call("GET", "/articles?status=all", cookie=c)
(a,) = json.loads(b); assert a["title"] == "Hello & bye" and a["published"] == "2025-06-10T04:00:00Z" and a["is_read"] is False, a
s, b, h = await call("POST", "/read", f"id={a['id']}", c); assert s == 200, (s, b)
s, b, h = await call("GET", "/unread", cookie=c); assert json.loads(b) == {"count": 0}, b
s, b, h = await call("GET", "/articles?q=hello", cookie=c); assert len(json.loads(b)) == 1, b
s, b, h = await call("DELETE", "/feeds?url=https%3A%2F%2Ffeeds.example%2Fgone", cookie=c); assert s == 200
fd = js.FormData.new(); fd.append("opml", '<opml><body><outline text="x" xmlUrl="https://feeds.example/rss"/></body></opml>')
r = await w.fetch(JSREQ(O + "/opml", to_js({"method": "POST", "body": fd, "headers": {"cookie": c}}, dict_converter=js.Object.fromEntries)))
assert json.loads(str(await r.text()))["imported"] == 1
s, b, h = await call("GET", "/opml", cookie=c); assert "feeds.example/rss" in b and h.get("content-type").startswith("application/xml")
await w.scheduled(None, None, None)

# WebCrypto: a DPoP proof that verifies with the public key it carries.
crypto = WebCrypto()
key = await crypto.generate_key()
proof = await oauth.dpop_proof(crypto, key, "POST", "https://a.example/t?x=1", "n")
RESULT = proof
res = await Http().request("GET", "https://feeds.example/rss", headers={"User-Agent": "t"})
assert res.status == 200 and res.headers["x-test"] == "1" and res.body.startswith(b"<?xml")
print("python side ok")
`);
const proof = py.globals.get("RESULT");
const [h, p, s] = proof.split(".");
const dec = (x) => Buffer.from(x, "base64url");
const header = JSON.parse(dec(h));
const pub = await crypto.subtle.importKey("jwk", header.jwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
const ok = await crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, pub, dec(s), new TextEncoder().encode(`${h}.${p}`));
if (!ok) throw new Error("DPoP signature did not verify");
console.log("dpop ok", JSON.parse(dec(p)).htu);
