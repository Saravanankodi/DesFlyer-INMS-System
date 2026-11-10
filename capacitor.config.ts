import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  // Android application id. Must be a valid Java package name
  // (letters, digits, underscores and dots only) - a hyphen is illegal.
  appId: "com.desflyer.inms",
  appName: "DesFlyer-INMS",
  webDir: "out",

  // ---------------------------------------------------------------------
  // LIVE SERVER
  // The Flask app is server-rendered, so the Android shell loads the
  // deployed website inside a WebView. When your domain is ready, uncomment
  // the next line and replace it with your HTTPS URL, then run:
  //     npx cap sync android
  // ---------------------------------------------------------------------
  server: {
    // url: "https://inms.desflyer.com",
    androidScheme: "https",
    cleartext: false,
    allowNavigation: [
      // Add any extra domains the app navigates to (e.g. a CDN or a
      // separate reports host). The live site domain is allowed implicitly.
    ],
  },

  android: {
    // The whole app is remote; never mix http content into the https shell.
    allowMixedContent: false,
    captureInput: true,
    webContentsDebuggingEnabled: false,
    backgroundColor: "#0f172a",
  },
};

export default config;
