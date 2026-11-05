"""Entry point for FastAPI Cloud (and `fastapi dev` / `fastapi run` here):
the server in worker/src/pulseboard/server.py. Its docstring lists the
environment variables it reads."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "worker" / "src"))

from pulseboard.server import app  # noqa: E402

__all__ = ["app"]
