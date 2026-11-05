"""CPython stand-ins for what entry.py gets from the Workers runtime: D1 over
sqlite3, fetch over a table of canned responses, WebCrypto over `cryptography`,
and a client that sends requests through the FastAPI app as the Workers ASGI
adapter would.
"""

import asyncio
import pathlib
import sys

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pulseboard import databases  # noqa: E402
from pulseboard.api import ASSET_HEADER, create_api  # noqa: E402
from pulseboard.app import App  # noqa: E402
from pulseboard.oauth import b64url  # noqa: E402


class SqliteDb(databases.SqliteDb):
    """An in-memory database with the schema already applied."""

    def __init__(self):
        super().__init__(":memory:")
        for migration in sorted((ROOT / "migrations").glob("*.sql")):
            self.conn.executescript(migration.read_text())


class Res:
    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self.body = body.encode() if isinstance(body, str) else body
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


class FakeHttp:
    """Routes keyed on (method, url) or url; a value may be a Res or a
    callable taking (method, url, headers, body)."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []

    async def request(self, method, url, headers=None, body=None):
        self.calls.append((method, url, headers or {}, body))
        handler = self.routes.get((method, url), self.routes.get(url))
        if handler is None:
            return Res(404, "not found")
        if callable(handler):
            return handler(method, url, headers or {}, body)
        return handler


class SoftCrypto:
    async def generate_key(self):
        key = ec.generate_private_key(ec.SECP256R1())
        n = key.private_numbers()
        def enc(i):
            return b64url(i.to_bytes(32, "big"))
        return {"kty": "EC", "crv": "P-256", "x": enc(n.public_numbers.x),
                "y": enc(n.public_numbers.y), "d": enc(n.private_value)}

    async def sign(self, jwk, data):
        import base64
        d = int.from_bytes(base64.urlsafe_b64decode(jwk["d"] + "=="), "big")
        key = ec.derive_private_key(d, ec.SECP256R1())
        r, s = decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")


class Resp:
    def __init__(self, r: httpx.Response):
        self.status = r.status_code
        self.body = r.text
        self.headers = r.headers
        self.asset = r.headers.get(ASSET_HEADER)


class Api:
    """The FastAPI app over one `App`, with the cron trigger alongside. Each
    request gets a fresh client, so no cookie is kept between them: tests say
    which session they send."""

    def __init__(self, origin, *args):
        self.origin = origin
        self.app = App(*args)
        self.asgi = create_api(lambda request: self.app)

    async def handle(self, req):
        method, path, cookie, params = req
        headers = {"cookie": cookie} if cookie else {}
        transport = httpx.ASGITransport(app=self.asgi, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=self.origin) as client:
            url = "/" + path.strip("/")
            if method in ("POST", "PUT"):
                r = await client.request(method, url, data=params, headers=headers)
            else:
                r = await client.request(method, url, params=params, headers=headers)
        return Resp(r)

    async def scheduled(self, *args, **kwargs):
        await self.app.scheduled(*args, **kwargs)


@pytest.fixture
def db():
    return SqliteDb()


def run(coro):
    return asyncio.run(coro)
