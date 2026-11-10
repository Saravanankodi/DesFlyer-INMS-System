# FIREBASE_SETUP.md — INMS Firebase Setup Guide

A complete, beginner-friendly walkthrough for connecting this Flask application
to **your** Firebase project (`desflyer-inms`).

Every step is labelled so you always know *where* to do it:

| Label | Meaning |
| --- | --- |
| **CONSOLE** | Click in <https://console.firebase.google.com> (browser) |
| **TERMINAL** | Run a command in PowerShell in the project folder |
| **AUTOMATIC** | The application already does this — nothing for you to do |
| **OPTIONAL** | Nice to have, not required for login |

Project folder used in all examples:

```
C:\Users\user\OneDrive\Desktop\INMS\DesFlyer-INMS-System
```

---

## 1. How to use this document

Read sections **2 → 3 → 4** once, then follow **section 5** to finish the
setup. Sections 6–21 are reference material you can return to later.

If login fails at any point, run the built-in doctor first:

```powershell
python check_firebase_connection.py --email saravanankodi5@gmail.com --password "SK@DesFlyer"
```

It tells you exactly which piece is missing.

---

## 2. What the app uses Firebase for

| Firebase product | Used for | Who talks to it |
| --- | --- | --- |
| **Authentication** | Stores e-mail + password. Passwords are **never** stored in your database. | Flask server (Admin SDK + REST sign-in) |
| **Cloud Firestore** | All records: users, interns, mentors, tasks, notifications | Flask server (Admin SDK) |
| **Cloud Storage** | Uploaded documents, project ZIPs, intern submissions | Flask server (Admin SDK) |

> **Important:** the browser never talks to Firebase directly. The Flask
> server is the only client. That is why the security rules are a *second*
> line of defence — the server already checks every role and every form field.

---

## 3. What is already done in your project

Tick these off before continuing:

- [x] Firebase project **`desflyer-inms`** exists
- [x] **Authentication → Users** contains `saravanankodi5@gmail.com`
- [x] **Email/Password** sign-in provider is enabled
- [x] **Firestore Database** `(default)` is created
- [x] Firestore **rules** were pasted and published
- [x] **Storage** bucket `desflyer-inms.firebasestorage.app` exists and its rules were pasted

**Still missing (this is why login does not work):**

- [ ] The **service account key** file (`secrets\firebase-service-account.json`)
- [ ] A **`users` document** linking your Auth account to the `admin` role
- [ ] Starting the app in **production mode** (emulator mode is currently off — good)

---

## 4. Configuration values (`.env`)

**AUTOMATIC** — already written for you in `.env`:

```ini
FIREBASE_PROJECT_ID=desflyer-inms
FIREBASE_STORAGE_BUCKET=desflyer-inms.firebasestorage.app
FIREBASE_WEB_API_KEY=AIzaSyDOJVupgIUUN3fODWU--LB3mXrxGT59POE
FIREBASE_CREDENTIALS_FILE=secrets/firebase-service-account.json
FIREBASE_USE_EMULATORS=0
FLASK_SECRET_KEY=<random 64-character value>
```

Where each value comes from, if you ever need to re-check it:

| Variable | **CONSOLE** location |
| --- | --- |
| `FIREBASE_PROJECT_ID` | Project settings → General → *Project ID* |
| `FIREBASE_STORAGE_BUCKET` | Storage → bucket name shown at the top |
| `FIREBASE_WEB_API_KEY` | Project settings → General → Your apps → Web app → `apiKey` |
| `FIREBASE_CREDENTIALS_FILE` | File you download in section 5 |

> `.env` is git-ignored. **Never commit it.** `.env.example` is the committed
> template.

---

## 5. Download the service account key — **the missing step**

This is the only blocker right now. Without it the app refuses to start
(by design — it never falls back to local files).

### 5.1 **CONSOLE**

