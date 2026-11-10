"""Firebase Authentication operations for the INMS Flask backend.

Credentials (email + password) live ONLY in Firebase Authentication; the old
PBKDF2 password hashes stored in users.json are no longer written anywhere.

Flask keeps issuing its own signed session cookie (identical user experience,
identical protected pages); what changed is that the password is now verified
by Firebase before the session is created.

Sign-in uses the Identity Toolkit REST API because that is the only supported
way to verify an email/password pair from a trusted server.  All other
operations use the Firebase Admin SDK.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import firebase_config

SIGN_IN_TIMEOUT_SECONDS = 15

# Identity Toolkit responses that simply mean "credentials did not match".
_REJECTED_CODES = {
    "INVALID_PASSWORD",
    "EMAIL_NOT_FOUND",
    "INVALID_LOGIN_CREDENTIALS",
    "MISSING_PASSWORD",
    "USER_NOT_FOUND",
    "INVALID_EMAIL",
}


class AuthError(RuntimeError):
    """Base class for Firebase Authentication failures."""


class AuthUnavailableError(AuthError):
    """Firebase Authentication could not be reached / is misconfigured."""


class AccountAlreadyExistsError(AuthError):
    """An Authentication account with this email already exists."""


class AccountNotProvisionedError(AuthError):
    """The Firestore user record has no matching Firebase Authentication account."""

    def __init__(self, email: str) -> None:
        super().__init__(email)
        self.email = email


class _SignInRejected(AuthError):
    """The Identity Toolkit rejected the submitted credentials."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _auth():
    return firebase_config.auth_client()


def _log(message: str) -> None:
    print(f"[INMS][auth] {message}", flush=True)


# ---------------------------------------------------------------------------
# Identity Toolkit REST: verify an email/password pair
# ---------------------------------------------------------------------------

def _rest_sign_in(email: str, password: str) -> dict:
    config = firebase_config.settings()
    url = f"{config.auth_base_url}/accounts:signInWithPassword?key={config.web_api_key}"
    payload = json.dumps(
        {"email": email, "password": password, "returnSecureToken": True}
    ).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=SIGN_IN_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            code = str(body.get("error", {}).get("message", "")).split(" ")[0]
        except (ValueError, AttributeError):
            code = ""
        if code in _REJECTED_CODES:
            raise _SignInRejected(code) from None
        _log(f"sign-in rejected for {email}: HTTP {exc.code} {code or '(unparsed)'}")
        raise AuthUnavailableError(
            "Firebase Authentication rejected the request unexpectedly."
        ) from exc
    except urllib.error.URLError as exc:
        _log(f"sign-in network failure for {email}: {exc.reason}")
        raise AuthUnavailableError("Could not reach Firebase Authentication.") from exc
    except (TimeoutError, OSError) as exc:
        _log(f"sign-in timeout for {email}: {exc}")
        raise AuthUnavailableError("Firebase Authentication timed out.") from exc
    except ValueError as exc:
        _log(f"sign-in returned an unreadable response for {email}")
        raise AuthUnavailableError("Firebase Authentication returned an invalid response.") from exc


def _account_exists(user: dict) -> bool:
    """True when a Firebase Authentication account exists for this user record."""
    auth_client = _auth()
    uid = user.get("uid")
    try:
        if uid:
            auth_client.get_user(uid)
        elif user.get("email"):
            auth_client.get_user_by_email(user["email"])
        else:
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - map Firebase errors to auth states
        from firebase_admin import auth as fb_auth
        from firebase_admin.exceptions import FirebaseError

        # UserNotFoundError: no such account.  ValueError: malformed uid/e-mail
        # (firebase_admin has no dedicated exception for that).
        if isinstance(exc, (fb_auth.UserNotFoundError, ValueError)):
            return False
        if isinstance(exc, FirebaseError):
            _log(f"could not look up authentication account for {user.get('email')}: {exc}")
            raise AuthUnavailableError("Could not query Firebase Authentication.") from exc
        raise


# ---------------------------------------------------------------------------
# Public API used by app.py
# ---------------------------------------------------------------------------

def verify_password(user: dict, password: str) -> bool:
    """Verify ``password`` against Firebase Authentication for this user record.

    Returns True/False for a normal credential check.  Raises
    AccountNotProvisionedError when the user record has no Authentication
    account yet (migration still pending) and AuthUnavailableError when the
    service itself cannot be used (network / configuration problems).
    """
    email = str(user.get("email") or "").strip()
    if not email:
        raise AccountNotProvisionedError("")

    try:
        _rest_sign_in(email, password)
        return True
    except _SignInRejected:
        # Distinguish "wrong password" from "account never migrated".
        if not _account_exists(user):
            raise AccountNotProvisionedError(email) from None
        return False


