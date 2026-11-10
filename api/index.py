"""Vercel serverless entry point for the INMS Flask application.

Vercel's Python runtime imports this module and looks for a WSGI callable
named ``app``.  The real application lives in ``app.py`` at the project root;
this file only makes sure that directory is importable.

If the application cannot start (for example a missing Firebase environment
variable), a small diagnostic WSGI app is exported instead of crashing with an
opaque "FUNCTION_INVOCATION_FAILED".  That makes production misconfiguration
visible without reading the deployment logs, and never exposes secret values.

Nothing here changes the application behaviour - every route, template,
validation rule and Firebase call is exactly the same as in local development.
"""

from __future__ import annotations

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


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
    from app import app  # noqa: E402,F401
except BaseException as exc:  # noqa: BLE001 - SystemExit is raised by app.py
    app = _diagnostic_app(exc)
