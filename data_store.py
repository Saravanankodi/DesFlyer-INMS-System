"""Firestore persistence layer for INMS.

Replaces the legacy local JSON files (interns.json, tasks.json, mentors.json,
users.json, notifications.json) with the equivalent Cloud Firestore collections.

The public API intentionally mirrors the old ``load_json`` / ``save_json``
functions so every existing route in app.py keeps working unchanged:

    load_json(INTERNS_FILE)       -> list[dict]  (from the "interns" collection)
    save_json(INTERNS_FILE, rows) -> full-collection write to "interns"

Guarantees provided here:
  * Collection names are stable, plural, lower-case nouns.
  * Document IDs are the domain IDs (DFIN001, DFM001, DFPY01, user id, ...),
    so records stay easy to find in the Firebase console.
  * Records are returned in their original creation order (``seq``).
  * ``createdAt`` / ``updatedAt`` are Firestore server timestamps.
  * Password hashes are NEVER stored - credentials live only in Firebase
    Authentication (the ``password`` key is stripped defensively on write).
  * ``save`` mirrors the exact semantics of writing the whole JSON file:
    upsert every record in the list and delete documents that are no longer
    present.  Documents whose data did not change are skipped, which keeps
    ``updatedAt`` truthful and saves write quota.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

import firebase_config

# Map every legacy JSON filename to its Firestore collection.
COLLECTION_BY_FILE = {
    "interns.json": "interns",
    "tasks.json": "tasks",
    "mentors.json": "mentors",
    "users.json": "users",
    "notifications.json": "notifications",
}

# Firestore allows 500 operations per BatchedWrite; stay safely below it.
BATCH_LIMIT = 400

# Keys maintained by this layer; excluded when comparing record payloads.
_META_KEYS = ("createdAt", "updatedAt", "seq")


class DataStoreError(RuntimeError):
    """Raised for unexpected persistence problems (unknown file, duplicate ids)."""


def collection_name(path: Any) -> str:
    """Return the Firestore collection for a legacy JSON path (Path or str)."""
    name = Path(str(path)).name
    try:
        return COLLECTION_BY_FILE[name]
    except KeyError:
        raise DataStoreError(
            f"No Firestore collection is registered for '{name}'. "
            "Every collection must be declared in data_store.COLLECTION_BY_FILE."
        ) from None


def _db():
    return firebase_config.firestore_client()


def _timestamp():
    from firebase_admin.firestore import SERVER_TIMESTAMP

    return SERVER_TIMESTAMP


def _record_id(record: Mapping[str, Any]) -> str:
    value = record.get("id")
    if value is None or str(value).strip() == "":
        return uuid.uuid4().hex
    return str(value)


def _normalise(record: Mapping[str, Any], doc_id: str) -> dict:
    """Copy of the record without credentials, with a guaranteed string id."""
    data = {key: value for key, value in record.items() if key != "password"}
    data["id"] = doc_id
    return data


def load_collection(name: str) -> list[dict]:
    """Read every document of a collection, ordered by creation (seq)."""
    records: list[dict] = []
    for doc in _db().collection(name).get():
        data = doc.to_dict() or {}
        data.setdefault("id", doc.id)  # domain id; auto-id only as a fallback
        records.append(data)
    records.sort(key=lambda item: (item.get("seq") if isinstance(item.get("seq"), int) else 0,
                                   str(item.get("id", ""))))
    return records


def save_collection(name: str, value: Iterable[Mapping[str, Any]]) -> None:
    """Write the full collection contents (the old "rewrite the file" behaviour).

    - every record in ``value`` is upserted under its ``id``,
    - documents that disappeared from ``value`` are deleted,
    - unchanged documents are left untouched,
    - ``createdAt`` is set on first write, ``updatedAt`` on every real change,
    - ``seq`` preserves the historical list/creation order.
    """
    db = _db()

    incoming: dict[str, dict] = {}
    for record in value:
        if not isinstance(record, Mapping):
            raise DataStoreError(f"Invalid record for collection '{name}': {type(record)!r}")
        doc_id = _record_id(record)
        if doc_id in incoming:
            raise DataStoreError(
                f"Duplicate id '{doc_id}' while saving collection '{name}'."
            )
        incoming[doc_id] = _normalise(record, doc_id)

    # One read gives us: document ids, existing order, audit timestamps and
    # enough information to skip writes for records that did not change.
    existing: dict[str, dict] = {}
    for doc in db.collection(name).get():
        existing[doc.id] = doc.to_dict() or {}

    next_seq = max(
        (row.get("seq") for row in existing.values() if isinstance(row.get("seq"), int)),
        default=0,
    )

    operations: list[tuple[Any, dict]] = []  # (DocumentReference, data)

    for doc_id, data in incoming.items():
        previous = existing.get(doc_id)
        if previous is None:
            next_seq += 1
            data["seq"] = next_seq
            data["createdAt"] = _timestamp()
            data["updatedAt"] = _timestamp()
            operations.append((db.collection(name).document(doc_id), data))
            continue

        # Preserve the original creation order / audit fields.
        previous_seq = previous.get("seq")
        if isinstance(previous_seq, int):
            data["seq"] = previous_seq
            if previous_seq > next_seq:
                next_seq = previous_seq
        else:
            next_seq += 1
            data["seq"] = next_seq
        data["createdAt"] = previous.get("createdAt") or _timestamp()

        changed = any(previous.get(key) != data.get(key) for key in data)
        changed = changed or any(key not in data and key in previous
                                 for key in previous if key not in _META_KEYS)
        if not changed:
            continue
        data["updatedAt"] = _timestamp()
        operations.append((db.collection(name).document(doc_id), data))

    for doc_id in existing:
        if doc_id not in incoming:
            operations.append((db.collection(name).document(doc_id), None))  # None => delete

    for start in range(0, len(operations), BATCH_LIMIT):
        chunk = operations[start:start + BATCH_LIMIT]
        batch = db.batch()
        for reference, data in chunk:
            if data is None:
                batch.delete(reference)
            else:
                batch.set(reference, data)
        if chunk:
            batch.commit()


# ---------------------------------------------------------------------------
# Legacy call-signatures used by app.py
# ---------------------------------------------------------------------------

def load_json(path: Any) -> list:
    """Firestore-backed replacement for the old JSON file reader."""
    return load_collection(collection_name(path))


def save_json(path: Any, value: Iterable[Mapping[str, Any]]) -> None:
    """Firestore-backed replacement for the old JSON file writer."""
    save_collection(collection_name(path), value)
