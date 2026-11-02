#!/usr/bin/env python3
"""Stdlib stand-in for the Jev sizing endpoint (https://api.typesafe.ai/v1/systemone), for offline tests.

Behaviour comes from the query string of each request URL, falling back to server defaults:
    ?size=tiny|everyday|large|hardest   the choice (default tiny)
    &p=0.9                              probability of the choice (default 0.9)
    &delay=1.5                          seconds to sleep before answering (default 0)
    &status=500                         HTTP error to return instead of an answer (default 200)
The server counts POSTs in `hits` and keeps the last request body in `last_body`.

Standalone: FAKE_JEV_SIZE / FAKE_JEV_P / FAKE_JEV_DELAY / FAKE_JEV_STATUS set the defaults;
    python3 tests/fake_jev.py [port]     prints the URL to put in JEV_ROUTER_URL.
"""
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SIZES = ("tiny", "everyday", "large", "hardest")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):  # keep test output quiet
        pass

    def do_POST(self):
        srv = self.server
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        with srv.lock:
            srv.hits += 1
            srv.last_body = body
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        q = {k: v[0] for k, v in query.items()}
        size = q.get("size", srv.size)
        p = float(q.get("p", srv.p))
        delay = float(q.get("delay", srv.delay))
        status = int(q.get("status", srv.status))
        if delay:
            time.sleep(delay)
        if status != 200:
            self.send_error(status)
            return
        if not self.headers.get("Authorization", "").startswith("Bearer "):
            self.send_error(401)
            return
        if size not in SIZES:
            self.send_error(400)
            return
        others = (1 - p) / (len(SIZES) - 1)
        probs = {s: (p if s == size else others) for s in SIZES}
        data = json.dumps({
            "answers": {"size": {"choice": size, "probabilities": probs, "confidence": 0.9}},
            "usage": {"input_tokens": 42},
        }).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:  # the client gave up (timeout test): nothing to do
            pass


def _configure(srv, size, p, delay, status):
    srv.daemon_threads = True
    srv.lock = threading.Lock()
    srv.hits = 0
    srv.last_body = None
    srv.size, srv.p, srv.delay, srv.status = size, p, delay, status
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}/v1/systemone"
    return srv


def start(size="tiny", p=0.9, delay=0.0, status=200):
    """Start the fake on a free local port in a background thread. Caller calls shutdown()."""
    srv = _configure(ThreadingHTTPServer(("127.0.0.1", 0), Handler), size, p, delay, status)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = _configure(ThreadingHTTPServer(("127.0.0.1", port), Handler),
                     os.environ.get("FAKE_JEV_SIZE", "tiny"),
                     float(os.environ.get("FAKE_JEV_P", "0.9")),
                     float(os.environ.get("FAKE_JEV_DELAY", "0")),
                     int(os.environ.get("FAKE_JEV_STATUS", "200")))
    print(f"fake Jev on {srv.url}", flush=True)
    srv.serve_forever()
