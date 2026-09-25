"""
Downloadable Asset & Template Library (spec section 23).

Two kinds of library item:
  - "project_template": a starter arrangement (a small set of Track rows,
    described as data) that gets created fresh inside a project the user
    already owns or can edit. No files are involved.
  - "media_asset": an actual bundled file that gets copied into a
    project's Media Library as a new MediaAsset, exactly like an upload.

Every seeded item here is either:
  - a project template (pure data, no third-party content at all), or
  - an originally-generated placeholder file made by this app itself
    with ffmpeg (simple tones/chimes) or Pillow (gradient backgrounds) --
    never third-party stock. See seed_library() / _generate_placeholder_*.

Paid items are supported in the data model (is_free, price_usd) but this
app has no payment provider connected. Rather than fake an unlock, paid
items are reported the same honest way an unconnected AI provider is
reported elsewhere in this app: a plain "purchasing isn't connected yet"
message, never free access and never a fabricated charge.
"""

import json
import shutil
import subprocess
import uuid
from pathlib import Path

from config import BASE_DIR, get_config
from source.project.models import db, LibraryItem, MediaAsset, Track

CONFIG = get_config()

LIBRARY_ASSETS_DIR = BASE_DIR / "assets" / "library"


class PurchaseNotConnectedError(Exception):
    """Raised when a paid library item is requested but no payment
    provider is connected. The item is never granted for free."""


def list_library_items():
    return LibraryItem.query.order_by(LibraryItem.kind, LibraryItem.title).all()


def get_library_item(item_id):
    return LibraryItem.query.get(item_id)


# ------------------------------------------------------------------
# Applying a project template: create real Track/Clip rows from the
# item's stored template_data (a list of tracks, each with a kind/name
# and an empty clip list -- clips reference real media, which the
# library can't supply, so templates seed structure, not content).
# ------------------------------------------------------------------

def apply_project_template(item: LibraryItem, project) -> list:
    if item.kind != "project_template":
        raise ValueError("this library item is not a project template")
    if not item.is_free:
        raise PurchaseNotConnectedError(
            "Purchasing isn't connected yet, so paid templates can't be applied. "
            "This template needs a payment provider account/API key to be set up first."
        )
    data = json.loads(item.template_data_json or "[]")
    existing_max = db.session.query(db.func.max(Track.order_index)).filter_by(
        project_id=project.id
    ).scalar() or 0
    created = []
    for i, track_spec in enumerate(data):
        track = Track(
            project_id=project.id,
            name=track_spec.get("name", "New Track"),
            kind=track_spec.get("kind", "audio"),
            order_index=existing_max + i + 1,
        )
        db.session.add(track)
        created.append(track)
    db.session.commit()
    return created


# ------------------------------------------------------------------
# Importing a bundled media asset into a project's Media Library.
# ------------------------------------------------------------------

def copy_media_asset_to_project(item: LibraryItem, project) -> MediaAsset:
    if item.kind != "media_asset":
        raise ValueError("this library item is not a media asset")
    if not item.is_free:
        raise PurchaseNotConnectedError(
            "Purchasing isn't connected yet, so paid assets can't be imported. "
            "This asset needs a payment provider account/API key to be set up first."
        )
    src = Path(item.file_path)
    if not src.exists():
        raise FileNotFoundError(f"library asset file is missing on the server: {src}")

    category = item.file_category or "audio"
    dest_dir = Path(project.folder_path) / _category_folder(category)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{uuid.uuid4().hex}-{src.name}"
    shutil.copyfile(src, dest_path)

    import hashlib
    file_hash = hashlib.sha256(dest_path.read_bytes()).hexdigest()
    asset = MediaAsset(
        project_id=project.id, category=category, filename=src.name,
        storage_path=str(dest_path), original_hash=file_hash,
    )
    db.session.add(asset)
    db.session.commit()
    return asset


def _category_folder(category: str) -> str:
    return {
        "image": "images", "audio": "audio", "music": "music", "video": "video",
        "voice": "voice", "animation": "animation", "font": "fonts",
    }.get(category, "images")


# ------------------------------------------------------------------
# Seeding: create the built-in free items once, generating their
# placeholder files with ffmpeg/Pillow if they don't already exist.
# ------------------------------------------------------------------

