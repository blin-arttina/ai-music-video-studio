"""
Configuration for the AI-Assisted Music Studio and Video Generator.

All secrets are read from environment variables. Nothing sensitive is
hard-coded here. On Render (or any host), set these in the service's
Environment settings.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Everything the app actually needs to keep -- the database file and every
# project's saved media/text/exports -- lives under DATA_DIR rather than
# next to the app's own code. On a plain Render web service (no persistent
# disk attached), this defaults to BASE_DIR, which sits on temporary storage
# that Render can wipe on a restart or redeploy -- fine for local use, but
# not safe for real projects once this is deployed. Setting the DATA_DIR
# environment variable to a Render persistent disk's mount path (e.g.
# /var/data, once a disk is attached to this service) makes projects survive
# restarts and redeploys instead of disappearing.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))


class Config:
    # --- Core app ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    APP_NAME = "AI-Assisted Music Studio and Video Generator"

    # --- Local storage (per-project folders live under here) ---
    PROJECTS_DIR = DATA_DIR / "projects"
    ASSETS_DIR = DATA_DIR / "assets"
    EXPORTS_DIR = DATA_DIR / "exports"
    BACKUPS_DIR = DATA_DIR / "backups"
    PROTECTION_DIR = DATA_DIR / "protection"

    # --- Database (local project/user index) ---
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DATA_DIR / 'studio.db'}"
    )
    # Render gives postgres:// but SQLAlchemy needs postgresql://
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1
        )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Local single-user access (no account system) ---
    # This app has no sign-in of its own and no longer authenticates against
    # the Blind Art Server or any other account system. It's reached only by
    # people who have its address, and every visitor is treated as this one
    # local "creator" account, which just labels rows in this app's own
    # local database (nothing is sent anywhere).
    DEFAULT_OWNER_EMAIL = os.environ.get("DEFAULT_OWNER_EMAIL", "creator@music-video-studio.local")
    DEFAULT_OWNER_NAME = os.environ.get("DEFAULT_OWNER_NAME", "Creator")

    # --- Upload limits ---
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "500")) * 1024 * 1024
    ALLOWED_AUDIO_EXT = {"mp3", "wav", "ogg", "m4a", "flac", "aac", "webm"}  # webm covers browser MediaRecorder output
    ALLOWED_VIDEO_EXT = {"mp4", "mov", "webm", "mkv", "avi"}
    ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
    ALLOWED_FONT_EXT = {"ttf", "otf"}
    ALLOWED_TEXT_EXT = {"txt", "md", "srt", "json"}
    ALLOWED_ARCHIVE_EXT = {"zip"}

    # --- Content protection (required, on by default, cannot be disabled) ---
    # These two flags exist only so the code has a single named place that
    # documents the requirement. They are intentionally not exposed in any
    # settings UI or API payload as something a user can flip off.
    WATERMARK_REQUIRED_DEFAULT = True
    TEXT_OWNERSHIP_REQUIRED_DEFAULT = True
    DEFAULT_WATERMARK_TEXT = os.environ.get("DEFAULT_WATERMARK_TEXT", "")  # falls back to creator name
    DEFAULT_WATERMARK_POSITION = "corner"  # corner | center | tiled
    DEFAULT_WATERMARK_OPACITY = 0.55
    MIN_WATERMARK_OPACITY = 0.25  # floor so it can never be made invisible
    MAX_WATERMARK_OPACITY = 0.85  # ceiling so "size/opacity controls" can't hide it at 0 or blot the frame at 1

    # --- AI module integrations (all optional; unset = "not connected") ---
    AI_MUSIC_PROVIDER_API_KEY = os.environ.get("AI_MUSIC_PROVIDER_API_KEY")
    AI_IMAGE_PROVIDER_API_KEY = os.environ.get("AI_IMAGE_PROVIDER_API_KEY")
    AI_VIDEO_PROVIDER_API_KEY = os.environ.get("AI_VIDEO_PROVIDER_API_KEY")
    AI_TEXT_PROVIDER_API_KEY = os.environ.get("AI_TEXT_PROVIDER_API_KEY")  # lyrics/scripts/assistant

    # --- AI Voice: self-hosted Chatterbox (resemble-ai/chatterbox), not a
    # paid API -- no account or key needed, just the chatterbox-tts package
    # (and PyTorch) installed on whatever server actually runs this app.
    # See source/ai/modules.py generate_voice() and PROJECT_NOTES.txt for
    # install/setup instructions. ---
    CHATTERBOX_DEVICE = os.environ.get("CHATTERBOX_DEVICE", "cpu")  # "cpu" or "cuda"
    CHATTERBOX_NANO = os.environ.get("CHATTERBOX_NANO", "true").strip().lower() != "false"


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


def get_config():
    env = os.environ.get("FLASK_ENV", "production")
    return DevelopmentConfig if env == "development" else ProductionConfig