1. Open
   <https://console.firebase.google.com/project/desflyer-inms/settings/serviceaccounts/adminsdk>
   (or: ⚙️ **Project settings** → **Service accounts**).
2. Make sure the **Firebase Admin SDK** tab is selected.
3. Click **Generate new private key**.
4. Confirm with **Generate key**.
5. A `.json` file downloads, named like
   `desflyer-inms-firebase-adminsdk-abc12-3f4e5d6c7b.json`.

### 5.2 **TERMINAL** — move it into the project

The app expects it at `secrets\firebase-service-account.json`:

```powershell
cd C:\Users\user\OneDrive\Desktop\INMS\DesFlyer-INMS-System
New-Item -ItemType Directory -Force secrets | Out-Null
Copy-Item "$env:USERPROFILE\Downloads\desflyer-inms-firebase-adminsdk-*.json" `
          "secrets\firebase-service-account.json"
```

Check it landed:

```powershell
Test-Path secrets\firebase-service-account.json
```

Expected output: `True`

### 5.3 **TERMINAL** — verify the connection

```powershell
python check_firebase_connection.py --email saravanankodi5@gmail.com --password "SK@DesFlyer"
```

What you should see after this section (the `users` link is fixed in section 8):

```
[PASS] project id            -> desflyer-inms
[PASS] storage bucket        -> desflyer-inms.firebasestorage.app
[PASS] web API key           -> set
[PASS] emulator mode         -> off (real project)
[PASS] service account key   -> service account file: ...\secrets\firebase-service-account.json
[PASS] Firestore reachable   -> 0 document(s) in users
[PASS] Firebase Authentication reachable
[PASS] Auth account exists   -> c0uYAjnsklRk6WBoo02E7SYGndA2
[PASS] password accepted by Firebase Auth
[FAIL] linked to a users document -> NOT LINKED ...
```

> **Security:** the downloaded key gives full admin access to your project.
> Keep it inside `secrets\` (git-ignored). Never e-mail it, paste it in chat,
> or commit it. If it leaks: **CONSOLE** → Service accounts → delete that key
> and generate a new one.

---

## 6. Authentication: e-mail/password and your admin user

### 6.1 Enable the provider — **CONSOLE**

<https://console.firebase.google.com/project/desflyer-inms/authentication/providers>

- **Email/Password** → status must be **Enabled** → **Save**.

### 6.2 Your admin account — already exists

<https://console.firebase.google.com/project/desflyer-inms/authentication/users>

| Email | UID |
| --- | --- |
| `saravanankodi5@gmail.com` | `c0uYAjnsklRk6WBoo02E7SYGndA2` |

The password you set in the console (`SK@DesFlyer`) is the one the Flask login
form verifies. Passwords are never copied into Firestore.

### 6.3 Add more accounts later

Two ways:

- **CONSOLE** → Authentication → Users → **Add user** (creates the password),
  then run the linking command from section 8.
- **In the app** → log in as admin → **Login Accounts** → **Add account**
  (**AUTOMATIC**: creates the Auth user *and* the Firestore link together).

> **Do not** create login accounts by hand in Firestore alone — the password
> must exist in Authentication, otherwise the app shows
> *"This account does not exist in Firebase Authentication yet."*

---

## 7. Firestore: database, rules and collections

### 7.1 Database — **CONSOLE** (already done)

<https://console.firebase.google.com/project/desflyer-inms/firestore/databases/-default-/data>

You do **not** need to create collections manually. Firestore creates a
collection the first time a document is written to it. The app creates:

| Collection | Created when |
| --- | --- |
| `users` | first login account is linked (section 8) |
| `mentors` | first mentor is added in the app |
| `interns` | first intern is added in the app |
| `tasks` | first task/project is created |
| `notifications` | first task event happens |

### 7.2 Rules — **CONSOLE** (already done, verify)

<https://console.firebase.google.com/project/desflyer-inms/firestore/databases/-default-/rules>

The editor must contain exactly the contents of the file
`firestore.rules` in this project. To re-apply:

1. Open `firestore.rules` in VS Code.
2. `Ctrl+A`, `Ctrl+C`.
3. Paste into the console editor (replace everything).
4. Click **Publish**. Wait for *"Rules published"*.

Key points of these rules (details in section 16):

- No `allow ... if true` anywhere.
- Every read/write requires a signed-in user with the right custom claim.
- Any document containing a `password` field is rejected.
- Unknown paths are denied by default.

### 7.3 Indexes — **CONSOLE**

<https://console.firebase.google.com/project/desflyer-inms/firestore/indexes>

**No composite indexes are required.** The app reads whole collections and
sorts in Python, exactly like it did with the JSON files. If the console ever
shows a "missing index" link, click it — but you should not need to.

---

## 8. Link your Auth account to the `admin` role — **TERMINAL**

The login form looks up the user in the Firestore **`users`** collection. Your
Auth account exists, but no `users` document points to it yet, so the form says
*"Invalid login details or selected role."*

### 8.1 Run the linking script

```powershell
cd C:\Users\user\OneDrive\Desktop\INMS\DesFlyer-INMS-System
python provision_firebase_user.py --email saravanankodi5@gmail.com --username admin --role admin
```

Expected output:

```
Provisioned admin access for the existing Firebase Auth account.
```

What it does (**AUTOMATIC**):

1. Finds the Auth account by e-mail (does **not** change its password).
2. Creates `users/<account-id>` with `id`, `username`, `email`, `role`, `uid`.
3. Sets the custom claims `role=admin`, `profileId=""`, `accountId=<id>`
   used by the security rules.
4. Is safe to run twice — a second run just refreshes the claims.

Afterwards **CONSOLE** → Firestore → Data shows:

```
users
└── <10-character-id>
    ├── id:        "<10-character-id>"
    ├── username:  "admin"
    ├── email:     "saravanankodi5@gmail.com"
    ├── role:      "admin"
    ├── uid:       "c0uYAjnsklRk6WBoo02E7SYGndA2"
    ├── seq:       1
    ├── createdAt: <timestamp>
    └── updatedAt: <timestamp>
