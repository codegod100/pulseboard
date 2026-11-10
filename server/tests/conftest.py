"""Run the built component under `wasmtime serve` and talk to it over HTTP.

What the component reaches out to is faked here:

- Neon: neon_standin.py, in front of a fresh Postgres database per test
  (PULSEBOARD_TEST_POSTGRES names the server, as an admin URL);
- everyone else (feeds, AT Protocol sign-in): an `Upstream` server. With
  PULSEBOARD_TEST_UPSTREAM set, the component sends every outgoing request
  there, with the URL it meant in an X-Test-Original-Url header.

Environment: PULSEBOARD_COMPONENT (the .wasm, default
server/build/pulseboard-server.wasm), WASMTIME (default: on PATH).
"""

import os
import pathlib
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg
import pytest

import neon_standin

HERE = pathlib.Path(__file__).resolve().parent
COMPONENT = pathlib.Path(os.environ.get("PULSEBOARD_COMPONENT", HERE.parent / "build" / "pulseboard-server.wasm"))
WASMTIME = os.environ.get("WASMTIME") or shutil.which("wasmtime") or "wasmtime"
PG_ADMIN = os.environ.get("PULSEBOARD_TEST_POSTGRES", "postgresql://postgres@127.0.0.1:5432/postgres")
CRON_SECRET = "test-cron-secret"


class Res:
    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self.body = body.encode() if isinstance(body, str) else body
        self.headers = dict(headers or {})


class Upstream:
    """Routes keyed on (method, url) or url; a value is a Res or a callable
    taking (method, url, headers, body) and returning one."""

    def __init__(self):
        self.routes = {}
        self.calls = []
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def version_string(self):
                # A route's own Server header replaces this one.
                return getattr(self, "server_header", None) or super().version_string()

            def handle_any(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n).decode() if n else None
                url = self.headers.get("X-Test-Original-Url", "")
                headers = httpx.Headers(list(self.headers.items()))
                upstream.calls.append((self.command, url, headers, body))
                handler = upstream.routes.get((self.command, url), upstream.routes.get(url))
                if handler is None:
                    res = Res(404, "not found")
                elif callable(handler):
                    res = handler(self.command, url, headers, body)
                else:
                    res = handler
                headers = dict(res.headers)
                self.server_header = headers.pop("Server", None)
                self.send_response(res.status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(res.body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(res.body)

            do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = handle_any

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def fetched(self, url):
        return [c for c in self.calls if c[1] == url]


@pytest.fixture(scope="session")
def neon():
    s = neon_standin.start()
    yield f"http://127.0.0.1:{s.server_port}/sql"
    s.shutdown()


@pytest.fixture(scope="session")
def compiled(tmp_path_factory):
    """The component compiled once for the host, so each server starts fast."""
    if not COMPONENT.exists():
        pytest.exit(f"{COMPONENT} does not exist: build it first (see server/README.md)")
    out = tmp_path_factory.mktemp("cwasm") / "server.cwasm"
    subprocess.run([WASMTIME, "compile", "-o", str(out), str(COMPONENT)], check=True)
    return out


def new_database(request) -> str:
    name = "pb_test_" + secrets.token_hex(4)
    with psycopg.connect(PG_ADMIN, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name}")

    def drop():
        with psycopg.connect(PG_ADMIN, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    request.addfinalizer(drop)
    return urlunsplit(urlsplit(PG_ADMIN)._replace(path="/" + name))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """One `wasmtime serve` of the component, its database, and its world."""

    def __init__(self, compiled, neon_url, db_url, static, upstream, env=None):
        self.db_url = db_url
        self.upstream = upstream
        self.port = free_port()
        environ = {
            "DATABASE_URL": db_url,
            "NEON_SQL_URL": neon_url,
            "PULSEBOARD_TEST_UPSTREAM": upstream.origin,
            "PULSEBOARD_TEST_HOOKS": "1",
            "CRON_SECRET": CRON_SECRET,
            **(env or {}),
        }
        cmd = [WASMTIME, "serve", "--allow-precompiled", "-S", "cli=y",
               "--addr", f"127.0.0.1:{self.port}", "--dir", f"{static}::/dist"]
        for k in environ:
            cmd += ["--env", k]
        self.log = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(cmd + [str(compiled)], env={**os.environ, **environ},
                                     stdout=self.log, stderr=subprocess.STDOUT)
        self.base = f"http://127.0.0.1:{self.port}"
        for _ in range(100):
            try:
                httpx.get(self.base + "/health", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            raise RuntimeError("the server did not start:\n" + self.output())

    def output(self) -> str:
        self.log.seek(0)
        return self.log.read().decode(errors="replace")

    def request(self, method, path, cookie="", headers=None, content=None, **params):
        h = {"host": "pulseboard.example", "x-forwarded-proto": "https", **(headers or {})}
        if cookie:
            h["cookie"] = cookie
        url = self.base + "/" + path.strip("/")
        with httpx.Client(timeout=60, follow_redirects=False) as c:
            if content is not None:
                return c.request(method, url, content=content, headers=h)
            if method in ("POST", "PUT"):
                return c.request(method, url, data=params, headers=h)
            return c.request(method, url, params=params, headers=h)

    def internal(self, what, **params):
        r = self.request("POST", "internal/" + what, headers={"x-pulseboard-cron": CRON_SECRET}, **params)
        assert r.status_code == 200, r.text
        return r.json()

    def sql(self, query, params=()):
        with psycopg.connect(self.db_url, autocommit=True) as conn:
            cur = conn.execute(query, params)
            return cur.fetchall() if cur.description else cur.rowcount

    def close(self):
        self.proc.terminate()
        self.proc.wait(5)


@pytest.fixture
def static(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text("<!doctype html>client")
    (d / "pulseboard.wasm").write_bytes(b"\0asm")
    (tmp_path / "secret.txt").write_text("no")
    return d


@pytest.fixture
def make_server(request, compiled, neon, static):
    servers = []

    def make(env=None, migrate=True):
        s = Server(compiled, neon, new_database(request), static, Upstream(), env)
        servers.append(s)
        if migrate:
            s.internal("migrate")
        return s

    yield make
    for s in servers:
        s.close()
        if request.node.rep_call.failed if hasattr(request.node, "rep_call") else False:
            print(s.output())


@pytest.fixture
def server(make_server):
    return make_server()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)
