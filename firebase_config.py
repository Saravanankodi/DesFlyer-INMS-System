"""Centralized Firebase configuration for the INMS Flask backend.

This is the ONLY module in the project that initialises the Firebase Admin SDK.
All other modules (data_store, firebase_auth_service, storage_service) obtain
the Firestore client, Auth client and Storage bucket from here.

Configuration comes from environment variables (optionally loaded from a local
`.env` file, which is git-ignored).  See `.env.example` for the full list.

Firebase-only architecture:
    The application does NOT fall back to any local database.  If Firebase is
    not configured correctly the application refuses to start and prints an
    actionable error message.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

# Development/testing only: local Firebase Emulator Suite endpoints.
DEFAULT_EMULATOR_PROJECT_ID = "demo-inms"
DEFAULT_EMULATOR_HOSTS = {
    "AUTH": "localhost:9099",
    "FIRESTORE": "localhost:8080",
    # STORAGE_EMULATOR_HOST keeps the "http://" scheme even though the name
    # suggests otherwise (google-cloud-storage uses the value as a base URL).
    "STORAGE": "http://localhost:9199",
}

_lock = threading.Lock()
_app = None
_settings = None


class FirebaseConfigError(RuntimeError):
    """Raised when Firebase configuration is missing or invalid."""


def _load_dotenv() -> None:
    """Minimal .env reader (KEY=VALUE lines) so no third-party dependency is needed.

    Real process environment variables always win over values in the file.
    """
    if not ENV_FILE.exists():
        return
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _credentials_path(raw: str) -> Path:
    """Resolve a credentials path relative to the project folder.

    ``.env`` normally contains a relative path such as
    ``secrets/firebase-service-account.json``.  Resolving it against BASE_DIR
    makes the application work no matter which directory it is started from.
    """
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


class FirebaseSettings:
    """Resolved Firebase configuration for the running process."""

    def __init__(
        self,
        *,
        project_id: str,
        storage_bucket: str,
        web_api_key: str,
        use_emulators: bool,
        credentials_source: str,
    ) -> None:
        self.project_id = project_id
        self.storage_bucket = storage_bucket
        self.web_api_key = web_api_key
        self.use_emulators = use_emulators
        self.credentials_source = credentials_source

    @property
    def auth_base_url(self) -> str:
        """Base URL for Identity Toolkit REST calls (password sign-in)."""
        if self.use_emulators:
            host = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", DEFAULT_EMULATOR_HOSTS["AUTH"])
            return f"http://{host}/identitytoolkit.googleapis.com/v1"
        return "https://identitytoolkit.googleapis.com/v1"


def _read_settings() -> FirebaseSettings:
    _load_dotenv()

    use_emulators = _truthy(os.environ.get("FIREBASE_USE_EMULATORS"))
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "").strip()

    if use_emulators and not project_id:
        project_id = DEFAULT_EMULATOR_PROJECT_ID

    if not project_id:
        raise FirebaseConfigError(
            "FIREBASE_PROJECT_ID is not set.\n"
            "  1. Create a Firebase project at https://console.firebase.google.com\n"
            "  2. Project settings -> copy the Project ID\n"
            "  3. Put it in a .env file:  FIREBASE_PROJECT_ID=your-project-id\n"
            "  (See FIREBASE_SETUP.md, sections 4 and 8.)"
        )

    storage_bucket = os.environ.get("FIREBASE_STORAGE_BUCKET", "").strip()
    if not storage_bucket:
        storage_bucket = f"{project_id}.appspot.com"

    # --- Credentials (service account) -------------------------------------
    credentials_source = ""
    if not use_emulators:
        raw_credentials = os.environ.get("FIREBASE_CREDENTIALS", "").strip()
        credentials_file = (
            os.environ.get("FIREBASE_CREDENTIALS_FILE", "").strip()
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        )
        if raw_credentials:
            credentials_source = "FIREBASE_CREDENTIALS (inline service account JSON)"
        elif credentials_file:
            resolved = _credentials_path(credentials_file)
            if not resolved.exists():
                raise FirebaseConfigError(
                    f"The service account key file does not exist:\n  {resolved}\n"
                    "Fix it in 3 steps:\n"
                    "  1. Open https://console.firebase.google.com/project/"
                    f"{project_id}/settings/serviceaccounts/adminsdk\n"
                    "  2. Click 'Generate new private key' and save the JSON file as:\n"
                    f"     {BASE_DIR / 'secrets' / 'firebase-service-account.json'}\n"
                    "  3. Start the app again (FIREBASE_CREDENTIALS_FILE in .env already "
                    "points there).\n"
                    "(See FIREBASE_SETUP.md, section 5.)"
                )
            credentials_source = f"service account file: {resolved}"
        else:
            raise FirebaseConfigError(
                "No Firebase credentials found. The application is Firebase-only and will "
                "not start without them.\n"
                "Provide ONE of the following in your .env file:\n"
                "  FIREBASE_CREDENTIALS_FILE=secrets/firebase-service-account.json\n"
                "  GOOGLE_APPLICATION_CREDENTIALS=C:\\path\\to\\serviceAccountKey.json\n"
                "  FIREBASE_CREDENTIALS={\"type\":\"service_account\", ...}  (full JSON, one line)\n"
                "Download the key from Firebase Console -> Project settings -> "
                "Service accounts -> Generate new private key.\n"
                "(See FIREBASE_SETUP.md, section 5.)"
            )
    else:
        credentials_source = "Firebase Emulators (no credentials required)"

    # --- Web API key (password sign-in via Identity Toolkit REST) ----------
    web_api_key = os.environ.get("FIREBASE_WEB_API_KEY", "").strip()
    if use_emulators and not web_api_key:
        web_api_key = "fake-api-key"  # The Auth emulator accepts any key.
    if not web_api_key:
        raise FirebaseConfigError(
            "FIREBASE_WEB_API_KEY is not set. It is required to verify passwords with "
            "Firebase Authentication.\n"
            "Firebase Console -> Project settings -> General -> Your apps -> "
            "Web app -> copy the Web API Key (or create a Web app first).\n"
            "(See FIREBASE_SETUP.md, sections 6 and 8.)"
        )

    return FirebaseSettings(
        project_id=project_id,
        storage_bucket=storage_bucket,
        web_api_key=web_api_key,
        use_emulators=use_emulators,
        credentials_source=credentials_source,
    )


def _parse_credentials_payload(raw: str) -> dict:
    """Turn a service-account key supplied as an environment variable into a dict.

    Environment variables reach the process in several damaged shapes depending
    on the host: quotes around the value, surrounding whitespace, newlines
    stripped out, a ``data:...;base64,`` prefix, unpadded base64, or URL-safe
    base64.  All of those are accepted here so one imperfect copy/paste does not
    take the whole site down.  The error messages name the value's length, which
    is the fastest way to spot a truncated key.
    """
    import base64
    import binascii

    payload = raw.strip().strip('"').strip("'").strip()
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]

    # 1. Plain JSON, optionally with escaped newlines (private_key "\n").
    for candidate in (payload, payload.replace("\\n", "\n")):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    # 2. base64 or base64url, re-padded to a multiple of four.
    compact = "".join(payload.split()).replace("-", "+").replace("_", "/")
    compact += "=" * (-len(compact) % 4)
    try:
        decoded = base64.b64decode(compact, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            f"value is {len(payload)} characters and is neither JSON nor valid base64 ({exc})"
        ) from exc

    try:
        parsed = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"value is {len(payload)} characters, decodes to {len(decoded)} bytes, "
            "but is not valid JSON - the key is most likely truncated or altered "
            f"({exc})"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError("decoded value is not a JSON object")

    missing = [
        field
        for field in ("type", "project_id", "private_key", "client_email")
        if not parsed.get(field)
    ]
    if missing:
        raise ValueError("decoded JSON is missing field(s): " + ", ".join(missing))
    return parsed


def init_firebase() -> None:
    """Initialise the Firebase Admin SDK exactly once. Raises FirebaseConfigError."""
    global _app, _settings
    with _lock:
        if _app is not None:
            return

        settings = _read_settings()

        if settings.use_emulators:
            # Emulator hosts must be present in the environment before the
            # underlying google-cloud clients are created.
            os.environ.setdefault(
                "FIRESTORE_EMULATOR_HOST",
                os.environ.get("FIRESTORE_EMULATOR_HOST", DEFAULT_EMULATOR_HOSTS["FIRESTORE"]),
            )
            os.environ.setdefault(
                "FIREBASE_AUTH_EMULATOR_HOST",
                os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", DEFAULT_EMULATOR_HOSTS["AUTH"]),
            )
            os.environ.setdefault(
                "STORAGE_EMULATOR_HOST",
                os.environ.get("STORAGE_EMULATOR_HOST", DEFAULT_EMULATOR_HOSTS["STORAGE"]),
            )
            # google-cloud-storage uses STORAGE_EMULATOR_HOST as a base URL, so
            # it must start with a scheme even if the user wrote "host:port".
            storage_host = os.environ["STORAGE_EMULATOR_HOST"]
            if not storage_host.startswith(("http://", "https://")):
                os.environ["STORAGE_EMULATOR_HOST"] = f"http://{storage_host}"

        from firebase_admin import credentials as fb_credentials
        from firebase_admin import initialize_app

        options = {"projectId": settings.project_id, "storageBucket": settings.storage_bucket}

        if settings.use_emulators:
            # Emulator mode never touches a real project and must not require
            # Application Default Credentials (a developer machine may have none).
            # AnonymousCredentials satisfies the SDK's data-plane clients
            # (Firestore, Storage); the Auth emulator ignores credentials.
            from google.auth.credentials import AnonymousCredentials

            _app = initialize_app(AnonymousCredentials(), options=options)
        else:
            raw_credentials = os.environ.get("FIREBASE_CREDENTIALS", "").strip()
            credentials_file = (
                os.environ.get("FIREBASE_CREDENTIALS_FILE", "").strip()
                or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
            )
            try:
                if raw_credentials:
                    # Support raw JSON or base64-encoded JSON (single-line friendly),
                    # tolerating quotes, whitespace, missing padding and base64url.
                    credential = fb_credentials.Certificate(
                        _parse_credentials_payload(raw_credentials)
                    )
                else:
                    credential = fb_credentials.Certificate(str(_credentials_path(credentials_file)))
                _app = initialize_app(credential, options=options)
            except Exception as exc:  # noqa: BLE001 - surfaced as a config error
                raise FirebaseConfigError(
                    "Firebase credentials could not be loaded "
                    f"({settings.credentials_source}).\nDetails: {exc}\n"
                    "Re-download the key from Firebase Console -> Project settings -> "
                    "Service accounts -> Generate new private key."
                ) from exc

        _settings = settings
        mode = "emulators" if settings.use_emulators else "production"
        print(
            f"[INMS] Firebase initialised (project={settings.project_id}, "
            f"bucket={settings.storage_bucket}, mode={mode})",
            flush=True,
        )


def settings() -> FirebaseSettings:
    if _settings is None:
        raise FirebaseConfigError("Firebase has not been initialised. Call init_firebase() first.")
    return _settings


def firestore_client():
    from firebase_admin import firestore

    return firestore.client()


def auth_client():
    from firebase_admin import auth

    return auth


def bucket():
    from firebase_admin import storage

    return storage.bucket(name=settings().storage_bucket)
