"""Pulseboard as an ordinary FastAPI server, for FastAPI Cloud (or anywhere
uvicorn runs). The routes are the same api.py the Worker serves; this module
supplies what Cloudflare otherwise would:

- storage: Postgres (Neon) when DATABASE_URL is set, else a local SQLite
  file (PULSEBOARD_DB, default pulseboard.db), migrated on startup;
- outgoing HTTP: httpx;
- DPoP signing: `cryptography` instead of WebCrypto;
- the Qt client: files from web/dist (PULSEBOARD_STATIC to override);
- the cron trigger: a loop that refreshes due feeds every 30 minutes
  (REFRESH_EVERY_MINUTES; 0 turns it off).

PUBLIC_ORIGIN (e.g. https://pulseboard.fastapicloud.dev) pins the origin used
for AT Protocol sign-in; without it, the request's own (proxy-aware) origin is
used.
"""

import asyncio
import base64
import contextlib
import logging
import mimetypes
import os
import pathlib

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from .api import ASSET_HEADER, create_api
from .app import App
from .databases import PostgresDb, SqliteDb, migrate
from .oauth import b64url

log = logging.getLogger("pulseboard")

REPO = pathlib.Path(__file__).resolve().parents[3]
FETCH_TIMEOUT = 15.0
mimetypes.add_type("application/wasm", ".wasm")


class HttpResponse:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status = status
        self.headers = headers
        self.body = body


class Http:
    """The `request` interface feeds.py and oauth.py use, over httpx."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def request(self, method, url, headers=None, body=None):
        res = await self.client.request(method, url, headers=headers or {}, content=body)
        return HttpResponse(res.status_code, {k.lower(): v for k, v in res.headers.items()},
                            res.content)


class Crypto:
    """ES256 keys and signatures for DPoP, as WebCrypto gives the Worker."""

    async def generate_key(self):
        n = ec.generate_private_key(ec.SECP256R1()).private_numbers()

        def enc(i):
            return b64url(i.to_bytes(32, "big"))
        return {"kty": "EC", "crv": "P-256", "x": enc(n.public_numbers.x),
                "y": enc(n.public_numbers.y), "d": enc(n.private_value)}

    async def sign(self, jwk, data: bytes) -> bytes:
        d = int.from_bytes(base64.urlsafe_b64decode(jwk["d"] + "=="), "big")
        key = ec.derive_private_key(d, ec.SECP256R1())
        r, s = decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def open_db():
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return PostgresDb(url)
    path = os.environ.get("PULSEBOARD_DB", "pulseboard.db")
    log.warning("DATABASE_URL is not set; using the local SQLite file %s", path)
    return SqliteDb(path)


async def refresh_loop(app: App, minutes: float):
    while True:
        await asyncio.sleep(minutes * 60)
        try:
            await app.scheduled()
        except Exception:
            log.exception("scheduled refresh failed")


def static_file(root: pathlib.Path, path: str):
    """The file under `root` for a URL path, or None. "/" is the client."""
    rel = path.lstrip("/") or "index.html"
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def build(db=None, http_client: httpx.AsyncClient | None = None,
          static: pathlib.Path | None = None,
          refresh_minutes: float | None = None) -> FastAPI:
    """The server. Arguments override the environment (the tests use them)."""
    root = (static or pathlib.Path(os.environ.get("PULSEBOARD_STATIC", REPO / "web" / "dist"))).resolve()
    if refresh_minutes is None:
        refresh_minutes = float(os.environ.get("REFRESH_EVERY_MINUTES", "30"))
    public_origin = os.environ.get("PUBLIC_ORIGIN", "").rstrip("/")
    state = {}

    @contextlib.asynccontextmanager
    async def lifespan(api: FastAPI):
        client = http_client or httpx.AsyncClient(
            follow_redirects=True, timeout=FETCH_TIMEOUT)
        database = db or open_db()
        await database.open()
        applied = await migrate(database)
        if applied:
            log.info("applied migrations: %s", ", ".join(applied))
        state["app"] = App(database, Http(client), Crypto())
        task = None
        if refresh_minutes > 0:
            task = asyncio.create_task(refresh_loop(state["app"], refresh_minutes))
        try:
            yield
        finally:
            if task:
                task.cancel()
            if http_client is None:
                await client.aclose()
            if db is None:
                await database.close()

    api = create_api(lambda request: state["app"], lifespan=lifespan, public_origin=public_origin)

    @api.middleware("http")
    async def serve_assets(request: Request, call_next):
        resp = await call_next(request)
        path = resp.headers.get(ASSET_HEADER)
        if path is None:
            return resp
        target = static_file(root, path)
        if target is None:
            return JSONResponse({"error": "not found"}, 404)
        headers = {"Cache-Control": "no-cache"} if target.suffix in (".html", ".js", ".wasm") else {}
        return FileResponse(target, headers=headers)

    return api


app = build()
