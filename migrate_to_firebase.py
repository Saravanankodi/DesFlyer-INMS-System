"""One-time migration from the legacy local storage to Firebase.

  legacy local JSON files  ->  Cloud Firestore collections
  users.json password hashes->  Firebase Authentication accounts (temp password)
  uploads/*                 ->  Firebase Storage objects

What it does, step by step:
  1. For every account in users.json:
       - reuse the existing Firebase Authentication account if the email is
         already registered, otherwise create one with --temp-password;
       - attach the custom role claims used by the security rules
         (role / profileId / accountId);
       - record the resulting UID in the `users` Firestore document.
       - password hashes are NEVER written to Firestore.
  2. Writes interns / mentors / tasks / notifications to Firestore using the
     exact document ids and original list order of the JSON files.
  3. Uploads every file under uploads/documents, uploads/projects and
     uploads/intern_files to Firebase Storage using the SAME stored_name, so
     all existing file references keep resolving.

The script is idempotent - running it again only fills in what is missing.

Usage (from the project folder, with .env configured):
    python migrate_to_firebase.py --temp-password "SomeTempPass123"
    python migrate_to_firebase.py --dry-run
    python migrate_to_firebase.py --skip-auth --skip-storage

Nothing in this script modifies the JSON files; they remain as a backup.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from pathlib import Path

import data_store
import firebase_auth_service
from firebase_config import FirebaseConfigError, bucket, init_firebase

BASE_DIR = Path(__file__).resolve().parent
UPLOADS_BASE = BASE_DIR / "uploads"
UPLOAD_DIRS = {
    "documents": UPLOADS_BASE / "documents",
    "projects": UPLOADS_BASE / "projects",
    "intern_files": UPLOADS_BASE / "intern_files",
}


def read_json_file(name: str) -> list:
    path = BASE_DIR / name
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  !! could not read {name}: {exc}")
        return []


def provision_users(dry_run: bool, temp_password: str | None) -> tuple[list, dict]:
    """Create/link Firebase Authentication accounts for every user record."""
    stats = {"linked": 0, "created": 0, "skipped": 0}
    users = read_json_file("users.json")
    if not users:
        print("  users.json is empty - nothing to provision.")
        return users, stats

    if dry_run:
        print(f"  [dry-run] would provision {len(users)} account(s).")
        return users, stats

    from firebase_admin import auth as fb_auth

    for user in users:
        email = str(user.get("email") or "").strip()
        username = str(user.get("username") or email)
        role = str(user.get("role") or "")
        if not email:
            print(f"  !! user '{username}' has no email - cannot create an Authentication account.")
            stats["skipped"] += 1
            continue

        uid = None
        try:
            uid = fb_auth.get_user_by_email(email).uid
            stats["linked"] += 1
            print(f"  = Authentication account already exists: {email}")
        except fb_auth.UserNotFoundError:
            if not temp_password:
                print(f"  !! no Authentication account for {email} and no --temp-password given - SKIPPED.")
                stats["skipped"] += 1
                continue
            try:
                created = fb_auth.create_user(
                    email=email, password=temp_password, display_name=username)
            except fb_auth.EmailAlreadyExistsError:
                uid = fb_auth.get_user_by_email(email).uid
            else:
                uid = created.uid
                stats["created"] += 1
                print(f"  + created Authentication account: {email} (temp password supplied)")

        user["uid"] = uid
        profile_id = user.get("mentor_id") or user.get("intern_id") or ""
        fb_auth.set_custom_user_claims(uid, {
            "role": role,
            "profileId": profile_id,
            "accountId": user.get("id", ""),
        })

    return users, stats


def write_collections(users: list, dry_run: bool) -> None:
    """Write every collection to Firestore (users first, then profile data)."""
    others = (
        ("interns", "interns.json"),
        ("mentors", "mentors.json"),
        ("tasks", "tasks.json"),
        ("notifications", "notifications.json"),
    )
    if dry_run:
        print(f"  [dry-run] would write {len(users)} record(s) to 'users'.")
        for collection, filename in others:
            print(f"  [dry-run] would write {len(read_json_file(filename))} "
                  f"record(s) to '{collection}'.")
        return
    data_store.save_collection("users", users)
    print(f"  + {len(users)} record(s) -> Firestore collection 'users'.")
    for collection, filename in others:
        records = read_json_file(filename)
        data_store.save_collection(collection, records)
        print(f"  + {len(records)} record(s) -> Firestore collection '{collection}'.")


def upload_files(dry_run: bool) -> None:
    storage_bucket = bucket()
    for kind, directory in UPLOAD_DIRS.items():
        if not directory.exists():
            print(f"  - {directory.name}/ not found, skipped.")
            continue
        files = [p for p in sorted(directory.iterdir()) if p.is_file()]
        uploaded = existing = 0
        for path in files:
            if dry_run:
                continue
            blob = storage_bucket.blob(f"{kind}/{path.name}")
            try:
                if blob.exists():
                    existing += 1
                    continue
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                with path.open("rb") as handle:
                    blob.upload_from_file(handle, content_type=content_type)
                uploaded += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  !! upload failed for {path.name}: {exc}")
        if dry_run:
            print(f"  [dry-run] would upload {len(files)} file(s) to '{kind}/'.")
        else:
            print(f"  + {uploaded} file(s) uploaded to '{kind}/' ({existing} already present).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate local INMS data to Firebase.")
    parser.add_argument("--temp-password",
                        help="Password assigned to NEW Firebase Authentication accounts "
                             "(existing accounts keep their password).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be migrated without writing anything.")
    parser.add_argument("--skip-auth", action="store_true",
                        help="Do not create Authentication accounts (Firestore + Storage only).")
    parser.add_argument("--skip-storage", action="store_true",
                        help="Do not upload files (Firestore + Authentication only).")
    args = parser.parse_args()

    try:
        init_firebase()
    except FirebaseConfigError as exc:
        print(f"[INMS] Firebase configuration error:\n{exc}", file=sys.stderr)
        return 1

    import os
    temp_password = args.temp_password or os.environ.get("MIGRATION_TEMP_PASSWORD")
    if temp_password is not None and len(temp_password) < 6:
        print("The temporary password must be at least 6 characters.", file=sys.stderr)
        return 1

    print("\n=== 1/3 Firebase Authentication accounts ===")
    if args.skip_auth:
        print("  skipped (--skip-auth).")
        auth_stats = {"linked": 0, "created": 0, "skipped": 0}
        users = read_json_file("users.json")
    else:
        users, auth_stats = provision_users(args.dry_run, temp_password)

    print("\n=== 2/3 Firestore collections ===")
    write_collections(users, args.dry_run)

    print("\n=== 3/3 Firebase Storage ===")
    if args.skip_storage:
        print("  skipped (--skip-storage).")
    else:
        upload_files(args.dry_run)

    print("\n=== Migration summary ===")
    print(f"  Authentication accounts: {auth_stats['created']} created, "
          f"{auth_stats['linked']} already existed, {auth_stats['skipped']} skipped.")
    if args.dry_run:
        print("  This was a DRY RUN - nothing was written.")
        return 0
    if auth_stats["skipped"]:
        print("  !! Accounts marked 'skipped' cannot log in until they are created.")
        print("     Re-run with --temp-password, or create the user again in the")
        print("     admin 'Users' page.")
    print("  Next steps:")
    print("    1. Sign in at /login with each account (temporary password for new ones).")
    print("    2. Let users change their temporary password via Users -> Edit (admin).")
    print("    3. Deploy the security rules: firebase deploy --only firestore:rules,storage")
    print("    4. Keep the JSON files as a backup until you have verified the data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
