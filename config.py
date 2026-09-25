"""
Configuration for the AI-Assisted Music Studio and Video Generator.

All secrets are read from environment variables. Nothing sensitive is
hard-coded here. On Render (or any host), set these in the service's
Environment settings.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    # --- Core app ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    APP_NAME = "AI-Assisted Music Studio and Video Generator"

    # --- Local storage (per-project folders live under here) ---
    PROJECTS_DIR = BASE_DIR / "projects"
    ASSETS_DIR = BASE_DIR / "assets"
    EXPORTS_DIR = BASE_DIR / "exports"
    BACKUPS_DIR = BASE_DIR / "backups"
    PROTECTION_DIR = BASE_DIR / "protection"

    # --- Database (local project/user index) ---
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'studio.db'}"
    )
    # Render gives postgres:// but SQLAlchemy needs postgresql://
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1
        )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Blind Art Server integration ---
    # This app authenticates its users against the central Blind Art Server
    # (accounts, JWT auth) instead of keeping its own separate user system.
    BLIND_ART_SERVER_URL = os.environ.get(
        "BLIND_ART_SERVER_URL", "https://blind-art-server.onrender.com"
    )
    BLIND_ART_SERVER_TIMEOUT = int(os.environ.get("BLIND_ART_SERVER_TIMEOUT", "120"))

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
    AI_VOICE_PROVIDER_API_KEY = os.environ.get("AI_VOICE_PROVIDER_API_KEY")  # e.g. ElevenLabs
    AI_IMAGE_PROVIDER_API_KEY = os.environ.get("AI_IMAGE_PROVIDER_API_KEY")
    AI_VIDEO_PROVIDER_API_KEY = os.environ.get("AI_VIDEO_PROVIDER_API_KEY")
    AI_TEXT_PROVIDER_API_KEY = os.environ.get("AI_TEXT_PROVIDER_API_KEY")  # lyrics/scripts/assistant


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


def get_config():
    env = os.environ.get("FLASK_ENV", "production")
    return DevelopmentConfig if env == "development" else ProductionConfig
