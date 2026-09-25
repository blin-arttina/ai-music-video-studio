# Deploying to Render (Blind Art Server pattern)

This follows the same steps already used for `Blind-Art-Server` and
`BuildYourAppAI`, so it fits straight into your existing workflow.

## 1. Push to GitHub

From the tablet (Termux), the same way as your other projects:

```bash
cd ~/storage/shared/AI-Assisted-Music-Video-Studio
git init
git add .
git commit -m "Initial commit: AI-Assisted Music Studio and Video Generator"
git branch -M main
git remote add origin https://github.com/blin-arttina/AI-Assisted-Music-Video-Studio.git
git push -u origin main
```

(Create the empty GitHub repo first at github.com/new under blin-arttina, same as before. Keep it public if Render's free tier gives an "unfetchable URL" error, as happened with Blind-Art-Server.)

## 2. Create the Render web service

1. In Render: New → Web Service → connect the new GitHub repo.
2. Environment: Python 3.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn server:app`
5. Add environment variables (Render → your service → Environment):
   - `SECRET_KEY` — any long random string
   - `BLIND_ART_SERVER_URL` — `https://blind-art-server.onrender.com`
   - `DATABASE_URL` — a Render Postgres connection string (recommended for
     production instead of the default SQLite file, which won't
     persist across deploys on Render's free tier)
   - `ANTHROPIC_API_KEY` — optional, enables AI Lyrics/Script/Help
   - Any of `AI_MUSIC_PROVIDER_API_KEY`, `AI_VOICE_PROVIDER_API_KEY`,
     `AI_IMAGE_PROVIDER_API_KEY`, `AI_VIDEO_PROVIDER_API_KEY` — optional,
     only if/when you connect a generation provider

## 3. ffmpeg for video watermarking

Render's standard Python runtime does not include ffmpeg by default.
Two options:
- Add a `render-build.sh` that installs ffmpeg via apt during build
  (Render's native runtime allows `apt-get` in the build step on some
  plans), or
- Switch this service to a Docker-based Render deploy and install
  ffmpeg in the Dockerfile (`apt-get install -y ffmpeg`).

Until ffmpeg is available, image watermarking works normally; video
export will return a clear "ffmpeg is not installed" error instead of
silently skipping the watermark.

## 4. Persistent storage

Render's free-tier filesystem is ephemeral — uploaded media and
per-project folders will NOT survive a redeploy unless you attach a
Render Disk (persistent volume) to this service, the same
consideration that applies to any file-storage-heavy Blind Art app.
For production use, attach a disk and point `PROJECTS_DIR` /
`EXPORTS_DIR` at a path under it, or migrate media storage to Blind
Art Server's own cloud storage once that's available there.

## 5. Confirm it's live

```
GET https://<your-service>.onrender.com/health
```
should return `{"status": "ok", "app": "AI-Assisted Music Studio and Video Generator"}`.

Then sign in from the browser with your existing Blind Art Server
account.
