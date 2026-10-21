"""The Worker: adapts Cloudflare's runtime (D1, fetch, WebCrypto, static
assets) to the plain-Python reader in `pulseboard/`.

Everything Workers-specific lives in this file, so the rest can be tested
under CPython against SQLite.
"""

from urllib.parse import parse_qsl, urlsplit

import js
from pyodide.ffi import JsProxy, to_js
from workers import Response, WorkerEntrypoint

from pulseboard.app import App, Req

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


class Default(WorkerEntrypoint):
    def _app(self):
        return App(D1(self.env.DB), Http(), WebCrypto())

    async def fetch(self, request):
        jsreq = getattr(request, "js_object", request)
        url = urlsplit(str(jsreq.url))
        method = str(jsreq.method).upper()
        params = parse_qsl(url.query, keep_blank_values=True)
        if method in ("POST", "PUT", "DELETE"):
            ctype = str(jsreq.headers.get("content-type") or "")
            if "application/x-www-form-urlencoded" in ctype or not ctype:
                params += parse_qsl(str(await jsreq.text()), keep_blank_values=True)
            elif "multipart/form-data" in ctype:
                form = await jsreq.formData()
                for pair in form.entries():
                    k, v = pair.to_py() if isinstance(pair, JsProxy) else pair
                    if isinstance(v, str):
                        params.append((k, v))
        req = Req(
            method=method,
            path=url.path.strip("/"),
            params=params,
            cookie=str(jsreq.headers.get("cookie") or ""),
            origin=f"{url.scheme}://{url.netloc}",
        )
        resp = await self._app().handle(req)
        if resp.asset is not None:
            assets = _raw(self.env.ASSETS)
            if resp.asset == "/" + req.path:
                res = await assets.fetch(jsreq)
            else:
                res = await assets.fetch(js.Request.new(
                    req.origin + resp.asset, _js({"method": "GET", "headers": jsreq.headers})))
            return Response(res)
        return Response(resp.body, status=resp.status, headers=resp.headers)

    async def scheduled(self, *args):
        await self._app().scheduled()
