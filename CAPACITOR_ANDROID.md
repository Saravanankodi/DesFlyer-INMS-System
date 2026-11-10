# CAPACITOR_ANDROID.md — Android app (Capacitor) setup

This project is a **server-rendered Flask application**. Capacitor cannot run
Python, so the Android app is a native **WebView shell** that loads your
deployed INMS website. Everything (Jinja templates, routes, login, Firebase)
keeps running on the Flask server; the phone only renders it.

```
Android APK  ──►  WebView  ──►  https://<your-live-domain>
                                   (Flask + Firebase, unchanged)
```

---

## 1. What was created

| Path | Purpose |
| --- | --- |
| `capacitor.config.ts` | App id, name, `webDir`, and the `server.url` you will fill in |
| `out/index.html` | Offline / "not configured" shell page (Capacitor requires `webDir`) |
| `android/` | Full native Android project (Gradle, manifest, resources) |
| `android/app/src/main/java/com/desflyer/inms/MainActivity.java` | Session-cookie persistence + file downloads |
| `package.json` | Capacitor dependencies and build scripts |
| `.gitignore` | `node_modules/`, Gradle build output, keystores |

### Installed packages

```
@capacitor/core        8.6.0
@capacitor/android     8.6.0
@capacitor/cli         8.6.0  (dev)
typescript             5.9.x (dev — required to read capacitor.config.ts)
```

> **Why `typescript@5`?** TypeScript 7 removed the compiler API that Capacitor
> uses to load `.ts` config files. Do not upgrade to TypeScript 7 unless you
> switch to `capacitor.config.json`.

### `appId` — one intentional change

You proposed `com.desflyer.desflyer-INMS`. Android application ids must be valid
Java package names: **letters, digits and underscores only, separated by dots**.
A hyphen (`-`) is illegal and the Gradle build fails.

This project uses:

```ts
appId: "com.desflyer.inms"
appName: "DesFlyer-INMS"   // the name shown on the phone is unchanged
```

Changing the app id later changes the Play Store identity, so keep this one.

---

## 2. Add the live URL (the only step left)

Open `capacitor.config.ts` and uncomment / edit:

```ts
server: {
  url: "https://inms.desflyer.com",   // <-- your HTTPS domain
  androidScheme: "https",
  cleartext: false,
  allowNavigation: [],
},
```

Then:

```powershell
cd C:\Users\user\OneDrive\Desktop\INMS\DesFlyer-INMS-System
npx cap sync android
```

That is the whole change. No frontend, template or backend code is touched.

