"""A tiny web server for watching the village live and replaying its history.

Endpoints:
  /                 the viewer page
  /api/info         {"frames": N, "live": bool}
  /api/frame/<n>    frame n from history (-1 = latest)
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC = Path(__file__).parent / "static"


class History:
    """Index of a history.jsonl file by line offset, refreshed as it grows."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.offsets: list[int] = []
        self._scanned = 0
        self._lock = threading.Lock()

    def refresh(self) -> int:
        with self._lock:
            if not self.path.exists():
                return 0
            with open(self.path, "rb") as f:
                f.seek(self._scanned)
                pos = self._scanned
                for line in f:
                    if not line.endswith(b"\n"):
                        break   # partially written; pick it up next time
                    self.offsets.append(pos)
                    pos += len(line)
                self._scanned = pos
            return len(self.offsets)

    def get(self, n: int) -> bytes | None:
        count = self.refresh()
        if not count:
            return None
        n = count - 1 if n < 0 else min(n, count - 1)
        with open(self.path, "rb") as f:
            f.seek(self.offsets[n])
            return f.readline().rstrip(b"\n")


def serve(history: History, port: int = 8000, sim=None, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, body: bytes, ctype: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._send((STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/info":
                info = {"frames": history.refresh(), "live": sim is not None}
                return self._send(json.dumps(info).encode(), "application/json")
            if path.startswith("/api/frame/"):
                try:
                    n = int(path.rsplit("/", 1)[1])
                except ValueError:
                    return self._send(b"bad frame", "text/plain", 400)
                body = history.get(n)
                if body is None and sim is not None and sim.latest_frame:
                    body = json.dumps(sim.latest_frame).encode()
                if body is None:
                    return self._send(b"no frames yet", "text/plain", 404)
                return self._send(body, "application/json")
            self._send(b"not found", "text/plain", 404)

    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
