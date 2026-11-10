"""Backend smoke test — runs INSIDE the Firebase Emulator Suite.

Executes the real Firestore / Authentication / Storage code paths used by the
Flask application (data_store, firebase_auth_service, storage_service) against
local emulators, so the integration can be verified without a real project.

Run from the project folder:

    firebase emulators:exec --project demo-inms --only "auth,firestore,storage" ^
        "python tests/backend_smoke_test.py"

Exit code 0 = all checks passed.
"""

from __future__ import annotations

import io
import os
import sys
import traceback
from pathlib import Path

# Emulator mode must be configured BEFORE the app modules initialise Firebase.
os.environ.setdefault("FIREBASE_USE_EMULATORS", "1")
os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-inms")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import data_store  # noqa: E402
import firebase_auth_service as auth_service  # noqa: E402
import storage_service  # noqa: E402
from firebase_config import init_firebase  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not condition else ""), flush=True)


def test_firestore() -> None:
    collection = "mentors"
    before = data_store.load_collection(collection)
    probe_id = "DFMTST1"
    records = before + [
        {"id": probe_id, "name": "Smoke Mentor", "email": "smoke.mentor@example.com",
         "phone": "123", "departments": ["Python Development"], "department": "Python Development"},
        {"id": "DFMTST2", "name": "Second Mentor", "email": "smoke.mentor2@example.com",
         "phone": "456", "departments": ["Web Development"], "department": "Web Development"},
    ]

    # 1. Full-collection write (the old "rewrite the JSON file" semantics).
    try:
        data_store.save_collection(collection, records)
        check("firestore: save_collection writes records", True)
    except Exception as exc:  # noqa: BLE001
        check("firestore: save_collection writes records", False, repr(exc))
        return

    loaded = data_store.load_collection(collection)
    ids = [row.get("id") for row in loaded]
    check("firestore: load returns every record", probe_id in ids and "DFMTST2" in ids, str(ids))

    # 2. Original creation order is preserved (seq).
    check("firestore: new records keep list order",
          ids[-2:] == [probe_id, "DFMTST2"], str(ids))

    probe = next(row for row in loaded if row.get("id") == probe_id)
    check("firestore: round-trip preserves fields",
          probe.get("email") == "smoke.mentor@example.com"
          and probe.get("departments") == ["Python Development"])
    check("firestore: seq assigned", isinstance(probe.get("seq"), int), str(probe.get("seq")))
    check("firestore: createdAt assigned", probe.get("createdAt") is not None,
          str(probe.get("createdAt")))
    check("firestore: no password field ever stored", "password" not in probe)

    # 3. Unchanged save must not rewrite (updatedAt stays identical).
    stamp_before = probe.get("updatedAt")
    data_store.save_collection(collection, records)
    after_same = next(row for row in data_store.load_collection(collection)
                      if row.get("id") == probe_id)
    check("firestore: unchanged records are skipped",
          after_same.get("updatedAt") == stamp_before,
          f"{stamp_before!r} -> {after_same.get('updatedAt')!r}")

    # 4. Changed record gets a new updatedAt and keeps its seq.
    records_probe = [dict(row) for row in records]
    probe_index = next(i for i, row in enumerate(records_probe) if row.get("id") == probe_id)
    records_probe[probe_index]["phone"] = "999"
    data_store.save_collection(collection, records_probe)
    after_change = next(row for row in data_store.load_collection(collection)
                        if row.get("id") == probe_id)
    check("firestore: update applies changes",
          after_change.get("phone") == "999"
          and after_change.get("seq") == probe.get("seq"))

    # 5. save_json filename mapping works (mentors.json -> "mentors").
    try:
        data_store.save_json(Path("mentors.json"), records_probe)
        check("data_store: legacy filename maps to collection", True)
    except Exception as exc:  # noqa: BLE001
        check("data_store: legacy filename maps to collection", False, repr(exc))

    # 6. Deleting = records absent from the list disappear.
    data_store.save_collection(collection, before)
    cleaned = [row for row in data_store.load_collection(collection)
               if row.get("id") in {probe_id, "DFMTST2"}]
    check("firestore: removed records are deleted", cleaned == [], str(cleaned))


def test_auth() -> None:
    email = "smoke.admin@example.com"
    password = "SmokePass123"
    user_record = {"id": "smoketest", "username": "smokeadmin", "email": email, "role": "admin"}

    # Clean up leftovers from a previous run.
    existing = auth_service.resolve_uid(user_record)
    if existing:
        auth_service.delete_account(existing)

    try:
        uid = auth_service.create_account("smoketest", "smokeadmin", email, password, "admin")
        check("auth: create_account returns a uid", bool(uid), str(uid))
    except Exception as exc:  # noqa: BLE001
        check("auth: create_account returns a uid", False, repr(exc))
        return

    user_record["uid"] = uid
    try:
        check("auth: correct password verifies", auth_service.verify_password(user_record, password) is True)
        check("auth: wrong password is rejected", auth_service.verify_password(user_record, "wrong-password") is False)
    except Exception as exc:  # noqa: BLE001
        check("auth: password verification works", False, repr(exc))

    # Custom claims used by the security rules.
    try:
        from firebase_config import auth_client
        claims = auth_client().get_user(uid).custom_claims or {}
        check("auth: custom role claims attached",
              claims.get("role") == "admin" and claims.get("accountId") == "smoketest",
              str(claims))
    except Exception as exc:  # noqa: BLE001
        check("auth: custom role claims attached", False, repr(exc))

    # Duplicate e-mail must raise AccountAlreadyExistsError (mapped to the
    # existing "already in use" flash message in app.py).
    try:
        auth_service.create_account("smoketest2", "smokeadmin2", email, password, "admin")
        check("auth: duplicate email rejected", False, "no exception raised")
    except auth_service.AccountAlreadyExistsError:
        check("auth: duplicate email rejected", True)
    except Exception as exc:  # noqa: BLE001
        check("auth: duplicate email rejected", False, repr(exc))

    auth_service.delete_account(uid)
    try:
        auth_service.verify_password(user_record, password)
        check("auth: deleted account cannot sign in", False, "verification succeeded")
    except auth_service.AccountNotProvisionedError:
        check("auth: deleted account cannot sign in", True)
    except Exception as exc:  # noqa: BLE001
        check("auth: deleted account cannot sign in", False, repr(exc))


