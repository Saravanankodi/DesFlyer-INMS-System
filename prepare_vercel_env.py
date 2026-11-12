"""Prepare the value of the FIREBASE_CREDENTIALS environment variable for Vercel.

Vercel functions cannot read local files, so the service-account key has to be
passed inline.  A JSON key contains newlines, which environment variables and
web forms handle badly, so the key is base64-encoded into a single line.

This script:

1. reads ``secrets/firebase-service-account.json``;
2. re-encodes it and verifies that the encoded text decodes back to the same key;
3. writes the one-line value to ``vercel-credentials-base64.txt`` (git-ignored);
4. builds ``vercel.env`` - a complete, import-ready environment file for Vercel;
5. copies the key to the clipboard when possible;
6. prints the exact length the Vercel value must have.

Usage (from the project folder):

    python prepare_vercel_env.py

Then, in Vercel: Settings -> Environment Variables -> Add -> **Import .env** ->
choose ``vercel.env`` -> tick **Production** -> Save -> Redeploy.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
KEY_FILE = PROJECT_ROOT / "secrets" / "firebase-service-account.json"
OUTPUT_FILE = PROJECT_ROOT / "vercel-credentials-base64.txt"
OUTPUT_ENV_FILE = PROJECT_ROOT / "vercel.env"
LOCAL_ENV_FILE = PROJECT_ROOT / ".env"

# Exactly the settings the application needs in production.  The key's file
# path is deliberately absent: Vercel cannot read local files, so the inline
# FIREBASE_CREDENTIALS value is the only credential transport there.
VERCEL_ENV_VARS = (
    "FIREBASE_PROJECT_ID",
    "FIREBASE_STORAGE_BUCKET",
    "FIREBASE_WEB_API_KEY",
    "FIREBASE_CREDENTIALS",
    "FLASK_SECRET_KEY",
    "FIREBASE_USE_EMULATORS",
)


def _read_local_env() -> dict:
    """Read KEY=VALUE pairs from the local .env (comments ignored)."""
    values: dict = {}
    if not LOCAL_ENV_FILE.exists():
        return values
    for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, raw = line.partition("=")
        values[name.strip()] = raw.strip().strip('"').strip("'")
    return values


def _copy_to_clipboard(text: str) -> str:
    if sys.platform != "win32":
        return "skipped (not Windows)"
    try:
        subprocess.run("clip", input=text.encode(), check=True, shell=True)
        return "copied"
    except Exception as exc:  # noqa: BLE001 - clipboard is a convenience only
        return f"not copied ({exc})"


def main() -> int:
    if not KEY_FILE.exists():
        print(f"[FAIL] key file not found: {KEY_FILE}")
        print("       Download it from Firebase Console -> Project settings ->")
        print("       Service accounts -> Generate new private key, then save it there.")
        return 1

    raw = KEY_FILE.read_bytes()
    try:
        key = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {KEY_FILE.name} is not valid JSON: {exc}")
        return 1

    value = base64.b64encode(raw).decode("ascii")

    # Round-trip check: the value pasted into Vercel must decode to the same key.
    decoded = json.loads(base64.b64decode(value).decode("utf-8"))
    if decoded.get("private_key") != key.get("private_key"):
        print("[FAIL] round-trip check failed - do not use this value")
        return 1

    OUTPUT_FILE.write_text(value, encoding="utf-8")

    # Build the import-ready .env for Vercel. Plain KEY=VALUE lines only: the
    # dashboard's "Import .env" creates one variable per line.
    local = _read_local_env()
    project_id = local.get("FIREBASE_PROJECT_ID") or key.get("project_id") or ""
    settings = {
        "FIREBASE_PROJECT_ID": project_id,
        "FIREBASE_STORAGE_BUCKET": local.get("FIREBASE_STORAGE_BUCKET")
        or f"{project_id}.firebasestorage.app",
        "FIREBASE_WEB_API_KEY": local.get("FIREBASE_WEB_API_KEY") or "",
        "FIREBASE_CREDENTIALS": value,
        "FLASK_SECRET_KEY": local.get("FLASK_SECRET_KEY") or "",
        "FIREBASE_USE_EMULATORS": "0",
    }
    missing = [name for name in VERCEL_ENV_VARS if not settings[name]]
    OUTPUT_ENV_FILE.write_text(
        "".join(f"{name}={settings[name]}\n" for name in VERCEL_ENV_VARS),
        encoding="utf-8",
        newline="\n",
    )

    print("[PASS] project      ->", key.get("project_id"))
    print("[PASS] client_email ->", key.get("client_email"))
    print("[PASS] key size     ->", f"{len(raw)} bytes")
    print("[PASS] round-trip   -> decodes back to the same private key")
    print()
    print(f"FIREBASE_CREDENTIALS must be exactly {len(value)} characters.")
    print(f"Key file written to    : {OUTPUT_FILE}")
    print(f"Vercel import file     : {OUTPUT_ENV_FILE}")
    print(f"Clipboard              : {_copy_to_clipboard(value)}")
    if missing:
        print()
        print("[FAIL] not found in .env, fill in manually: " + ", ".join(missing))
    print()
    print("Next: Vercel -> Settings -> Environment Variables -> Add -> Import .env")
    print("      -> choose vercel.env -> tick Production -> Save -> Redeploy.")
    print("Then open /login: the diagnostic page shows the received length.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
