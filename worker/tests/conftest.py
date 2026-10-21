"""CPython stand-ins for what entry.py gets from the Workers runtime: D1 over
sqlite3, fetch over a table of canned responses, WebCrypto over `cryptography`.
"""

import asyncio
import pathlib
import sqlite3
import sys

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pulseboard.oauth import b64url  # noqa: E402


class SqliteDb:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript((ROOT / "migrations" / "0001_init.sql").read_text())

    async def all(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, list(params)).fetchall()]

    async def first(self, sql, params=()):
        rows = await self.all(sql, params)
        return rows[0] if rows else None

    async def run(self, sql, params=()):
        cur = self.conn.execute(sql, list(params))
        self.conn.commit()
        return cur.rowcount

    async def batch(self, statements):
        with self.conn:
            for sql, params in statements:
                self.conn.execute(sql, list(params))


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


@pytest.fixture
def db():
    return SqliteDb()


def run(coro):
    return asyncio.run(coro)
