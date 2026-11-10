# VERCEL_DEPLOY.md — Deploying INMS to Vercel

## What was wrong

Your first deployment failed **before any Python code ran**:

```
/vercel/path0/package.json: Unterminated string in JSON at position 1003
```

The `package.json` in the GitHub repository was **truncated at exactly 1003
characters** — it ended in the middle of `"@capacitor/`. Vercel could not parse
it, so the build stopped.

Fixed in commit `6254b58` (the file is now 1148 bytes and valid JSON).

After that fix the build succeeds and Vercel invokes the Flask function. It
returns HTTP 500 only because the Firebase environment variables are not set in
the Vercel project yet — see section 3.

---

## 1. How the Flask app runs on Vercel

Vercel does not run a Flask server; it runs the app as a **Python serverless
function**. The files added for this:

| File | Purpose |
| --- | --- |
| `api/index.py` | Entry point. Imports the real `app` from `app.py` and exposes it as the WSGI callable Vercel looks for. |
| `vercel.json` | Routes **every** request to that function, sets a 60 s timeout / 1 GB memory, and uses `public/` as the (empty) static output directory. |
| `public/.gitkeep` | Empty output directory, so repository files (templates, `app.py`, `users.json`, docs) are **never** served as static files. |
| `.vercelignore` | Keeps `android/`, `node_modules/`, `secrets/`, `.env`, legacy JSON data and docs out of the upload. Also hides `package.json`, so Vercel does not try to run a Node build. |
| `.python-version` | Pins Python 3.12 (Vercel's supported runtime). |

```
Request ──► Vercel rewrite ──► api/index.py ──► app.py (Flask) ──► Firebase
```

Templates, static files, sessions, validation and Firebase calls are unchanged.

---

## 2. Why `package.json` exists in a Python project

It is only there for the **Capacitor Android shell** (`npm run android:debug`).
It is excluded from the Vercel upload by `.vercelignore`, so the two targets do
not interfere.

---

## 3. Required environment variables (this is the remaining step)

Open your Vercel project →
**Settings → Environment Variables** →
<https://vercel.com/saravanan-ks-projects-092bdc6a/desflyer-inms-system/settings/environment-variables>

Add these **six** variables, each for **Production** (tick *Preview* too if you
use preview deployments):

| Name | Value |
| --- | --- |
| `FIREBASE_PROJECT_ID` | `desflyer-inms` |
| `FIREBASE_STORAGE_BUCKET` | `desflyer-inms.firebasestorage.app` |
| `FIREBASE_WEB_API_KEY` | `AIzaSyDOJVupgIUUN3fODWU--LB3mXrxGT59POE` |
| `FIREBASE_CREDENTIALS` | base64 of `secrets\firebase-service-account.json` (see below) |
| `FLASK_SECRET_KEY` | the value already in your local `.env` |
| `FIREBASE_USE_EMULATORS` | `0` |

### The service account value

Vercel cannot read a file, so the key is passed **inline as base64**. In
PowerShell, from the project folder:

```powershell
cd C:\Users\user\OneDrive\Desktop\INMS\DesFlyer-INMS-System
[Convert]::ToBase64String([IO.File]::ReadAllBytes("secrets\firebase-service-account.json")) | Set-Clipboard
```

The base64 string is now on your clipboard. Paste it as the value of
`FIREBASE_CREDENTIALS` in Vercel.

> `firebase_config.py` accepts the key in three forms: inline JSON, base64 JSON
> (what we use here), or a file path. Base64 is used because it survives
> environment-variable handling unchanged.

### Get the Flask secret

```powershell
Select-String -Path .env -Pattern "^FLASK_SECRET_KEY="
```

Copy everything after the `=`.

---

## 4. Redeploy

Environment variables are applied only to **new** deployments.

Vercel dashboard → **Deployments** → the top deployment → **⋯** → **Redeploy**.

Or push any commit:

```powershell
git commit --allow-empty -m "Redeploy with Firebase env vars"
git push origin main
```

---

## 5. Verify

1. Open <https://desflyer-inms-system.vercel.app/login>
2. Role **Admin**, e-mail `saravanankodi5@gmail.com`, password `SK@DesFlyer`.
3. You should reach `/admin/dashboard`.

If it still returns 500, open **Deployments → Functions → Logs** (or
**Logs** in the sidebar) and look for `[INMS] Firebase configuration error`.
That message names the exact missing variable.

---

## 6. Vercel limits that affect this app

| Limit | Value | Impact |
| --- | --- | --- |
| Request body size | **4.5 MB** | Uploads larger than 4.5 MB fail with `413` **before** reaching Flask. The app allows up to 500 MB locally. |
| Function duration | 60 s (set in `vercel.json`) | Very large uploads/downloads may time out. |
| Cold start | 1–3 s | First request after idle is slower (Firebase Admin init). |
| Hobby plan | Non-commercial only | DesFlyer is a company app — Vercel's terms require **Pro**. |

### Recommended for full functionality

Document uploads are a core feature (up to 500 MB). If users need large
uploads, deploy the same code to a host that runs a normal long-lived process:

- **Render** — `gunicorn app:app`, free tier available
- **Railway** — container or buildpack, simple env vars
- **Fly.io** — Docker, persistent process

No code changes are needed for those: `requirements.txt` + `app.py` are already
deployment-ready, and `FIREBASE_CREDENTIALS` works the same way.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Unterminated string in JSON` | Truncated `package.json` | Fixed in `6254b58`; verify the raw file on GitHub ends with `}` |
| `FUNCTION_INVOCATION_FAILED` / 500 | Missing env var | Section 3 |
| 500 only after redeploy | Env var added to the wrong environment | Add to **Production**, then redeploy |
| Login says "Invalid login details" | Firestore `users` link missing | Already provisioned (account `7405533183`, role `admin`) |
| `413 Request Entity Too Large` | Upload > 4.5 MB | Use a container host (section 6) |
| `Permission denied` in logs | Rules deny a client call | Expected — the server uses the Admin SDK |
| Timeout on upload | 60 s function limit | Container host |

---

## 8. Files added for Vercel

```
api/index.py
vercel.json
.vercelignore
.python-version
public/.gitkeep
VERCEL_DEPLOY.md
```

Commit: `6254b58 — Fix Vercel deployment: restore package.json and add Flask serverless entry`
