"""Prepare the value of the FIREBASE_CREDENTIALS environment variable for Vercel.

Vercel functions cannot read local files, so the service-account key has to be
passed inline.  A JSON key contains newlines, which environment variables and
web forms handle badly, so the key is base64-encoded into a single line.

This script:

1. reads ``secrets/firebase-service-account.json``;
2. re-encodes it and verifies that the encoded text decodes back to the same key;
3. writes the one-line value to ``vercel-credentials-base64.txt`` (git-ignored);
4. copies it to the clipboard when possible;
5. prints the exact length the Vercel value must have.

Usage (from the project folder):

    python prepare_vercel_env.py

Then open ``vercel-credentials-base64.txt``, select everything (Ctrl+A),
copy (Ctrl+C) and paste it into Vercel -> Settings -> Environment Variables
-> FIREBASE_CREDENTIALS (Production).
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

    print("[PASS] project      ->", key.get("project_id"))
    print("[PASS] client_email ->", key.get("client_email"))
    print("[PASS] key size     ->", f"{len(raw)} bytes")
    print("[PASS] round-trip   -> decodes back to the same private key")
    print()
    print(f"FIREBASE_CREDENTIALS must be exactly {len(value)} characters.")
    print(f"Value written to   : {OUTPUT_FILE}")
    print(f"Clipboard          : {_copy_to_clipboard(value)}")
    print()
    print("Next: Vercel -> Settings -> Environment Variables -> FIREBASE_CREDENTIALS")
    print("      -> Edit -> select all -> paste -> Save -> Redeploy.")
    print("Then open /login: the diagnostic page shows the received length.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
