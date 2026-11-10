# INMS — Firebase Database Schema

This document describes the exact data structure the application stores in
**Cloud Firestore**, **Firebase Authentication** and **Firebase Storage** after
the backend integration. It replaces the former local JSON files
(`interns.json`, `mentors.json`, `tasks.json`, `users.json`, `notifications.json`)
and the local `uploads/` folders.

All reads and writes go through two centralised modules:

| Concern              | Module                    |
| -------------------- | ------------------------- |
| Firestore read/write | `data_store.py`           |
| Authentication       | `firebase_auth_service.py`|
| File storage         | `storage_service.py`      |
| Initialisation       | `firebase_config.py`      |

No template or UI code touches Firebase — routes in `app.py` call the modules
above.

---

## 1. Collections overview

| Collection       | Document ID                | Source (legacy)     | Written by                     |
| ---------------- | -------------------------- | ------------------- | ------------------------------ |
| `users`          | account id (`admin01`, random 10-hex) | `users.json` | admin UI (`/admin/users`)   |
| `interns`        | profile id (`DFIN001`…)    | `interns.json`      | admin UI (`/interns/add`)      |
| `mentors`        | profile id (`DFM001`…)     | `mentors.json`      | admin UI (`/mentors/add`)      |
| `tasks`          | task id (`DFPY01`, `DFPY01-01`) | `tasks.json`    | admin/mentor UI (`/tasks/add`) |
| `notifications`  | random 32-hex UUID         | `notifications.json`| server (task events)           |

Document IDs are the **domain IDs**, so every record is easy to find in the
Firebase console (`tasks/DFPY01`, `interns/DFIN001`, …).

### Metadata fields on every document

| Field       | Type      | Meaning                                                        |
| ----------- | --------- | -------------------------------------------------------------- |
| `id`        | `string`  | Domain ID (same value as the document ID; kept explicit so record copies stay self-contained). |
| `seq`       | `number`  | Creation order. Preserves the original list order of the JSON files so tables render in the same sequence as before. |
| `createdAt` | `timestamp` (server) | Firestore server time of the first write. |
| `updatedAt` | `timestamp` (server) | Firestore server time of the last **content** change (unchanged records are not rewritten). |

> **Security note:** no document ever contains a password field. Credentials
> exist only in Firebase Authentication; `data_store.py` strips a `password`
> key defensively on every write, and `firestore.rules` rejects any document
> that contains one.

---

## 2. `users`

Login accounts. One document per login; the `uid` links it to Firebase
Authentication.

| Field       | Type     | Required | Notes                                                     |
| ----------- | -------- | -------- | --------------------------------------------------------- |
| `id`        | string   | ✔        | Account ID (document ID), e.g. `admin01`.                 |
| `username`  | string   | ✔        | Displayed name; also usable to sign in.                   |
| `email`     | string   | ✔        | Login identifier sent to Firebase Authentication.         |
| `role`      | string   | ✔        | `admin` \| `mentor` \| `intern`.                          |
| `uid`       | string   | –        | Firebase Authentication UID (set by migration/create).    |
| `mentor_id` | string   | conditional | Present only when `role == "mentor"` → `mentors.id`.   |
| `intern_id` | string   | conditional | Present only when `role == "intern"` → `interns.id`.   |