```

### 8.2 Alternative: create the document by hand — **CONSOLE**

Only if you cannot run the script. Claims will be missing (the Flask app still
works, because it uses the Admin SDK), but the security rules will treat the
account as having no role.

Firestore → **Start collection** → collection ID `users` → **Next** →
Document ID `admin01` → add fields:

| Field | Type | Value |
| --- | --- | --- |
| `id` | string | `admin01` |
| `username` | string | `admin` |
| `email` | string | `saravanankodi5@gmail.com` |
| `role` | string | `admin` |
| `uid` | string | `c0uYAjnsklRk6WBoo02E7SYGndA2` |
| `seq` | number | `1` |

→ **Save**. (Prefer the script — it also sets the claims.)

---

## 9. Storage: bucket and rules

### 9.1 Bucket — **CONSOLE** (already done)

<https://console.firebase.google.com/project/desflyer-inms/storage>

Bucket name: **`desflyer-inms.firebasestorage.app`**

> Newer projects use `.firebasestorage.app`; older ones use `.appspot.com`.
> Use exactly what the console shows. `.env` already has the right value.

### 9.2 Rules — **CONSOLE** (already done, verify)

Storage → **Rules** tab → the editor must contain the contents of
`storage.rules` → **Publish**.

The bucket stays **private**. Files are uploaded and downloaded by the Flask
server, which checks role + ownership first (`storage_service.py`). The rules
repeat the same content-type and size limits as a second gate:

| Folder | Who may write | Limits |
| --- | --- | --- |
| `documents/` | admin | PDF, images, Word/ODT, text — max 20 MB |
| `projects/` | mentor | ZIP only — max 500 MB |
| `intern_files/` | admin, mentor, intern | archives, documents, images, media — max 500 MB |
| anything else | nobody | denied |

> **Do not** make the bucket public and do not add `allUsers` access. The app
> serves downloads through Flask, so the bucket must stay private.

---

## 10. Deploy rules from the project files — **TERMINAL** (optional)

Instead of copy/pasting, you can deploy the exact files:

```powershell
cd C:\Users\user\OneDrive\Desktop\INMS\DesFlyer-INMS-System
firebase login --reauth
firebase use desflyer-inms
firebase deploy --only firestore:rules,storage
```

`firebase.json` already points at `firestore.rules` and `storage.rules`.
This is also the safest way to keep the console and the repository identical.

---

## 11. Data model overview

Full details: **`DATABASE_SCHEMA.md`**. Short version:

| Collection | Document ID | Example |
| --- | --- | --- |
| `users` | account id | `admin01` |
| `mentors` | mentor id | `DFM001` |
| `interns` | intern id | `DFIN001` |
| `tasks` | task id | `DFPY01`, `DFPY01-01` |
| `notifications` | random id | `a3f9…` |

Every document also has:

| Field | Meaning |
| --- | --- |
| `id` | same value as the document ID |
| `seq` | creation order (keeps tables in the original order) |
| `createdAt` | server timestamp, first write |
| `updatedAt` | server timestamp, last real change |

**No document ever contains a password.**

---

## 12. Start the app and test the login — **TERMINAL**

```powershell
cd C:\Users\user\OneDrive\Desktop\INMS\DesFlyer-INMS-System
python app.py
```

Expected console output:

```
[INMS] Firebase initialised (project=desflyer-inms, bucket=desflyer-inms.firebasestorage.app, mode=production)
 * Running on http://127.0.0.1:5000
