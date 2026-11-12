"""Vercel serverless entry point for the INMS Flask application.

Vercel's Python runtime imports this module and looks for a WSGI callable
named ``app``.  The real application lives in ``app.py`` at the project root;
this file only makes sure that directory is importable.

Routing note
------------
``vercel.json`` rewrites every request onto ``/api/index``.  On this project the
runtime then delivers ``PATH_INFO = "/api/index"`` to the WSGI application, so
Flask would 404 every real page (``/login``, ``/``, ...).  Before dispatching,
the original path is recovered - first from a header if the platform supplies
one, otherwise from the ``__path`` query parameter the rewrite captures - and
written back into ``PATH_INFO``.

If the application cannot start (for example a missing Firebase environment
variable), a small diagnostic WSGI app is exported instead of crashing with an
opaque "FUNCTION_INVOCATION_FAILED".  That makes production misconfiguration
visible without reading the deployment logs, and never exposes secret values.
"""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import unquote

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Headers that some hosting layers use to carry the pre-rewrite path.
_ORIGINAL_PATH_HEADERS = (
    "HTTP_X_ORIGINAL_URL",
    "HTTP_X_REWRITE_URL",
    "HTTP_X_FORWARDED_PATH",
    "HTTP_X_PATH",
)

_CAPTURED_QUERY_KEY = "__path"


def _looks_like_a_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("/")
        and "$" not in value
        and value != "/api/index"
        and " " not in value
    )


def restore_original_path(environ: dict) -> None:
    """Point PATH_INFO at the path the browser actually requested."""
    for header in _ORIGINAL_PATH_HEADERS:
        candidate = str(environ.get(header) or "").split("?")[0]
        if _looks_like_a_path(candidate):
            environ["PATH_INFO"] = candidate
            return

    query = str(environ.get("QUERY_STRING") or "")
    if _CAPTURED_QUERY_KEY + "=" not in query:
        return

    kept: list = []
    captured: str | None = None
    for part in query.split("&"):
        name, _, value = part.partition("=")
        if name == _CAPTURED_QUERY_KEY:
            captured = unquote(value)
        elif part:
            kept.append(part)

    captured_query = ""
    if captured and "?" in captured:
        # The capture can carry a query string of its own (e.g. /interns?q=1).
        captured, _, captured_query = captured.partition("?")
        if captured_query:
            kept.append(captured_query)

    environ["QUERY_STRING"] = "&".join(kept)
    if _looks_like_a_path(captured):
        environ["PATH_INFO"] = captured


def _diagnostic_app(exc: BaseException):
    """Minimal WSGI app returned when the Flask app cannot be imported."""

    detail = f"{type(exc).__name__}: {exc}".strip()
    # Keep only the first lines: enough to identify the cause, nothing secret.
    detail = " | ".join(line.strip() for line in detail.splitlines() if line.strip())[:900]

    def application(environ, start_response):
        body = json.dumps(
            {
                "status": "error",
                "reason": "INMS could not start on Vercel",
                "detail": detail,
                "hint": (
                    "Check Settings -> Environment Variables (Production): "
                    "FIREBASE_PROJECT_ID, FIREBASE_STORAGE_BUCKET, "
                    "FIREBASE_WEB_API_KEY, FIREBASE_CREDENTIALS (base64), "
                    "FLASK_SECRET_KEY, FIREBASE_USE_EMULATORS=0. "
                    "Then redeploy."
                ),
            },
            indent=2,
        ).encode("utf-8")
        start_response(
            "503 Service Unavailable",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Cache-Control", "no-store"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]

    return application


try:
    # Re-exported for Vercel: `app` is the WSGI application.
    from app import app as _flask_app  # noqa: E402

    class _PathAwareApp:
        """WSGI wrapper that restores the pre-rewrite path before dispatch."""

        def __call__(self, environ, start_response):
            restore_original_path(environ)
            return _flask_app(environ, start_response)

    app = _PathAwareApp()
except BaseException as exc:  # noqa: BLE001 - SystemExit is raised by app.py
    app = _diagnostic_app(exc)