PROJECT_TEMPLATES = [
    {
        "category": "song",
        "title": "Song with Vocals + Instrumental",
        "description": "A starter arrangement with separate tracks for lead vocals, "
                        "backing instrumental, and lyrics -- ready for you to add your own clips.",
        "tracks": [
            {"kind": "vocals", "name": "Lead Vocals"},
            {"kind": "music", "name": "Instrumental"},
            {"kind": "lyrics", "name": "Lyrics"},
        ],
    },
    {
        "category": "video_project",
        "title": "Narrated Video",
        "description": "A starter arrangement for a narrated video: a video track, "
                        "a narration track, background music, and text captions.",
        "tracks": [
            {"kind": "video", "name": "Video"},
            {"kind": "dialogue", "name": "Narration"},
            {"kind": "music", "name": "Background Music"},
            {"kind": "text", "name": "Captions"},
        ],
    },
    {
        "category": "podcast",
        "title": "Two-Voice Podcast",
        "description": "A starter arrangement for a two-person conversation: two "
                        "dialogue tracks plus an intro/outro music track.",
        "tracks": [
            {"kind": "dialogue", "name": "Speaker 1"},
            {"kind": "dialogue", "name": "Speaker 2"},
            {"kind": "music", "name": "Intro / Outro Music"},
        ],
    },
]

# Simple originally-generated placeholder audio tones (ffmpeg's built-in
# sine generator -- no third-party recordings involved).
PLACEHOLDER_TONES = [
    {"title": "Soft Chime (A4)", "freq": 440, "duration": 2.5, "filename": "chime_a4.wav"},
    {"title": "Deep Tone (A2)", "freq": 110, "duration": 3.0, "filename": "tone_a2.wav"},
    {"title": "Bright Ping (A5)", "freq": 880, "duration": 1.5, "filename": "ping_a5.wav"},
]

# Simple originally-generated gradient background images (Pillow).
PLACEHOLDER_GRADIENTS = [
    {"title": "Blue-Purple Gradient Background", "colors": ((20, 30, 90), (110, 40, 150)), "filename": "gradient_blue_purple.png"},
    {"title": "Warm Sunset Gradient Background", "colors": ((90, 30, 10), (230, 140, 40)), "filename": "gradient_sunset.png"},
    {"title": "Dark Teal Gradient Background", "colors": ((5, 25, 30), (20, 90, 100)), "filename": "gradient_teal.png"},
]


def _generate_placeholder_tone(path: Path, freq: float, duration: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={duration}",
        "-af", "afade=t=in:d=0.15,afade=t=out:st={:.2f}:d=0.3".format(max(duration - 0.3, 0)),
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _generate_placeholder_gradient(path: Path, top_color, bottom_color, size=(1280, 720)):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    img = Image.new("RGB", size)
    pixels = img.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        for x in range(width):
            pixels[x, y] = (r, g, b)
    img.save(path)


def seed_library():
    """Idempotent: only creates items if the table is currently empty,
    so re-running this on every startup never duplicates rows."""
    if LibraryItem.query.first() is not None:
        return

    for spec in PROJECT_TEMPLATES:
        item = LibraryItem(
            kind="project_template",
            category=spec["category"],
            title=spec["title"],
            description=spec["description"],
            is_free=True,
            price_usd=None,
            template_data_json=json.dumps(spec["tracks"]),
        )
        db.session.add(item)

    audio_dir = LIBRARY_ASSETS_DIR / "audio"
    for tone in PLACEHOLDER_TONES:
        dest = audio_dir / tone["filename"]
        if not dest.exists():
            try:
                _generate_placeholder_tone(dest, tone["freq"], tone["duration"])
            except Exception:
                continue  # ffmpeg unavailable in this environment -- skip, don't crash startup
        if dest.exists():
            item = LibraryItem(
                kind="media_asset",
                category="audio",
                title=tone["title"],
                description=f"A short, originally-generated {tone['freq']} Hz tone you can use "
                             "as a placeholder sound effect or chime.",
                is_free=True,
                price_usd=None,
                file_path=str(dest),
                file_category="audio",
            )
            db.session.add(item)

    image_dir = LIBRARY_ASSETS_DIR / "images"
    for grad in PLACEHOLDER_GRADIENTS:
        dest = image_dir / grad["filename"]
        if not dest.exists():
            try:
                _generate_placeholder_gradient(dest, grad["colors"][0], grad["colors"][1])
            except Exception:
                continue  # Pillow unavailable -- skip, don't crash startup
        if dest.exists():
            item = LibraryItem(
                kind="media_asset",
                category="image",
                title=grad["title"],
                description="An originally-generated gradient background image, "
                             "ready to use behind titles, lyrics, or captions.",
                is_free=True,
                price_usd=None,
                file_path=str(dest),
                file_category="image",
            )
            db.session.add(item)

    db.session.commit()
