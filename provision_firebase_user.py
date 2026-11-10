"""Link an existing Firebase Authentication account to an INMS role."""

from __future__ import annotations

import argparse
import re
import sys
from uuid import uuid4

import firebase_config
from firebase_config import FirebaseConfigError, init_firebase


def provision_user(email: str, username: str, role: str, profile_id: str = "") -> None:
    email = email.strip().casefold()
    username = username.strip()
    role = role.strip().casefold()
    profile_id = profile_id.strip()

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Provide a valid email address.")
    if not username:
        raise ValueError("A username is required.")
    if role not in {"admin", "mentor", "intern"}:
        raise ValueError("Role must be admin, mentor, or intern.")
    if role in {"mentor", "intern"} and not profile_id:
        raise ValueError("Mentor and intern accounts require --profile-id.")
    if role == "admin" and profile_id:
        raise ValueError("Admin accounts must not have a profile ID.")

    settings = firebase_config.settings()
    if settings.use_emulators:
        raise ValueError(
            "Firebase emulator mode is enabled. Set FIREBASE_USE_EMULATORS=0 "
            "and configure production Firebase credentials before provisioning."
        )

    auth_client = firebase_config.auth_client()
    from firebase_admin import auth as fb_auth

    try:
        auth_user = auth_client.get_user_by_email(email)
    except fb_auth.UserNotFoundError as exc:
        raise ValueError(
            "No Firebase Authentication account exists for this email. "
            "Create it in Firebase Authentication first."
        ) from exc

    db = firebase_config.firestore_client()
    users_ref = db.collection("users")
    existing_users = [doc.to_dict() or {} for doc in users_ref.stream()]

    def _claims_for(account_id: str) -> dict:
        return {
            "role": role,
            "profileId": profile_id,
            "accountId": account_id,
        }

    # Idempotent re-run: the same Auth account is already linked with the same
    # role -> make sure the custom claims exist and finish successfully.
    for existing in existing_users:
        if str(existing.get("email", "")).casefold() != email:
            continue
        if (str(existing.get("uid", "")) == auth_user.uid
                and str(existing.get("role", "")).casefold() == role
                and str(existing.get("id", ""))):
            auth_client.set_custom_user_claims(
                auth_user.uid, _claims_for(str(existing["id"]))
            )
            print(
                f"'{email}' is already linked as {role} "
                f"(account id {existing['id']}); role claims refreshed."
            )
            return
        raise ValueError("This email is already linked to a different INMS user.")

    if any(str(user.get("uid", "")) == auth_user.uid for user in existing_users):
        raise ValueError("This Firebase account is already linked to an INMS user.")
    if any(str(user.get("username", "")).casefold() == username.casefold()
           for user in existing_users):
        raise ValueError("This username is already linked to an INMS user.")
    if (auth_user.custom_claims or {}).get("accountId"):
        raise ValueError(
            "This Firebase account already has an INMS account claim. "
            "Resolve the existing account link before provisioning it again."
        )

    profile_field = {"mentor": "mentor_id", "intern": "intern_id"}.get(role)
    if profile_field:
        profile = db.collection("mentors" if role == "mentor" else "interns") \
            .document(profile_id).get()
        if not profile.exists:
            raise ValueError(f"No {role} profile exists with ID '{profile_id}'.")

    account_id = uuid4().hex[:10]
    user_record = {
        "id": account_id,
        "username": username,
        "email": email,
        "role": role,
        "uid": auth_user.uid,
    }
    if profile_field:
        user_record[profile_field] = profile_id

    # Use Firestore's server timestamp sentinel from the Admin SDK.
    from firebase_admin.firestore import SERVER_TIMESTAMP

    user_record["createdAt"] = SERVER_TIMESTAMP
    user_record["updatedAt"] = SERVER_TIMESTAMP

    user_ref = users_ref.document(account_id)
    previous_claims = auth_user.custom_claims or {}
    claims = {
        **previous_claims,
        "role": role,
        "profileId": profile_id,
        "accountId": account_id,
    }

    user_ref.create(user_record)
    try:
        auth_client.set_custom_user_claims(auth_user.uid, claims)
    except Exception as exc:
        try:
            user_ref.delete()
            auth_client.set_custom_user_claims(auth_user.uid, previous_claims or None)
        except Exception as rollback_exc:
            raise RuntimeError(
                "Role assignment failed and automatic rollback was incomplete. "
                "Check the Firebase users document and custom claims before retrying."
            ) from rollback_exc
        raise RuntimeError(
            "Could not assign the INMS role. The Firestore user record was rolled back."
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Link an existing Firebase Auth account to an INMS role."
    )
    parser.add_argument("--email", required=True, help="Email of the existing Auth account")
    parser.add_argument("--username", required=True, help="INMS login username")
    parser.add_argument("--role", required=True, choices=("admin", "mentor", "intern"))
    parser.add_argument(
        "--profile-id",
        default="",
        help="Required for mentor/intern: existing Firestore mentor/intern profile ID",
    )
    args = parser.parse_args()

    try:
        init_firebase()
        provision_user(args.email, args.username, args.role, args.profile_id)
    except (FirebaseConfigError, ValueError, RuntimeError) as exc:
        print(f"Provisioning failed: {exc}", file=sys.stderr)
        return 1

    print(f"Provisioned {args.role} access for the existing Firebase Auth account.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
