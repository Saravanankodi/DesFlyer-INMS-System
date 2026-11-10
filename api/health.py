"""Diagnostic endpoint:  GET /api/health

Reports whether the deployment can reach Firebase, without ever exposing a
secret value.  Use it to tell "missing environment variable" apart from
"network / credentials problem" when the site returns HTTP 500.

Response example (healthy):
    {
      "status": "ok",
      "project": "desflyer-inms",
      "bucket": "desflyer-inms.firebasestorage.app",
      "mode": "production",
      "env": { "FIREBASE_PROJECT_ID": true, ... },
      "checks": { "credentials": "ok", "firestore": "ok", "auth": "ok" }
    }
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

REQUIRED = (
    "FIREBASE_PROJECT_ID",
    "FIREBASE_STORAGE_BUCKET",
    "FIREBASE_WEB_API_KEY",
    "FIREBASE_CREDENTIALS",
    "FLASK_SECRET_KEY",
    "FIREBASE_USE_EMULATORS",
)

OPTIONAL_CREDENTIAL_NAMES = ("FIREBASE_CREDENTIALS_FILE", "GOOGLE_APPLICATION_CREDENTIALS")


def _short(exc: BaseException, limit: int = 400) -> str:
    text = f"{type(exc).__name__}: {exc}".replace("\n", " ").strip()
    return text[:limit]


def collect() -> dict:
    payload: dict = {"status": "error", "checks": {}}

    try:
        import firebase_config

        firebase_config._load_dotenv()
    except Exception as exc:  # noqa: BLE001
        payload["env"] = {}
        payload["reason"] = "Cannot import firebase_config"
        payload["detail"] = _short(exc)
        return payload

    payload["env"] = {name: bool(os.environ.get(name)) for name in REQUIRED}
    payload["optional_env"] = {
        name: bool(os.environ.get(name)) for name in OPTIONAL_CREDENTIAL_NAMES
    }

    missing = [name for name in REQUIRED if not os.environ.get(name)]
    # Credentials may also come from a file (local development); on Vercel the
    # inline FIREBASE_CREDENTIALS value is the only option.
    if "FIREBASE_CREDENTIALS" in missing:
        file_path = os.environ.get("FIREBASE_CREDENTIALS_FILE") or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        if file_path and os.path.exists(os.path.expanduser(file_path)):
            missing.remove("FIREBASE_CREDENTIALS")
    if missing:
        payload["reason"] = "Missing environment variable(s): " + ", ".join(missing)
        payload["hint"] = (
            "Add them in Vercel -> Settings -> Environment Variables (Production), "
            "then redeploy."
        )
        return payload

    try:
        firebase_config.init_firebase()
        settings = firebase_config.settings()
    except Exception as exc:  # noqa: BLE001
        payload["reason"] = "Firebase initialisation failed"
        payload["detail"] = _short(exc)
        return payload

    payload["project"] = settings.project_id
    payload["bucket"] = settings.storage_bucket
    payload["mode"] = "emulators" if settings.use_emulators else "production"
    payload["checks"]["credentials"] = "ok"

    try:
        db = firebase_config.firestore_client()
        users = list(db.collection("users").limit(1).stream())
        payload["checks"]["firestore"] = f"ok ({len(users)} user doc(s) sampled)"
    except Exception as exc:  # noqa: BLE001
        payload["checks"]["firestore"] = "failed: " + _short(exc)
        payload["trace"] = traceback.format_exc().splitlines()[-3:]
        payload["reason"] = "Firestore is not reachable from Vercel"
        return payload

    try:
        firebase_config.auth_client().list_users(max_results=1)
        payload["checks"]["auth"] = "ok"
    except Exception as exc:  # noqa: BLE001
        payload["checks"]["auth"] = "failed: " + _short(exc)
        payload["reason"] = "Firebase Authentication is not reachable from Vercel"
        return payload

    payload["status"] = "ok"
    payload.pop("reason", None)
    return payload


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - Vercel contract
        payload = collect()
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
