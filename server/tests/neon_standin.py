"""A stand-in for Neon's SQL-over-HTTP endpoint, in front of a local Postgres,
so the server's tests run without a Neon account.

    POST /sql   {"query": "...", "params": [...]}       -> {"rows": [...], "rowCount": n, ...}
                {"queries": [{"query", "params"}, ...]} -> {"results": [...]} (one transaction)

Like Neon with `Neon-Raw-Text-Output: true`, every value comes back as
Postgres's own text for it (or null), and parameters go to Postgres untyped.
The connection string comes from the `Neon-Connection-String` header.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
from psycopg.adapt import Loader
from psycopg.rows import dict_row


class TextLoader(Loader):
    def load(self, data):
        return bytes(data).decode()


def connect(url: str) -> psycopg.Connection:
    conn = psycopg.connect(url, autocommit=True, row_factory=dict_row,
                           cursor_factory=psycopg.RawCursor)  # $1 placeholders
    for info in psycopg.postgres.types:
        conn.adapters.register_loader(info.oid, TextLoader)
    return conn


def run(conn, q: dict) -> dict:
    cur = conn.execute(q["query"], q.get("params") or [], prepare=False)
    rows = cur.fetchall() if cur.description else []
    return {
        "command": (cur.statusmessage or "").split(" ")[0],
        "rowCount": cur.rowcount if cur.rowcount >= 0 else len(rows),
        "rows": rows,
        "fields": [{"name": d.name, "dataTypeID": d.type_code} for d in (cur.description or [])],
        "rowAsArray": False,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status: int, doc: dict):
        body = json.dumps(doc).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/sql":
            return self.reply(404, {"message": "not found"})
        if self.headers.get("Neon-Raw-Text-Output") != "true":
            return self.reply(400, {"message": "the server expects raw text output"})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        self.server.queries += 1
        try:
            with connect(self.headers["Neon-Connection-String"]) as conn:
                if "queries" in body:
                    with conn.transaction():
                        results = [run(conn, q) for q in body["queries"]]
                    return self.reply(200, {"results": results})
                return self.reply(200, run(conn, body))
        except psycopg.Error as exc:
            return self.reply(400, {"message": str(exc).strip(),
                                    "code": getattr(exc, "sqlstate", None)})


def start(port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.queries = 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    import sys
    s = start(int(sys.argv[1]) if len(sys.argv) > 1 else 5480)
    print(f"Neon stand-in on http://127.0.0.1:{s.server_port}/sql", flush=True)
    threading.Event().wait()
