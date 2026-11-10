"""Minimal runtime probe:  GET /api/ping  ->  "pong"."""

def app(environ, start_response):
    body = b"pong"
    start_response("200 OK", [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ])
    return [body]