> **Requirements for the URL**
> - Must be **HTTPS** (`cleartext: false` blocks plain HTTP).
> - Must be publicly reachable (or reachable from the phone's network).
> - Serve the app at the domain root, or set `url` to the full prefix
>   (e.g. `https://example.com/inms`).
> - The Flask session cookie must be allowed. Default Flask settings work.

---

## 3. Build the APK

### Debug build (for testing on your phone)

```powershell
cd C:\Users\user\OneDrive\Desktop\INMS\DesFlyer-INMS-System
npm run android:debug
```

Output:

```
android\app\build\outputs\apk\debug\app-debug.apk
```

Install it:

```powershell
adb install -r android\app\build\outputs\apk\debug\app-debug.apk
```

Or open the project in Android Studio:

```powershell
npm run cap:open
```

### Release build (for distribution)

1. Create a keystore **once** (keep it safe, never commit it):

```powershell
keytool -genkey -v -keystore android\desflyer-inms.keystore `
        -alias desflyer -keyalg RSA -keysize 2048 -validity 10000
```

2. Create `android/keystore.properties` (git-ignored):

```properties
storeFile=../desflyer-inms.keystore
storePassword=YOUR_STORE_PASSWORD
keyAlias=desflyer
keyPassword=YOUR_KEY_PASSWORD
```

3. Add to `android/app/build.gradle` inside `android { ... }`:

```gradle
def keystoreProperties = new Properties()
def keystorePropertiesFile = rootProject.file("keystore.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(new FileInputStream(keystorePropertiesFile))
}

signingConfigs {
    release {
        if (keystorePropertiesFile.exists()) {
            storeFile file(keystoreProperties['storeFile'])
            storePassword keystoreProperties['storePassword']
            keyAlias keystoreProperties['keyAlias']
            keyPassword keystoreProperties['keyPassword']
        }
    }
}
buildTypes {
    release {
        signingConfig signingConfigs.release
        minifyEnabled false
        proguardFiles getDefaultProguardFile('proguard-android.txt'), 'proguard-rules.pro'
    }
}
```

4. Build:

```powershell
npm run android:release
```

Output: `android\app\build\outputs\apk\release\app-release.apk`

> `android/keystore.properties` and `*.keystore` are already git-ignored.

---

## 4. What the Android shell handles for you

| Concern | Handling |
| --- | --- |
| **Login session** | `CookieManager` accepts cookies; the Flask session survives app restarts |
| **File downloads** (report PDFs, documents) | `MainActivity` attaches a `DownloadListener` that hands the URL to Android's `DownloadManager` **with the session cookie**, so authenticated downloads work |
| **File uploads** (documents, project ZIPs) | Capacitor's WebView implements `onShowFileChooser`; the native file picker opens normally |
| **Hardware back button** | Walks back through WebView history, then exits the app |
| **Keyboard** | `windowSoftInputMode="adjustResize"` so forms are not covered |
| **Mixed content** | Blocked (`allowMixedContent: false`) |
| **Cleartext HTTP** | Blocked (`usesCleartextTraffic="false"`) |

---

## 5. Known limitations (server-rendered app in a WebView)

| Limitation | Impact | Workaround |
| --- | --- | --- |
| Needs internet | No offline mode | `out/index.html` shows a clear message; a full offline app would require a separate API + client rewrite |
| Push notifications | The web bell only works while the app is open | Add FCM + a Capacitor push plugin later |
| Native look | It is the website, not native screens | By design — keeps the UI identical |
| Deep links | Only the configured domain loads | Add `allowNavigation` entries or an intent filter |
| App updates | Web changes deploy instantly; shell changes need a new APK | Only `capacitor.config.ts` / native code require a rebuild |

---

## 6. Icons and splash screen

The generated project uses the default Capacitor artwork. Replace it with the
DesFlyer logo:

1. Prepare a **1024×1024 PNG** logo.
2. Use Android Studio: right-click `android/app/src/main/res` →
   **New → Image Asset** → set the icon and round icon.
3. Splash: `android/app/src/main/res/drawable/splash.png` (and the
   `drawable-*` variants) or the `core-splashscreen` theme in
   `res/values/styles.xml`.

The launcher name is already **DesFlyer-INMS** (`res/values/strings.xml`).

---

## 7. Everyday workflow

```powershell
# after changing capacitor.config.ts, out/, or native plugins
npx cap sync android

# build + install debug
npm run android:debug
adb install -r android\app\build\outputs\apk\debug\app-debug.apk

# open in Android Studio
npm run cap:open

# check versions
npx cap doctor
```

Backend changes (Flask, templates, Firebase) need **no rebuild** — deploy the
server and the app picks them up on next launch.

---

## 8. Checklist before release

- [ ] `server.url` points at the production HTTPS domain
- [ ] `npx cap sync android` run after the config change
- [ ] Login works on a real phone (session persists after killing the app)
- [ ] Document upload works from the phone
- [ ] Report PDF download lands in the phone's Downloads folder
- [ ] Back button behaves correctly on every screen
- [ ] App icon and splash replaced
- [ ] Release keystore created and backed up
- [ ] `versionCode` / `versionName` bumped in `android/app/build.gradle`
- [ ] `android:usesCleartextTraffic` stays `false`

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Blank white screen | `server.url` missing or unreachable | Check the URL in a phone browser |
| "Webpage not available" | HTTP URL or no internet | Use HTTPS; check connectivity |
| Login does not stick | Cookies blocked | Keep the `CookieManager` lines in `MainActivity` |
| Download does nothing | Old APK without the download listener | Rebuild with `npm run android:debug` |
| `Parsing capacitor.config.ts failed` | TypeScript 7 installed | `npm install -D typescript@5` |
| Gradle: invalid package name | Hyphen in `appId` | Keep `com.desflyer.inms` |
| Build fails: SDK not found | `android/local.properties` missing | Add `sdk.dir=...\Android\Sdk` |
