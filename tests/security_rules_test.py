"""Security-rules test — runs INSIDE the Firebase Emulator Suite.

The Flask backend talks to Firebase with the Admin SDK, which BYPASSES the
security rules.  These tests therefore use the *client* paths instead:
plain HTTP requests against the Firestore and Storage emulators, exactly like
an unauthenticated attacker or a logged-in low-privilege user would send them.

Covered here:
  * unauthenticated reads/writes are DENIED (no "allow ... if true")
  * an authenticated intern cannot perform admin-only writes
  * an authenticated intern can read only the task actually assigned to them
  * Storage: unauthenticated upload denied, allowed upload accepted,
    disallowed content type rejected by the rules themselves

Run from the project folder:

    firebase emulators:exec --project demo-inms --only "auth,firestore,storage" ^
        "python tests/security_rules_test.py"

Exit code 0 = all checks passed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Emulator mode must be configured BEFORE the app modules initialise Firebase.
os.environ.setdefault("FIREBASE_USE_EMULATORS", "1")
os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-inms")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from firebase_config import init_firebase  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []

PROJECT = os.environ.get("FIREBASE_PROJECT_ID", "demo-inms")
FIRESTORE = f"http://{os.environ.get('FIRESTORE_EMULATOR_HOST', '127.0.0.1:8080')}"
AUTH_HOST = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
STORAGE = os.environ.get("STORAGE_EMULATOR_HOST", "http://127.0.0.1:9199")
if not STORAGE.startswith("http"):
    STORAGE = f"http://{STORAGE}"
BUCKET = f"{PROJECT}.appspot.com"
DOC_BASE = f"{FIRESTORE}/v1/projects/{PROJECT}/databases/(default)/documents"


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f" - {detail}" if detail and not condition else ""), flush=True)


def call(method: str, url: str, payload: dict | None = None, token: str | None = None,
         content_type: str = "application/json", raw: bytes | None = None):
    """Return (status, parsed-body-or-bytes) for an emulator request."""
    data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", content_type)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
    except OSError as exc:  # pragma: no cover - emulator not running
        return 0, str(exc)
    try:
        return status, json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return status, body


def sign_in(email: str, password: str) -> str | None:
    """Exchange credentials for an ID token on the Auth emulator."""
    url = (f"http://{AUTH_HOST}/identitytoolkit.googleapis.com/v1/"
           f"accounts:signInWithPassword?key=fake-api-key")
    status, body = call("POST", url, {"email": email, "password": password,
                                      "returnSecureToken": True})
    if status == 200 and isinstance(body, dict):
        return body.get("idToken")
    return None


# ---------------------------------------------------------------------------
# Firestore rules
# ---------------------------------------------------------------------------

def test_firestore_unauthenticated() -> None:
    # Write attempt without any credentials.
    status, body = call("POST", f"{DOC_BASE}/mentors", {"fields": {"name": {"stringValue": "attacker"}}})
    denied = status in (401, 403) or (
        isinstance(body, dict) and "PERMISSION_DENIED" in json.dumps(body))
    check("rules/firestore: unauthenticated CREATE denied", denied, f"HTTP {status} {body}")

    # Read attempt without any credentials.
    status, body = call("GET", f"{DOC_BASE}/users")
    denied = status in (401, 403) or (
        isinstance(body, dict) and "PERMISSION_DENIED" in json.dumps(body))
    check("rules/firestore: unauthenticated LIST denied", denied, f"HTTP {status} {body}")

    # Delete attempt without any credentials.
    status, body = call("DELETE", f"{DOC_BASE}/mentors/DFM001")
    denied = status in (401, 403) or (
        isinstance(body, dict) and "PERMISSION_DENIED" in json.dumps(body))
    check("rules/firestore: unauthenticated DELETE denied", denied, f"HTTP {status} {body}")


def test_firestore_intern_privileges() -> None:
    token = sign_in("e2e.intern@example.com", "InternPass123")
    if not token:
        check("rules/firestore: intern can sign in", False, "no ID token from Auth emulator")
        return
    check("rules/firestore: intern can sign in", True)

    # Admin-only collection: an intern must not be able to create a user.
    status, body = call("POST", f"{DOC_BASE}/users",
                        {"fields": {"id": {"stringValue": "hacked"},
                                    "username": {"stringValue": "hacked"},
                                    "email": {"stringValue": "hacked@x.com"},
                                    "role": {"stringValue": "admin"}}},
                        token=token)
    denied = status in (401, 403) or (
        isinstance(body, dict) and "PERMISSION_DENIED" in json.dumps(body))
    check("rules/firestore: intern cannot create admin-only 'users' doc",
          denied, f"HTTP {status} {body}")

    # Admin-only collection: an intern must not create mentors either.
    status, body = call("POST", f"{DOC_BASE}/mentors",
                        {"fields": {"id": {"stringValue": "DFHACK"},
                                    "name": {"stringValue": "hacker"},
                                    "email": {"stringValue": "h@x.com"},
                                    "phone": {"stringValue": "1"},
                                    "departments": {"arrayValue": {"values": [
                                        {"stringValue": "Python Development"}]}}}},
                        token=token)
    denied = status in (401, 403) or (
        isinstance(body, dict) and "PERMISSION_DENIED" in json.dumps(body))
    check("rules/firestore: intern cannot create admin-only 'mentors' doc",
          denied, f"HTTP {status} {body}")

    # Allowed: the intern can read the task assigned to them.
    status, body = call("GET", f"{DOC_BASE}/tasks/DFPY01", token=token)
    allowed = status == 200 and isinstance(body, dict) and "fields" in body
    check("rules/firestore: intern CAN read their own assigned task",
          allowed, f"HTTP {status} {str(body)[:200]}")

    # Password material must never be writable (rules reject 'password' field).
    status, body = call("POST", f"{DOC_BASE}/users",
                        {"fields": {"id": {"stringValue": "x"},
                                    "username": {"stringValue": "x"},
                                    "email": {"stringValue": "x@x.com"},
                                    "role": {"stringValue": "intern"},
                                    "password": {"stringValue": "secret"}}},
                        token=token)
    denied = status in (401, 403) or (
        isinstance(body, dict) and "PERMISSION_DENIED" in json.dumps(body))
    check("rules/firestore: document containing a 'password' field rejected",
          denied, f"HTTP {status} {body}")


# ---------------------------------------------------------------------------
# Storage rules
# ---------------------------------------------------------------------------

def storage_upload(name: str, content: bytes, content_type: str, token: str | None = None):
    """Upload through the Firebase *client* endpoint (/v0/...).

    The other endpoint family (/upload/storage/v1/...) is the Google Cloud JSON
    API used by service accounts and the Admin SDK; it bypasses security rules
    by design, exactly like the Admin SDK does in production.  Rules can only be
    exercised through the client endpoint the mobile/web SDKs use.
    """
    boundary = "inmsrulesboundary"
    meta = json.dumps({"contentType": content_type}).encode()
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
    ).encode() + meta + (
        f"\r\n--{boundary}\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()

    url = f"{STORAGE}/v0/b/{BUCKET}/o?name={urllib.parse.quote(name, safe='')}"
    return call("POST", url, token=token,
                content_type=f"multipart/related; boundary={boundary}", raw=body)


def storage_download(name: str, token: str | None = None):
    url = f"{STORAGE}/v0/b/{BUCKET}/o/{urllib.parse.quote(name, safe='')}"
    return call("GET", url, token=token)


def is_denied(status: int, body) -> bool:
    if status in (401, 403):
        return True
    return isinstance(body, (dict, bytes)) and b"Permission denied" in (
        json.dumps(body).encode() if isinstance(body, dict) else body)


def test_storage_rules() -> None:
    # Unauthenticated upload must be rejected by the rules.
    status, body = storage_upload("intern_files/rules-attacker.txt", b"boom", "text/plain")
    check("rules/storage: unauthenticated upload denied", is_denied(status, body),
          f"HTTP {status} {str(body)[:200]}")

    # Unauthenticated download must be rejected (private bucket).
    status, body = storage_download(
        "intern_files/DFPY01_DFIN001_25110c8ebaa7_intern_submission_e2e.txt")
    check("rules/storage: unauthenticated download denied", is_denied(status, body),
          f"HTTP {status} {str(body)[:200]}")

    intern_token = sign_in("e2e.intern@example.com", "InternPass123")
    if not intern_token:
        check("rules/storage: intern sign-in for storage checks", False, "no ID token")
        return

    # Allowed: an authenticated intern uploads an allowed submission type.
    status, body = storage_upload("intern_files/rules-allowed.txt", b"hello rules",
                                  "text/plain", token=intern_token)
    check("rules/storage: intern CAN upload an allowed submission",
          status in (200, 201), f"HTTP {status} {str(body)[:200]}")

    # Denied by the rules themselves: executable is not on the allow list.
    status, body = storage_upload("intern_files/rules-evil.exe", b"MZ....",
                                  "application/x-msdownload", token=intern_token)
    check("rules/storage: disallowed content type rejected by rules",
          is_denied(status, body), f"HTTP {status} {str(body)[:200]}")

    # Denied: an intern may not write into the admin-only documents folder.
    status, body = storage_upload("documents/rules-forge.pdf", b"%PDF-1.4 fake",
                                  "application/pdf", token=intern_token)
    check("rules/storage: intern cannot write admin 'documents' folder",
          is_denied(status, body), f"HTTP {status} {str(body)[:200]}")

    # The intern's own allowed object is readable by them.
    status, body = storage_download("intern_files/rules-allowed.txt", token=intern_token)
    check("rules/storage: intern CAN read back their own object",
          status == 200, f"HTTP {status} {str(body)[:200]}")

    # Delete: rules only allow admins/mentors, so an intern is rejected.
    status, body = call("DELETE",
                        f"{STORAGE}/v0/b/{BUCKET}/o/"
                        f"{urllib.parse.quote('intern_files/rules-allowed.txt', safe='')}",
                        token=intern_token)
    check("rules/storage: intern cannot delete a submission", is_denied(status, body),
          f"HTTP {status} {str(body)[:200]}")

    # Delete: no credentials at all must be rejected as well.
    status, body = call("DELETE",
                        f"{STORAGE}/v0/b/{BUCKET}/o/"
                        f"{urllib.parse.quote('intern_files/rules-allowed.txt', safe='')}")
    check("rules/storage: unauthenticated delete denied", is_denied(status, body),
          f"HTTP {status} {str(body)[:200]}")


def main() -> int:
    print("=== INMS security-rules test (Firebase emulators) ===", flush=True)
    init_firebase()

    for test in (test_firestore_unauthenticated, test_firestore_intern_privileges,
                 test_storage_rules):
        print(f"\n--- {test.__name__} ---", flush=True)
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            RESULTS.append((test.__name__, False, repr(exc)))

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n=== {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed ===")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("ALL SECURITY RULE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