```

Then in the browser:

1. Open <http://127.0.0.1:5000/login>
2. Select the **Admin** role.
3. **Username or email:** `saravanankodi5@gmail.com` (or `admin`)
4. **Password:** `SK@DesFlyer`
5. You should land on `/admin/dashboard` with *"Welcome, admin!"*.

If you see **"Invalid login details or selected role."**, go to section 17.

---

## 13. Creating the rest of the data

All of this is normal app usage — no console work needed.

| Task | Where in the app |
| --- | --- |
| Add a mentor | Mentors → Add Mentor |
| Add an intern | Interns → Add Intern |
| Create a login for a mentor/intern | Login Accounts → Add Account (pick the profile) |
| Create a project/task | Tasks → Add Task |
| Upload a document | inside the mentor/intern form |

Each action writes to Firestore and (for uploads) to Storage immediately.
Refresh the Firebase console to see the new documents/objects.

---

## 14. Security rules explained (what and why)

### 14.1 Why rules matter even though the server bypasses them

The Flask server uses the **Firebase Admin SDK**, which ignores security rules.
Primary access control is in `app.py` (role gates, ownership checks, validation).

The rules protect the project if:

- someone gets the Web API key (it is public by design) and tries the Firebase
  REST/SDK APIs directly,
- a future feature adds a browser-side Firebase call,
- a misconfigured tool or script is pointed at your project.

### 14.2 Roles come from custom claims

| Claim | Value | Used by |
| --- | --- | --- |
| `role` | `admin` / `mentor` / `intern` | every rule |
| `profileId` | `DFM001` / `DFIN001` / `""` | mentor/intern ownership checks |
| `accountId` | `users` document id | notification ownership |

The scripts and the app set these automatically. Verify them in
**CONSOLE** → Authentication → Users → click the user → *Custom claims*, or run
`python check_firebase_connection.py ...` (section 5.3).

### 14.3 What the rules guarantee

| Guarantee | Where |
| --- | --- |
| No unauthenticated read or write | all `match` blocks |
| No `allow ... if true` | verified — none exist |
| Interns only see their own tasks/files | `tasks`, `intern_files` |
| Mentors only see their own interns/tasks | `interns`, `tasks` |
| Only admins manage accounts and profiles | `users`, `interns`, `mentors` |
| No passwords in the database | `noPassword()` in every write rule |
| Upload type/size limits | `storage.rules` |

---

## 15. Common mistakes to avoid

| Mistake | Result | Fix |
| --- | --- | --- |
| Committing `.env` or the key file | Full project takeover risk | Keep `secrets/` git-ignored; rotate the key if leaked |
| Using `.appspot.com` for a `.firebasestorage.app` project | Storage 404 | Copy the bucket name from the console |
| Leaving `FIREBASE_USE_EMULATORS=1` | App talks to localhost; real accounts "don't exist" | Set it to `0` |
| Creating the Auth user but not the `users` doc | "Invalid login details" | Section 8 |
| Creating the `users` doc but not the Auth user | "account does not exist in Firebase Authentication yet" | Section 6.3 |
| Choosing the wrong role on the login form | "Invalid login details or selected role." | Role must match the account |
| Making the Storage bucket public | Anyone can read private documents | Keep it private |

---

## 16. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| App exits with *"The service account key file does not exist"* | Key not downloaded | Section 5 |
| App exits with *"No Firebase credentials found"* | `FIREBASE_CREDENTIALS_FILE` missing in `.env` | Section 4 |
| *"Invalid login details or selected role."* | No `users` doc, wrong password, or wrong role | Sections 8 and 17 |
| *"This account does not exist in Firebase Authentication yet."* | `users` doc exists, Auth user does not | Create the Auth user (6.3) |
| *"Authentication service is temporarily unavailable."* | Network / wrong API key | Check `FIREBASE_WEB_API_KEY`; check internet |
| *"Username or email is already in use."* | Duplicate in Auth or Firestore | Use a different e-mail |
| Uploads fail with *"not allowed"* | File type/size policy | See the table in 9.2 |
| Storage 404 on download | Wrong bucket name in `.env` | Section 9.1 |
| `Permission denied` in Firestore console logs | Rules deny a client-side call | Expected — the server uses the Admin SDK |

Still stuck? Run:

```powershell
python check_firebase_connection.py --email saravanankodi5@gmail.com --password "SK@DesFlyer"
```

---

## 17. "Invalid login details" — exact diagnosis

The login form only accepts a user when **all four** are true:

1. a `users` document exists whose `username` **or** `email` matches what you typed,
2. that document's `role` equals the role radio button you selected,
3. Firebase Authentication accepts the e-mail + password,
4. a Firebase Auth account exists for the e-mail in that document.

Your current state:

| Check | Status |
| --- | --- |
| Auth account exists | ✅ `c0uYAjnsklRk6WBoo02E7SYGndA2` |
| Password accepted by Firebase | ✅ verified |
| `users` document exists | ❌ **missing — this is the cause** |
| App in production mode | ❌ was `FIREBASE_USE_EMULATORS=1`, now `0` |
| Service account key | ❌ **missing** |

Do sections 5 and 8, then login works.

---

## 18. Security checklist

- [ ] `.env` is git-ignored and never committed
- [ ] `secrets/` is git-ignored; the key file is not inside OneDrive sync if possible
- [ ] `FIREBASE_USE_EMULATORS=0`
- [ ] Firestore rules published from `firestore.rules`
- [ ] Storage rules published from `storage.rules`
- [ ] Storage bucket is private (no `allUsers`)
- [ ] No `allow read, write: if true` in either rules file
- [ ] Passwords exist only in Authentication (never in Firestore)
- [ ] `FLASK_SECRET_KEY` is a long random value (already generated)
- [ ] Service account key rotated if it was ever shared

---

## 19. Migrating the old local JSON data — **OPTIONAL**

The old files (`interns.json`, `mentors.json`, `tasks.json`, `users.json`,
`notifications.json`) still exist but are **not read** by the app. To copy their
content into Firestore:

```powershell
python migrate_to_firebase.py --dry-run     # preview
python migrate_to_firebase.py               # write
```

Notes:

- Passwords are PBKDF2 hashes and cannot be migrated. The script creates Auth
  accounts with a temporary password you choose, or skips them.
- In your case the old files only contain one demo admin (`desflyer`) with a
  fake e-mail — you do **not** need to migrate anything.
- A migration is one-way for deleted records: documents removed from the JSON
  are removed from Firestore on the next save.

---

## 20. Local development with the Emulator Suite — **OPTIONAL**

Never point automated tests at the real project.

```powershell
# terminal 1 — start emulators (demo project, no real data)
firebase emulators:start --project demo-inms --only "auth,firestore,storage"

