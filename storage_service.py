"""Firebase Storage operations for the INMS Flask backend.

Replaces the local ``uploads/`` folders:

    uploads/documents/   ->  gs://<bucket>/documents/
    uploads/projects/    ->  gs://<bucket>/projects/
    uploads/intern_files/->  gs://<bucket>/intern_files/

The record shape stored in Firestore ({"filename": ..., "stored_name": ...})
is unchanged, so every existing route keeps working; only the backing store
moved to Firebase Storage.

Every upload is validated server-side (file type + maximum size) using the
exact same policy that is encoded in storage.rules - frontend validation is
never trusted on its own.
"""

from __future__ import annotations

import mimetypes
import uuid
from typing import Any

from werkzeug.utils import secure_filename

import firebase_config

MB = 1024 * 1024

# kind -> (max bytes, allowed extensions, human label)
_POLICIES: dict[str, tuple[int, set[str], str]] = {
    "documents": (
        20 * MB,
        {"pdf", "png", "jpg", "jpeg", "webp", "gif", "bmp", "doc", "docx", "odt", "txt"},
        "identity documents",
    ),
    "projects": (
        500 * MB,
        {"zip"},
        "final project",
    ),
    "intern_files": (
        500 * MB,
        {
            # archives
            "zip", "rar", "7z", "tar", "gz",
            # office / text
            "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md",
            "csv", "tsv", "json", "xml", "log",
            # images
            "png", "jpg", "jpeg", "gif", "webp", "svg", "bmp",
            # code / data
            "py", "ipynb", "js", "ts", "html", "css", "java", "c", "cpp", "h",
            "sql", "sh", "r", "dart", "kt", "swift", "go", "rb", "php", "yml",
            "yaml", "toml", "ini",
            # design / media
            "psd", "ai", "eps", "aep", "mp4", "mov", "avi", "mkv", "mp3", "wav",
        },
        "task submission",
    ),
}


class StorageError(RuntimeError):
    """Base class for Storage failures."""


class FileNotAllowedError(StorageError):
    """The uploaded file failed server-side type/size validation."""


class StorageUnavailableError(StorageError):
    """Firebase Storage could not complete the operation."""


def _bucket():
    return firebase_config.bucket()


def _blob_path(kind: str, stored_name: str) -> str:
    return f"{kind}/{stored_name}"


def _log(message: str) -> None:
    print(f"[INMS][storage] {message}", flush=True)


def _allowed_message(kind: str, extension: str) -> str:
    max_bytes, allowed, label = _POLICIES[kind]
    max_mb = max_bytes // MB
    if kind == "projects":
        # Keep the exact wording the application has always shown for this upload.
        return "Only .zip project files are accepted."
    ext = f".{extension}" if extension else "that"
    return (f"Files of type '{ext}' are not allowed for {label}. "
            f"Allowed types: {', '.join('.' + e for e in sorted(allowed))} (max {max_mb} MB).")


def save(file_storage: Any, kind: str, prefix: str) -> dict | None:
    """Validate and upload a werkzeug FileStorage to Firebase Storage.

    Returns ``{"filename": <original>, "stored_name": <storage object name>}``
    or ``None`` when the file has no usable name (same contract as before).

    Raises FileNotAllowedError when the type/size policy is violated and
    StorageUnavailableError when Storage cannot be reached.
    """
    if kind not in _POLICIES:
        raise StorageError(f"Unknown upload kind '{kind}'.")
    max_bytes, allowed, _label = _POLICIES[kind]

    filename = secure_filename(getattr(file_storage, "filename", "") or "")
    if not filename:
        return None

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in allowed:
        raise FileNotAllowedError(_allowed_message(kind, extension))

    # Size validation (stream-based, constant memory).
    try:
        stream = file_storage.stream
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(0)
    except (AttributeError, OSError, ValueError):
        size = 0  # Unseekable stream: rely on Flask's MAX_CONTENT_LENGTH.
    if size and size > max_bytes:
        max_mb = max_bytes // MB
        raise FileNotAllowedError(
            f"The file is too large ({round(size / MB, 1)} MB). "
            f"Maximum allowed size for this upload is {max_mb} MB."
        )

    stored_name = f"{prefix}_{uuid.uuid4().hex[:12]}_{filename}"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    try:
        blob = _bucket().blob(_blob_path(kind, stored_name))
        stream.seek(0)
        blob.upload_from_file(stream, content_type=content_type)
    except Exception as exc:  # noqa: BLE001 - surfaced as a storage failure
        _log(f"upload failed ({kind}/{stored_name}): {exc}")
        raise StorageUnavailableError(
            "Firebase Storage could not store the file. Please try again."
        ) from exc

    return {"filename": filename, "stored_name": stored_name}


def read(kind: str, stored_name: str | None) -> bytes | None:
    """Return the file bytes, or None when it does not exist / cannot be read."""
    if not stored_name or kind not in _POLICIES:
        return None
    try:
        return _bucket().blob(_blob_path(kind, stored_name)).download_as_bytes()
    except Exception as exc:  # noqa: BLE001 - NotFound and outages both mean "unavailable"
        from google.api_core import exceptions as gexceptions

        if isinstance(exc, gexceptions.NotFound):
            return None
        _log(f"download failed ({kind}/{stored_name}): {exc}")
        return None


def exists(kind: str, stored_name: str | None) -> bool:
    """True when the stored object is present in Firebase Storage."""
    if not stored_name or kind not in _POLICIES:
        return False
    try:
        return bool(_bucket().blob(_blob_path(kind, stored_name)).exists())
    except Exception as exc:  # noqa: BLE001
        _log(f"exists check failed ({kind}/{stored_name}): {exc}")
        return False


def delete(kind: str, stored_name: str | None) -> None:
    """Delete a stored object. Missing objects are ignored; other errors raise."""
    if not stored_name or kind not in _POLICIES:
        return
    try:
        _bucket().blob(_blob_path(kind, stored_name)).delete()
    except Exception as exc:  # noqa: BLE001
        from google.api_core import exceptions as gexceptions

        if isinstance(exc, gexceptions.NotFound):
            return
        _log(f"delete failed ({kind}/{stored_name}): {exc}")
        raise StorageUnavailableError(
            "Firebase Storage could not delete the file."
        ) from exc
