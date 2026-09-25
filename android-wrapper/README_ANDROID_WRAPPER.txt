ANDROID WEBVIEW WRAPPER -- README
============================================================

WHAT THIS IS
-------------
A small Android app project that shows the AI-Assisted Music Studio and
Video Generator web app full-screen, with its own icon (the same mandala
artwork used everywhere else in this project) on your home screen, so it
feels like a normal app instead of a browser tab. It is not a rewrite of
the app -- it just displays the same web pages your server already
serves, inside a plain Android WebView.

It includes:
  - Your mandala icon at every required size (already generated, nothing
    to do here).
  - The microphone permission the in-app recorder needs.
  - Downloads (watermarked exports, project ZIPs) saved to your device's
    normal Downloads folder, the way they would from a browser.
  - The file picker for uploading images/audio/video or a studio logo.
  - The Android back button/gesture stepping back through the app's own
    pages instead of closing the app.

HONESTY CHECK BEFORE YOU START
--------------------------------
This project was written by hand and could NOT be built or tested in the
sandbox that created it -- there is no Android SDK there, and the network
access needed to download one is blocked. Every file here follows
standard, well-established Android WebView patterns, but this has not
been proven to compile. Build it and fix anything Android Studio (or
Code On The Go) flags before relying on it -- don't skip straight to
installing it on your phone without a successful build first.

------------------------------------------------------------
STEP 1: THE ONE THING YOU MUST CHANGE BEFORE BUILDING
------------------------------------------------------------
This app needs a real web address to load -- it can't load "localhost"
the way a browser on the same computer as the server could, because your
phone is a different device from wherever the server runs.

File to open:
  android-wrapper/app/src/main/java/com/blindart/musicstudio/MainActivity.kt

Find this line near the top (around line 30):
  private const val APP_BASE_URL = "https://REPLACE-WITH-YOUR-SERVER-ADDRESS.example.com"

Replace the whole line with your server's real address in quotes, for
example:
  private const val APP_BASE_URL = "https://your-app-name.onrender.com"

Save the file. That's the only source code change required.

If you don't have a deployed server address yet: this wrapper needs the
Flask app to actually be running somewhere your phone can reach over the
internet (Render is a common free option). See the main README.md and
PROJECT_NOTES.txt in the project's root folder for deployment notes. A
server running only on a computer on your own home network (a plain
local IP address like 192.168.x.x) will only work while your phone is on
that same network.

------------------------------------------------------------
STEP 2: BUILD THE APP
------------------------------------------------------------
Use whichever of these matches how you've built APKs before:

Option A -- Android Studio (on a computer):
  1. Open Android Studio.
  2. Choose "Open" and select the android-wrapper folder (not the whole
     AI-Assisted-Music-Video-Studio folder -- specifically the
     android-wrapper folder inside it).
  3. Let it finish "Gradle Sync" (this downloads a few Android build
     tools the first time -- it needs internet access to do this).
  4. Build > Build Bundle(s) / APK(s) > Build APK(s).
  5. When it finishes, click "locate" in the notification to find the
     built APK file.

Option B -- Code On The Go (directly on your tablet):
  1. Open Code On The Go.
  2. Open the android-wrapper folder as a project.
  3. Let it sync/download the Android Gradle plugin and SDK components
     it needs (first time only -- needs internet access).
  4. Use its Build/Run APK option the same way you have for other
     projects.

Either way, the very first build may take a while and needs internet
access to download standard Android build tools -- that's normal and
only happens once.

------------------------------------------------------------
STEP 3: INSTALL AND TEST
------------------------------------------------------------
Install the built APK on your device (if it's not already there from
Option B above) and open it. Check, in this order:
  1. The app opens and shows the Main Menu (not a blank white screen --
     a blank screen almost always means APP_BASE_URL in Step 1 is wrong
     or the server isn't reachable from your phone).
  2. Sign in with your Blind Art Server account, same as in a browser.
  3. Open a project, try "Start Recording" once -- Android should ask to
     allow microphone access the first time.
  4. Try uploading a file in the Media Library -- the normal Android
     file picker should open.
  5. Try "Export with Watermark" on something small -- check your
     Downloads folder (or the download notification) for the file.
  6. Use the back button/gesture inside a project, then again to
     confirm it steps back through pages sensibly.

If something doesn't work, the most common causes are: APP_BASE_URL
pointing at the wrong address, the server not actually running, or (for
downloads specifically) a very old Android version needing you to accept
a storage permission prompt the first time.

------------------------------------------------------------
CHANGING THINGS LATER
------------------------------------------------------------
- App name shown under the icon: android-wrapper/app/src/main/res/values/strings.xml
- Icon images: android-wrapper/app/src/main/res/mipmap-*/ic_launcher.png
  (already generated from your mandala artwork at every required size --
  regenerate them the same way if you ever change the app icon: resize
  static/icons/music.png to 48/72/96/144/192 pixels square for
  mdpi/hdpi/xhdpi/xxhdpi/xxxhdpi respectively).
- Server address: back to Step 1 above.
- Once your server has a real https:// address, you can remove the line
  android:usesCleartextTraffic="true" from
  android-wrapper/app/src/main/AndroidManifest.xml -- it's only there so
  this can also load a plain http:// address during testing.

WHAT THIS DOES NOT DO
-----------------------
This wrapper doesn't add any feature the web app doesn't already have --
it's the same pages, just in an app frame. It doesn't work offline
(neither does the web app), and it doesn't change anything about how the
server itself works, what it costs to run, or where it's hosted.
