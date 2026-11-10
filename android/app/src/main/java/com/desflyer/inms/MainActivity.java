package com.desflyer.inms;

import android.app.DownloadManager;
import android.content.Context;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.webkit.CookieManager;
import android.webkit.URLUtil;
import android.webkit.WebView;

import com.getcapacitor.BridgeActivity;

/**
 * Android shell for the server-rendered DesFlyer-INMS Flask application.
 *
 * The WebView loads the live site (see capacitor.config.ts -> server.url).
 * Two things the plain WebView does not do by itself are handled here:
 *
 *   1. Session cookies - the Flask login session must survive app restarts.
 *   2. File downloads - report PDFs and uploaded documents are served with
 *      Content-Disposition: attachment. A normal WebView ignores those, so the
 *      download is handed to Android's DownloadManager *with the session
 *      cookie attached* (otherwise the server would reject it).
 */
public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Keep the Flask session cookie across app restarts.
        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        cookieManager.setAcceptThirdPartyCookies(getBridge().getWebView(), true);

        installDownloadHandler(getBridge().getWebView());
    }

    private void installDownloadHandler(WebView webView) {
        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            try {
                String fileName = URLUtil.guessFileName(url, contentDisposition, mimeType);

                DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                request.setMimeType(mimeType);
                request.setTitle(fileName);
                request.setDescription("DesFlyer-INMS download");
                request.setNotificationVisibility(
                        DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);
                request.setAllowedOverMetered(true);
                request.setAllowedOverRoaming(false);

                // Reuse the logged-in session; the server requires it.
                String cookie = CookieManager.getInstance().getCookie(url);
                if (cookie != null && !cookie.isEmpty()) {
                    request.addRequestHeader("Cookie", cookie);
                }
                if (userAgent != null && !userAgent.isEmpty()) {
                    request.addRequestHeader("User-Agent", userAgent);
                }

                DownloadManager manager =
                        (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                if (manager != null) {
                    manager.enqueue(request);
                }
            } catch (Exception ignored) {
                // Never crash the app because a download could not be started.
            }
        });
    }
}
