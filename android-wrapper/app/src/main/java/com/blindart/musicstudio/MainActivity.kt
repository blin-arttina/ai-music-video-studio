package com.blindart.musicstudio

import android.app.DownloadManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.util.Log
import android.view.KeyEvent
import android.webkit.CookieManager
import android.webkit.PermissionRequest
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity

/**
 * A thin wrapper that loads the AI-Assisted Music Studio and Video
 * Generator web app in a full-screen WebView, so it can live on your
 * home screen with its own icon like a normal app.
 *
 * ============================================================
 * SET YOUR SERVER ADDRESS HERE -- this is the only line you need to
 * change before building. See README_ANDROID_WRAPPER.txt for details.
 * ============================================================
 */
private const val APP_BASE_URL = "https://REPLACE-WITH-YOUR-SERVER-ADDRESS.example.com"

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null
    private lateinit var fileChooserLauncher: ActivityResultLauncher<Intent>

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // The file chooser needs to be registered before onCreate finishes,
        // so this comes first.
        fileChooserLauncher = registerForActivityResult(
            ActivityResultContracts.StartActivityForResult()
        ) { result ->
            val callback = fileChooserCallback
            fileChooserCallback = null
            if (callback == null) return@registerForActivityResult
            val data = result.data
            val uris: Array<Uri> = if (result.resultCode == RESULT_OK && data != null) {
                val clipData = data.clipData
                if (clipData != null) {
                    Array(clipData.itemCount) { i -> clipData.getItemAt(i).uri }
                } else {
                    val single = data.data
                    if (single != null) arrayOf(single) else emptyArray()
                }
            } else {
                emptyArray()
            }
            callback.onReceiveValue(uris)
        }

        webView = WebView(this)
        setContentView(webView)

        val settings: WebSettings = webView.settings
        settings.javaScriptEnabled = true
        // The Music & Text Studio's crash-recovery drafts and the Studio
        // Branding preview both rely on the browser's own local storage,
        // so this has to be on for the app to work the same as it does in
        // a desktop browser.
        settings.domStorageEnabled = true
        settings.allowFileAccess = true
        settings.mediaPlaybackRequiresUserGesture = false
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest
            ): Boolean {
                // Keep every page of your own app inside this WebView
                // instead of handing it off to an external browser.
                return false
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            // Lets the in-app microphone recorder (Media Library ->
            // Start Recording) actually ask for and use the microphone.
            override fun onPermissionRequest(request: PermissionRequest) {
                runOnUiThread { request.grant(request.resources) }
            }

            // Lets file <input> fields (uploading images/audio/video, or
            // choosing a studio logo) open Android's normal file picker.
            override fun onShowFileChooser(
                webView: WebView,
                filePathCallback: ValueCallback<Array<Uri>>,
                fileChooserParams: FileChooserParams
            ): Boolean {
                fileChooserCallback?.onReceiveValue(null)
                fileChooserCallback = filePathCallback
                val intent = fileChooserParams.createIntent()
                try {
                    fileChooserLauncher.launch(intent)
                } catch (e: Exception) {
                    fileChooserCallback = null
                    return false
                }
                return true
            }
        }

        // Watermarked exports and project ZIP downloads come back as a
        // normal file download, which a plain WebView otherwise silently
        // drops. This hands them to Android's own Download Manager so
        // they land in your device's Downloads folder like any other
        // download, with the notification that lets you open it.
        webView.setDownloadListener { url, _, contentDisposition, mimeType, _ ->
            try {
                val request = DownloadManager.Request(Uri.parse(url))
                val fileName = URLUtil.guessFileName(url, contentDisposition, mimeType)
                request.setMimeType(mimeType)
                request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName)
                request.addRequestHeader("cookie", CookieManager.getInstance().getCookie(url))
                val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
                dm.enqueue(request)
            } catch (e: Exception) {
                Log.e("MusicStudioWrapper", "Download failed to start: ${e.message}")
            }
        }

        webView.loadUrl(APP_BASE_URL)
    }

    // Makes the Android back button/gesture step back through the app's
    // own pages (e.g. out of a project and back to the Main Menu) instead
    // of immediately closing the app.
    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView.canGoBack()) {
            webView.goBack()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }
}