def test_auth_rest_sign_in_directly() -> None:
    """Sign in through the Identity Toolkit REST endpoint (what login uses)."""
    from firebase_config import auth_client, settings

    email = "smoke.rest@example.com"
    password = "RestPass123"
    try:
        auth_client().create_user(email=email, password=password, display_name="Rest Smoke")
    except Exception:  # noqa: BLE001 - likely already exists from a previous run
        pass
    try:
        result = auth_service._rest_sign_in(email, password)
        check("auth: REST sign-in returns tokens",
              bool(result.get("localId")) and bool(result.get("idToken")))
        check("auth: REST uses configured endpoint",
              ":9099" in settings().auth_base_url, settings().auth_base_url)
    except Exception as exc:  # noqa: BLE001
        check("auth: REST sign-in returns tokens", False, repr(exc))

    try:
        auth_service._rest_sign_in(email, "bad-password")
        check("auth: REST rejects bad password", False, "no exception")
    except auth_service._SignInRejected:
        check("auth: REST rejects bad password", True)
    except Exception as exc:  # noqa: BLE001
        check("auth: REST rejects bad password", False, repr(exc))


def test_storage() -> None:
    from werkzeug.datastructures import FileStorage

    payload = b"INMS smoke test payload \x00\x01\x02"
    stream = io.BytesIO(payload)
    upload = FileStorage(stream=stream, filename="smoke.pdf")

    try:
        record = storage_service.save(upload, "intern_files", "DFTEST01_DFIN001")
        check("storage: upload succeeds", bool(record and record.get("stored_name")),
              str(record))
    except Exception as exc:  # noqa: BLE001
        check("storage: upload succeeds", False, repr(exc))
        return

    check("storage: original filename kept", record["filename"] == "smoke.pdf")
    check("storage: object exists", storage_service.exists("intern_files", record["stored_name"]))

    downloaded = storage_service.read("intern_files", record["stored_name"])
    check("storage: download returns exact bytes", downloaded == payload,
          f"{len(downloaded or b'')} bytes")

    # Server-side type policy (mirrors storage.rules).
    try:
        storage_service.save(FileStorage(stream=io.BytesIO(b"x"), filename="evil.exe"),
                             "intern_files", "p")
        check("storage: disallowed type rejected", False, "no exception")
    except storage_service.FileNotAllowedError:
        check("storage: disallowed type rejected", True)
    except Exception as exc:  # noqa: BLE001
        check("storage: disallowed type rejected", False, repr(exc))

    # Server-side size policy: documents are capped at 20 MB.
    try:
        storage_service.save(
            FileStorage(stream=io.BytesIO(b"0" * (21 * 1024 * 1024)), filename="big.pdf"),
            "documents", "p")
        check("storage: oversized document rejected", False, "no exception")
    except storage_service.FileNotAllowedError:
        check("storage: oversized document rejected", True)
    except Exception as exc:  # noqa: BLE001
        check("storage: oversized document rejected", False, repr(exc))

    # Projects only accept .zip (historical message preserved).
    try:
        storage_service.save(FileStorage(stream=io.BytesIO(b"x"), filename="report.pdf"),
                             "projects", "p")
        check("storage: non-zip project rejected", False, "no exception")
    except storage_service.FileNotAllowedError as exc:
        check("storage: non-zip project rejected with legacy message",
              str(exc) == "Only .zip project files are accepted.", str(exc))
    except Exception as exc:  # noqa: BLE001
        check("storage: non-zip project rejected with legacy message", False, repr(exc))

    storage_service.delete("intern_files", record["stored_name"])
    check("storage: delete removes object",
          storage_service.exists("intern_files", record["stored_name"]) is False)
    check("storage: read after delete returns None",
          storage_service.read("intern_files", record["stored_name"]) is None)


def main() -> int:
    print("=== INMS backend smoke test (Firebase emulators) ===", flush=True)
    init_firebase()

    for test in (test_firestore, test_auth, test_auth_rest_sign_in_directly, test_storage):
        print(f"\n--- {test.__name__} ---", flush=True)
        try:
            test()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            RESULTS.append((test.__name__, False, "unhandled exception"))

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n=== {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed ===")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("ALL BACKEND CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