def resolve_uid(user: dict) -> str | None:
    """Return the Firebase UID for a user record, looking it up by email if needed."""
    uid = user.get("uid")
    if uid:
        return str(uid)
    email = str(user.get("email") or "").strip()
    if not email:
        return None
    try:
        return _auth().get_user_by_email(email).uid
    except Exception as exc:  # noqa: BLE001
        from firebase_admin import auth as fb_auth

        if isinstance(exc, fb_auth.UserNotFoundError):
            return None
        raise


def create_account(user_id: str, username: str, email: str, password: str,
                   role: str, profile_id: str = "") -> str:
    """Create a Firebase Authentication account and attach role claims. Returns the UID."""
    auth_client = _auth()
    try:
        created = auth_client.create_user(
            email=email, password=password, display_name=username or email
        )
    except Exception as exc:  # noqa: BLE001
        from firebase_admin import auth as fb_auth
        from firebase_admin.exceptions import FirebaseError

        if isinstance(exc, fb_auth.EmailAlreadyExistsError):
            raise AccountAlreadyExistsError(email) from exc
        if isinstance(exc, FirebaseError):
            _log(f"create_user failed for {email}: {exc}")
            raise AuthUnavailableError("Firebase Authentication could not create the account.") from exc
        raise
    try:
        auth_client.set_custom_user_claims(
            created.uid,
            {"role": role or "", "profileId": profile_id or "", "accountId": user_id or ""},
        )
    except Exception as exc:  # noqa: BLE001
        # Roll back so a half-created account cannot linger.
        try:
            auth_client.delete_user(created.uid)
        except Exception:  # noqa: BLE001
            pass
        _log(f"set_custom_user_claims failed for {email}: {exc}")
        raise AuthUnavailableError("Could not assign role claims to the new account.") from exc
    return created.uid


def update_account(uid: str, *, username: str = None, email: str = None,
                   password: str = None, role: str = None,
                   profile_id: str = None, account_id: str = None) -> None:
    """Update an existing Firebase Authentication account (fields left as None stay unchanged)."""
    auth_client = _auth()
    fields = {}
    if username:
        fields["display_name"] = username
    if email:
        fields["email"] = email
    if password:
        fields["password"] = password
    try:
        if fields:
            auth_client.update_user(uid, **fields)
        if role is not None:
            auth_client.set_custom_user_claims(
                uid,
                {
                    "role": role or "",
                    "profileId": profile_id or "",
                    "accountId": account_id or "",
                },
            )
    except Exception as exc:  # noqa: BLE001
        from firebase_admin import auth as fb_auth
        from firebase_admin.exceptions import FirebaseError

        if isinstance(exc, fb_auth.EmailAlreadyExistsError):
            raise AccountAlreadyExistsError(email or "") from exc
        if isinstance(exc, fb_auth.UserNotFoundError):
            raise AccountNotProvisionedError(email or "") from exc
        if isinstance(exc, FirebaseError):
            _log(f"update_user failed for uid={uid}: {exc}")
            raise AuthUnavailableError("Firebase Authentication could not update the account.") from exc
        raise


def delete_account(uid: str) -> None:
    """Delete a Firebase Authentication account. Missing accounts are ignored."""
    if not uid:
        return
    auth_client = _auth()
    try:
        auth_client.delete_user(uid)
    except Exception as exc:  # noqa: BLE001
        from firebase_admin import auth as fb_auth
        from firebase_admin.exceptions import FirebaseError

        if isinstance(exc, fb_auth.UserNotFoundError):
            return
        if isinstance(exc, FirebaseError):
            _log(f"delete_user failed for uid={uid}: {exc}")
            raise AuthUnavailableError("Firebase Authentication could not delete the account.") from exc
        raise


def send_password_reset(email: str) -> str:
    """Generate a password-reset link for an existing account.

    There is no "forgot password" button in the existing UI, so this helper is
    intentionally kept as a server-side/operational function (used from a
    Python shell or a future feature).  See FIREBASE_SETUP.md section 9.
    """
    try:
        return _auth().generate_password_reset_link(email)
    except Exception as exc:  # noqa: BLE001
        from firebase_admin import auth as fb_auth
        from firebase_admin.exceptions import FirebaseError

        if isinstance(exc, fb_auth.UserNotFoundError):
            raise AccountNotProvisionedError(email) from exc
        if isinstance(exc, FirebaseError):
            _log(f"generate_password_reset_link failed for {email}: {exc}")
            raise AuthUnavailableError(
                "Could not create a password reset link. Enable the Email/Password "
                "sign-in provider and the password-reset email template first."
            ) from exc
        raise