# terminal 2 — run the app against them
$env:FIREBASE_USE_EMULATORS="1"
$env:FIREBASE_PROJECT_ID="demo-inms"
$env:FLASK_SECRET_KEY="local-dev-only"
python app.py
```

Emulator ports: Auth `9099`, Firestore `8080`, Storage `9199`, Hub `4400`.

Tests:

```powershell
python tests\backend_smoke_test.py
python tests\security_rules_test.py
```

> Emulator mode is a **separate** database. Data created there never appears in
> the real project — that is exactly why the real login failed while
> `FIREBASE_USE_EMULATORS=1` was set.

---

## 21. Final checklist and quick reference

### Do this now, in order

| # | Where | Action |
| --- | --- | --- |
| 1 | **CONSOLE** | Project settings → Service accounts → **Generate new private key** |
| 2 | **TERMINAL** | Move the JSON to `secrets\firebase-service-account.json` (5.2) |
| 3 | **TERMINAL** | `python check_firebase_connection.py --email saravanankodi5@gmail.com --password "SK@DesFlyer"` |
| 4 | **TERMINAL** | `python provision_firebase_user.py --email saravanankodi5@gmail.com --username admin --role admin` |
| 5 | **TERMINAL** | `python app.py` |
| 6 | Browser | <http://127.0.0.1:5000/login> → Admin → e-mail + password |
| 7 | **CONSOLE** | Confirm `users` collection now contains your admin document |
| 8 | **OPTIONAL** | `firebase deploy --only firestore:rules,storage` |

### Useful commands

```powershell
python check_firebase_connection.py --email <email> --password "<password>"
python provision_firebase_user.py --email <email> --username <name> --role admin
python migrate_to_firebase.py --dry-run
firebase deploy --only firestore:rules,storage
python tests\backend_smoke_test.py
python tests\security_rules_test.py
```

### Useful console links

| Page | URL |
| --- | --- |
| Authentication users | <https://console.firebase.google.com/project/desflyer-inms/authentication/users> |
| Sign-in providers | <https://console.firebase.google.com/project/desflyer-inms/authentication/providers> |
| Firestore data | <https://console.firebase.google.com/project/desflyer-inms/firestore/databases/-default-/data> |
| Firestore rules | <https://console.firebase.google.com/project/desflyer-inms/firestore/databases/-default-/rules> |
| Storage files | <https://console.firebase.google.com/project/desflyer-inms/storage> |
| Service accounts | <https://console.firebase.google.com/project/desflyer-inms/settings/serviceaccounts/adminsdk> |
| Project settings | <https://console.firebase.google.com/project/desflyer-inms/settings/general> |

---

*Files referenced by this guide: `.env`, `.env.example`, `firebase_config.py`,
`firebase_auth_service.py`, `data_store.py`, `storage_service.py`,
`firestore.rules`, `storage.rules`, `firebase.json`,
`provision_firebase_user.py`, `check_firebase_connection.py`,
`migrate_to_firebase.py`, `DATABASE_SCHEMA.md`.*
