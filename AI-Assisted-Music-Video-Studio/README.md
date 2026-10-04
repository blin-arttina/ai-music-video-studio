# AI-Assisted Music Studio and Video Generator

**Status:** ACTIVE — Phase 1/2/4 foundation built and working; Phase 3 (AI generation) wired as real, honest integration points; Phase 5 (collaboration) implemented at the data/API level.

An accessible, all-in-one creative studio for music, audio, lyrics, images, animation, and video, with AI assistance, ownership records, watermarking, and content-protection features — running as a web app on the Blind Art Server ecosystem.

## What this app does today

- **Accounts & security** — signs in against the Blind Art Server (no separate password system); every project, text item, and file is tied to the authenticated creator; sessions are server-side and cookie-based.
- **Projects** — new, open, rename, duplicate, delete, backup (ZIP), export-as-ZIP, each in its own organized folder.
- **Media Library** — upload and organize images, audio, music, video, voice, animation, and fonts per project.
- **Lyrics/Notes/Scripts editor with required ownership protection** — every save gets a SHA-256 hash, a timestamp, a version number, a unique content ID, and a server-side ownership record that is never overwritten (a new record is appended on every edit).
- **Image & video watermarking on export** — on by default, cannot be disabled, opacity is clamped so it can't be silently zeroed out; visible creator watermark burned into the exported file (Pillow for images, ffmpeg for video).
- **AI Assistant** — Help Assistant, Lyrics drafting, and Script/Video-plan drafting work today if `ANTHROPIC_API_KEY` is set. AI Music, AI Voice, AI Image, and AI Animation are real API routes that report "not connected" until a generation provider's API key is added — see `configuration/.env.example`. Nothing fakes a result.
- **Collaboration** — project invitations with View/Comment/Edit/Full permissions, and revocation, at the API level (UI for this is a Phase 5 follow-up).
- **Audit log** — records project actions (create, edit, export, delete) for the owner to review.
- **Accessibility** — dark background, large text, high-contrast white text, large tap targets, descriptive labels (not icon-only), skip link, visible focus outlines, keyboard-operable tabs.

## Requirements

- Python 3.10+
- `ffmpeg` on the server for video watermarking (image watermarking needs only Pillow, which is in `requirements.txt`)
- A running Blind Art Server instance to authenticate against
- Optional: `ANTHROPIC_API_KEY` (or another provider's key) to enable AI text assistance/generation modules

## Installation (local)

```bash
cd AI-Assisted-Music-Video-Studio
pip install -r requirements.txt --break-system-packages
cp configuration/.env.example configuration/.env   # then fill in real values
export $(cat configuration/.env | xargs)           # or use python-dotenv / your shell's env loading
export FLASK_ENV=development
python server.py
```

Then open `http://localhost:5000` and sign in with your existing Blind Art Server account.

## Deploying alongside Blind Art Server

See `documentation/DEPLOYMENT.md` — it follows the same Render pattern already used for Blind-Art-Server and BuildYourAppAI.

## Basic usage

1. Sign in with your Blind Art Server account.
2. Create a project from the Main Menu.
3. Inside a project: write and save lyrics/notes/scripts (ownership-protected automatically), upload media to the Media Library, export images/video with the required watermark, and use the AI Assistant tab for drafting help.
4. Back up or export the whole project as a ZIP any time from the Project tab.

See `USER_GUIDE.txt` for complete instructions, and `CONTENT_PROTECTION_GUIDE.txt` for exactly how watermarking and ownership protection work and what they do (and don't) guarantee.

## Icon

Drop your `music.png` into `static/icons/music.png` (create the `icons` folder if it isn't there) and it will appear as the app's icon/favicon automatically — the templates already reference that path.
