"""The Worker: adapts Cloudflare's runtime (D1, fetch, WebCrypto, static
assets) to the plain-Python reader in `pulseboard/`, and hands requests to its
FastAPI app through the Workers ASGI adapter.

Everything Workers-specific lives in this file, so the rest can be tested
under CPython against SQLite.
"""

from urllib.parse import unquote

import js
from pyodide.ffi import JsProxy, to_js
from workers import WorkerEntrypoint, asgi

from pulseboard.api import ASSET_HEADER, create_api
from pulseboard.app import App

try:
    from pyodide.ffi import jsnull
except ImportError:  # older Pyodide: None already converts to null
    jsnull = None

FETCH_TIMEOUT_MS = 15_000


def _raw(binding):
    """The JS object behind the SDK's Python wrapper, if there is one."""
    for attr in ("_binding", "_env"):
        try:
            inner = getattr(binding, attr)
        except AttributeError:
            continue
        if inner is not None:
            return inner
    return binding


def _js(value):
    return to_js(value, dict_converter=js.Object.fromEntries)


def _py(value):
    if value is jsnull or value is None:
        return None
    if isinstance(value, JsProxy):
        value = value.to_py()
    if isinstance(value, dict):
        return {k: _py(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_py(v) for v in value]
    return value


class D1:
    def __init__(self, binding):
        self.db = _raw(binding)

    def _stmt(self, sql, params):
        stmt = self.db.prepare(sql)
        if params:
            stmt = stmt.bind(*[jsnull if p is None else p for p in params])
        return stmt

    async def all(self, sql, params=()):
        res = await self._stmt(sql, params).all()
        return _py(res.results) or []

    async def first(self, sql, params=()):
        rows = await self.all(sql, params)
        return rows[0] if rows else None

    async def run(self, sql, params=()):
        res = await self._stmt(sql, params).run()
        return int(_py(res.meta).get("changes", 0) or 0)

    async def batch(self, statements):
        if statements:
            await self.db.batch(to_js([self._stmt(sql, params) for sql, params in statements]))


class HttpResponse:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status = status
        self.headers = headers
        self.body = body


class Http:
    async def request(self, method, url, headers=None, body=None):
        init = {"method": method, "headers": headers or {}, "redirect": "follow",
                "signal": js.AbortSignal.timeout(FETCH_TIMEOUT_MS)}
        if body is not None:
            init["body"] = body
        res = await js.fetch(url, _js(init))
        data = (await res.arrayBuffer()).to_bytes()
        hdrs = {}
        for pair in res.headers.entries():
            k, v = pair.to_py() if isinstance(pair, JsProxy) else pair
            hdrs[str(k).lower()] = str(v)
        return HttpResponse(int(res.status), hdrs, data)


class WebCrypto:
    ALG = {"name": "ECDSA", "namedCurve": "P-256"}

    async def generate_key(self):
        pair = await js.crypto.subtle.generateKey(_js(self.ALG), True, _js(["sign", "verify"]))
        jwk = _py(await js.crypto.subtle.exportKey("jwk", pair.privateKey))
        return {k: jwk[k] for k in ("kty", "crv", "x", "y", "d")}

    async def sign(self, jwk, data: bytes) -> bytes:
        key = await js.crypto.subtle.importKey(
            "jwk", _js(jwk), _js(self.ALG), False, _js(["sign"]))
        sig = await js.crypto.subtle.sign(
            _js({"name": "ECDSA", "hash": "SHA-256"}), key, to_js(data))
        return sig.to_bytes()


def app_for(env) -> App:
    return App(D1(env.DB), Http(), WebCrypto())


# Built once per isolate; each request gets an App over that request's env.
api = create_api(lambda request: app_for(request.scope["env"]))


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        jsreq = getattr(request, "js_object", request)
        res = await asgi.fetch(api, jsreq, self.env)
        path = _py(res.headers.get(ASSET_HEADER))
        if not path:
            return res
        # The app said "serve this static file": fetch it from the assets
        # binding, so the client bundle never passes through Python.
        assets = _raw(self.env.ASSETS)
        url = js.URL.new(jsreq.url)
        if path == unquote(str(url.pathname)):
            return await assets.fetch(jsreq)
        return await assets.fetch(js.Request.new(
            str(url.origin) + path, _js({"method": "GET", "headers": jsreq.headers})))

    async def scheduled(self, *args):
        await app_for(self.env).scheduled()