**Relationships:** `mentor_id` → `mentors.id`, `intern_id` → `interns.id`.
**Authentication:** passwords are **not** stored here. Custom claims are set on
the Firebase Authentication user: `role`, `profileId` (mentor/intern id),
`accountId` (this document's `id` — used by notification rules).

## 3. `interns`

| Field              | Type    | Required | Notes                                        |
| ------------------ | ------- | -------- | -------------------------------------------- |
| `id`               | string  | ✔        | `DFIN001`… (document ID).                    |
| `name`             | string  | ✔        |                                              |
| `email`            | string  | ✔        |                                              |
| `phone`            | string  | ✔        |                                              |
| `department`       | string  | ✔        | One of the canonical department names.       |
| `joining_date`     | string  | ✔        | ISO date `YYYY-MM-DD`.                       |
| `duration_months`  | number  | ✔        | Integer > 0.                                 |
| `end_date`         | string  | computed | `joining_date + duration_months` (recomputed on read). |
| `employment_status`| string  | computed | `Active Intern` \| `Past Employee`.          |
| `assigned_mentor`  | string  | –        | → `mentors.id`.                              |
| `document`         | map     | –        | `{filename, stored_name}` → Storage `documents/<stored_name>`. |

**Ownership:** the intern's own document; mentors may read only interns whose
`assigned_mentor` equals their profile ID.

## 4. `mentors`

| Field         | Type   | Required | Notes                                  |
| ------------- | ------ | -------- | -------------------------------------- |
| `id`          | string | ✔        | `DFM001`… (document ID).               |
| `name`        | string | ✔        |                                          |
| `email`       | string | ✔        |                                          |
| `phone`       | string | ✔        |                                          |
| `departments` | list\<string\> | ✔ | At least one department.           |
| `department`  | string | –        | Legacy first department (kept for compatibility). |
| `document`    | map    | –        | `{filename, stored_name}` → `documents/`. |

## 5. `tasks`

The largest collection. Parent tasks are admin projects; mentor work items are
subtasks of a parent.

| Field                    | Type    | Required | Notes                                            |
| ------------------------ | ------- | -------- | ------------------------------------------------ |
| `id`                     | string  | ✔        | `DFPY01` (admin) / `DFPY01-01` (mentor subtask). |
| `title`                  | string  | ✔        |                                                  |
| `description`            | string  | –        |                                                  |
| `task_type`              | string  | ✔        | `Individual Work` \| `Team Work`.                |
| `department`             | string  | ✔        |                                                  |
| `start_date`             | string  | ✔        | `YYYY-MM-DD`.                                    |
| `deadline`               | string  | ✔        | `YYYY-MM-DD`.                                    |
| `priority`               | string  | ✔        | `High` \| `Medium` \| `Low`.                     |
| `status`                 | string  | ✔        | Admin/confirmed status: `Start` / `In Progress` / `Completed` / `Not Completed`. |
| `intern_status`          | string  | ✔        | Status reported by the intern.                   |
| `mentor_status`          | string  | ✔        | Status last set by the mentor.                   |
| `mentor_pending_status`  | string/null | ✔    | Status waiting for mentor confirmation.          |
| `mentor_pending`         | bool    | ✔        | `true` while an intern's update awaits confirmation. |
| `completed_at`           | string  | –        | Set when status becomes `Completed`.             |
| `created_by_role`        | string  | ✔        | `admin` \| `mentor`.                             |
| `parent_task_id`         | string/null | ✔   | For subtasks → parent task ID.                   |
| `parent_task_title`      | string  | –        | Denormalised parent title.                       |
| `assigned_mentor`        | string  | –        | → `mentors.id` (drives mentor visibility).       |
| `assigned_intern_ids`    | list\<string\> | ✔  | → `interns.id` (team allocation).                |
| `assigned_names`         | list\<string\> | –  | Denormalised intern names (display only).        |
| `intern_id`              | string  | ✔        | First/legacy assigned intern (`assigned_intern_ids[0]`). |
| `intern_files`           | list\<map\> | –    | Task submissions, see below.                     |
| `intern_project_file`    | map     | –        | Mentor-visible intern submission `{filename, stored_name}` → `intern_files/`. |
| `final_project_file`     | map     | –        | Final ZIP submitted by mentor → `projects/`.     |
| `final_project_submitted_by` / `final_project_submitted_at` | string | – | Submission audit.               |
| `project_file`           | map     | –        | Legacy field kept for compatibility.             |

### `tasks/{id}/intern_files[]` (embedded file records)

| Field             | Type   | Notes                                              |
| ----------------- | ------ | -------------------------------------------------- |
| `id`              | string | Random 32-hex file ID.                             |
| `filename`        | string | Original filename (used for download name).        |
| `stored_name`     | string | Storage object: `intern_files/<stored_name>`.      |
| `task_id`         | string | → task ID.                                         |
| `intern_id`       | string | → `interns.id` (uploader).                         |
| `intern_name`     | string | Denormalised.                                      |
| `uploaded_at`     | string | ISO timestamp.                                     |
| `uploaded_by` / `uploaded_by_role` | string | Set for mentor uploads to admin.      |
| `sent_to_admin`   | bool   | Mentor forwarded this file to the admin.           |
| `sent_to_admin_at` / `sent_to_admin_by` | string | Forwarding audit.               |

> File metadata is embedded in the task document (the file *content* lives in
> Storage). This keeps the existing in-memory task logic unchanged and avoids
> cross-collection consistency problems.

**Visibility rules implemented in `app.py`:** interns see only their own
submissions; admins only see files with `sent_to_admin == true`; mentors see
files of their assigned interns.

## 6. `notifications`

| Field         | Type   | Notes                                                     |
| ------------- | ------ | --------------------------------------------------------- |
| `id`          | string | Random 32-hex (document ID).                             |
| `recipient_id`| string | → `users.id` of the recipient (never the profile ids).    |
| `task_id`     | string | → `tasks.id`.                                             |
| `task_title`  | string | Denormalised for the bell menu.                           |
| `user_name`   | string | Actor who caused the event.                               |
| `action`      | string | e.g. `Task assigned`, `Marked task as completed`.         |
| `created_at`  | string | ISO timestamp used for ordering in the UI.                |
| `read`        | bool   | The UI shows only unread items; “mark as read” deletes the document. |

---

## 7. Firebase Authentication

| Item              | Value                                                             |
| ----------------- | ----------------------------------------------------------------- |
| Provider          | Email/Password (enabled in the Firebase console)                  |
| Identifier        | `email` (users may still *type* their username — `app.py` resolves username → email before verification) |
| Password policy   | Firebase default (min 6 characters)                               |
| Custom claims     | `role`, `profileId`, `accountId` (used by security rules)         |
| Session           | Flask signed session cookie (unchanged UX); verified credentials come from Firebase |

## 8. Firebase Storage layout

Bucket: `FIREBASE_STORAGE_BUCKET` (default `<project-id>.appspot.com`), **private**
(no public ACLs; files are streamed through Flask after permission checks).

| Prefix          | Contents                                  | Source folder       | Server-side policy                          |
| --------------- | ----------------------------------------- | ------------------- | ------------------------------------------- |
| `documents/`    | Intern/mentor identity documents          | `uploads/documents` | pdf, images, doc/docx/odt/txt — max 20 MB  |
| `projects/`     | Final combined project ZIP (mentor)       | `uploads/projects`  | zip only — max 500 MB                       |
| `intern_files/` | Task submissions (intern → mentor → admin)| `uploads/intern_files` | archives, office, images, code, audio/video — max 500 MB |

Object name = `stored_name` stored in the record
(`{prefix}_{12-hex}_{original-filename}`), so records only need the object
name — the folder prefix comes from the record type.

---

## 9. Indexes & query patterns

No **composite** indexes are required: the application reads whole collections
and filters/sorts in Python exactly as it did with the JSON files, which keeps
the integration change minimal and index-free.

Recommended additions if the dataset grows:

| Purpose                                   | Suggested query / index                                        |
| ----------------------------------------- | -------------------------------------------------------------- |
| Unread bell for one user                  | `notifications.where('recipient_id','==',UID).where('read','==',false)` → composite (`recipient_id`, `read`) |
| Recent tasks per department               | `tasks.where('department','==',X).order_by('seq')` → composite (`department`, `seq`) |
| Active interns of a mentor                | `interns.where('assigned_mentor','==',MID)` (single-field index is automatic) |

## 10. Write/consistency model

`save_collection()` reproduces the semantics of “rewrite the whole JSON file”:

1. upsert every record of the list under its `id`,
2. delete documents that are no longer in the list,
3. skip documents whose content did not change (keeps `updatedAt` honest and
   saves write quota).

Concurrent saves of the same collection follow last-write-wins — the same
behaviour the application had with local JSON files. Deploy **one** Flask
instance (or add per-document updates) if you later need multi-instance
concurrency.
