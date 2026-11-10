"""Minimal runtime probe:  GET /api/ping  ->  "pong".

Used only to verify that Vercel's Python runtime and routing work, with no
project imports at all. Safe to delete once the deployment is healthy.
"""

from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - Vercel contract
        body = b"pong"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
