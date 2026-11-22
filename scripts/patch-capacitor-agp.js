/**
 * Keep the Android Gradle plugin pinned to the version the installed
 * Android Studio supports.
 *
 * Capacitor generates `android/capacitor-cordova-android-plugins/build.gradle`
 * and ships `node_modules/@capacitor/android/capacitor/build.gradle`; both
 * declare a buildscript classpath of AGP 8.13.0. Android Studio Ladybug
 * (build 242) only accepts AGP up to 8.8.2, so leaving those lines alone
 * brings the "incompatible version (AGP 8.13.0)" error straight back after
 * every `npm install` or `npx cap sync`.
 *
 * The value here must match `android/build.gradle`.
 *
 * Run automatically by the npm `postinstall` script; safe to run any time:
 *
 *     node scripts/patch-capacitor-agp.js
 */

const fs = require('fs');
const path = require('path');

const TARGET_AGP = '8.8.2';
const ROOT = path.join(__dirname, '..');
const GRADLE_FILES = [
  path.join(ROOT, 'node_modules', '@capacitor', 'android', 'capacitor', 'build.gradle'),
  path.join(ROOT, 'android', 'capacitor-cordova-android-plugins', 'build.gradle'),
];
const PATTERN = /com\.android\.tools\.build:gradle:\d+\.\d+\.\d+/;

function patch(file) {
  const relative = path.relative(ROOT, file);

  if (!fs.existsSync(file)) {
    // Not generated yet - nothing to do.
    console.log(`[agp-pin] skipped: ${relative} does not exist`);
    return;
  }

  const source = fs.readFileSync(file, 'utf8');
  if (!PATTERN.test(source)) {
    console.log(`[agp-pin] skipped: no AGP classpath in ${relative}`);
    return;
  }

  const patched = source.replace(
    PATTERN,
    `com.android.tools.build:gradle:${TARGET_AGP}`
  );

  if (patched === source) {
    console.log(`[agp-pin] ${relative} already at AGP ${TARGET_AGP}`);
    return;
  }

  fs.writeFileSync(file, patched, 'utf8');
  console.log(`[agp-pin] ${relative} pinned to AGP ${TARGET_AGP}`);
}

GRADLE_FILES.forEach(patch);
