"""Diagnose the INMS <-> Firebase connection.

Run this FIRST whenever login does not work:

    python check_firebase_connection.py --email you@example.com --password "your-password"

It checks, in order:
  1. .env values are present (project id, bucket, web API key, key file path)
  2. The service account key exists and loads
  3. Firestore + Auth Admin SDK calls succeed
  4. The e-mail has a Firebase Authentication account
  5. The password is accepted by Firebase Authentication
  6. The e-mail is linked to a `users` document (needed by the login form)
  7. The custom claims (role / profileId / accountId) are set

Exit code 0 = everything needed for login works.
"""

from __future__ import annotations

import argparse
import sys

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f"  ->  {detail}" if detail else ""), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the INMS Firebase connection.")
    parser.add_argument("--email", default="", help="Login e-mail to test")
    parser.add_argument("--password", default="", help="Password to test (optional)")
    args = parser.parse_args()

    import firebase_config
    from firebase_config import FirebaseConfigError

    # --- 1. configuration ---------------------------------------------------
    config_error = None
    try:
        settings = firebase_config._read_settings()
    except FirebaseConfigError as exc:
        config_error = exc
        settings = None
        record(FAIL, "configuration", str(exc).splitlines()[0])

    if settings is not None:
        record(PASS, "project id", settings.project_id)
        record(PASS, "storage bucket", settings.storage_bucket)
        record(PASS, "web API key", "set" if settings.web_api_key else "MISSING")
        record(
            PASS if not settings.use_emulators else WARN,
            "emulator mode",
            "ON - the app talks to localhost, not your real project!"
            if settings.use_emulators
            else "off (real project)",
        )

    # --- 2. credentials / Admin SDK ----------------------------------------
    admin_ok = False
    if settings is not None:
        try:
            firebase_config.init_firebase()
            record(PASS, "service account key", settings.credentials_source)
            admin_ok = True
        except FirebaseConfigError as exc:
            record(FAIL, "service account key", str(exc).splitlines()[0])
    else:
        record(FAIL, "service account key", "skipped - fix the configuration first")

    # --- 3. Firestore + Auth reachability ----------------------------------
    users: list = []
    if admin_ok:
        try:
            db = firebase_config.firestore_client()
            users = list(db.collection("users").stream())
            record(PASS, "Firestore reachable", f"{len(users)} document(s) in users")
        except Exception as exc:  # noqa: BLE001
            record(FAIL, "Firestore reachable", f"{type(exc).__name__}: {exc}")
        try:
            firebase_config.auth_client().list_users(max_results=1)
            record(PASS, "Firebase Authentication reachable")
        except Exception as exc:  # noqa: BLE001
            record(FAIL, "Firebase Authentication reachable", f"{type(exc).__name__}: {exc}")

    # --- 4/5. account + password -------------------------------------------
    email = args.email.strip().casefold()
    if email:
        if admin_ok:
            from firebase_admin import auth as fb_auth

            try:
                auth_user = firebase_config.auth_client().get_user_by_email(email)
                record(PASS, "Auth account exists", auth_user.uid)
            except fb_auth.UserNotFoundError:
                record(FAIL, "Auth account exists",
                       "create it in Firebase Console -> Authentication -> Users")
                auth_user = None
            except Exception as exc:  # noqa: BLE001
                record(FAIL, "Auth account exists", f"{type(exc).__name__}: {exc}")
                auth_user = None
        else:
            auth_user = None

        if args.password:
            import json
            import os
            import urllib.error
            import urllib.request

            api_key = (
                settings.web_api_key if settings is not None
                else os.environ.get("FIREBASE_WEB_API_KEY", "").strip()
            )
            base = (
                settings.auth_base_url if settings is not None
                else "https://identitytoolkit.googleapis.com/v1"
            )
            if not api_key:
                record(FAIL, "password accepted by Firebase Auth", "FIREBASE_WEB_API_KEY is missing")
            else:
                payload = json.dumps(
                    {"email": email, "password": args.password, "returnSecureToken": True}
                ).encode()
                request = urllib.request.Request(
                    f"{base}/accounts:signInWithPassword?key={api_key}",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=20) as response:
                        body = json.loads(response.read().decode())
                    record(PASS, "password accepted by Firebase Auth",
                           f"uid={body.get('localId', '')}")
                except urllib.error.HTTPError as exc:
                    try:
                        code = str(json.loads(exc.read().decode())
                                   .get("error", {}).get("message", "")).split(" ")[0]
                    except Exception:  # noqa: BLE001
                        code = ""
                    record(FAIL, "password accepted by Firebase Auth",
                           f"rejected ({code or 'HTTP ' + str(exc.code)})")
                except Exception as exc:  # noqa: BLE001
                    record(FAIL, "password accepted by Firebase Auth",
                           f"{type(exc).__name__}: {exc}")

        # --- 6/7. Firestore link + claims ----------------------------------
        if not admin_ok:
            record(WARN, "linked to a users document",
                   "skipped - needs the service account key (section 5)")
        else:
            match = next(
                (doc for doc in users
                 if str((doc.to_dict() or {}).get("email", "")).casefold() == email),
                None,
            )
            if match is None:
                record(
                    FAIL,
                    "linked to a users document",
                    "NOT LINKED - this is why the login form says "
                    "'Invalid login details'. Run provision_firebase_user.py",
                )
            else:
                data = match.to_dict() or {}
                record(PASS, "linked to a users document",
                       f"id={data.get('id')} role={data.get('role')}")
                if auth_user is not None:
                    claims = auth_user.custom_claims or {}
                    ok = claims.get("accountId") == data.get("id") and claims.get("role") == data.get("role")
                    record(
                        PASS if ok else WARN,
                        "custom claims",
                        str({k: claims.get(k) for k in ("role", "profileId", "accountId")}),
                    )

    # --- summary ------------------------------------------------------------
    failures = [item for item in results if item[0] == FAIL]
    warnings = [item for item in results if item[0] == WARN]
    print("\n" + "-" * 70)
    if failures:
        print(f"RESULT: {len(failures)} problem(s) must be fixed before login works.")
        for _, name, detail in failures:
            print(f"  * {name}: {detail}")
        print("\nSee FIREBASE_SETUP.md for the exact console steps.")
        return 1
    if warnings:
        print(f"RESULT: connection OK with {len(warnings)} warning(s).")
        return 0
    print("RESULT: Firebase connection OK - the login form should work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
