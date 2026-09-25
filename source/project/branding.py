"""
Studio branding: a creator's own studio/label name and logo, saved once
and reused as the default watermark on every one of their projects,
rather than retyping a name and re-uploading a logo project by project.

This is deliberately account-wide (keyed by the Blind Art Server email,
via StudioBrand), not per-project -- a creator's brand doesn't change
per project, and this is what the user asked for: "put on all finished
projects."

Storage lives outside any single project's folder, under
CONFIG.BASE_DIR / "studio_brands" / <safe email> / logo.<ext>, since a
brand isn't owned by any one project and must survive that project
being deleted.
"""

import hashlib
import re
from pathlib import Path

from config import BASE_DIR, get_config
from source.project.models import db, StudioBrand

CONFIG = get_config()

MAX_LOGO_DIMENSION = 1024  # logos are resized down to this on upload -- plenty for a watermark


def _safe_email_folder(email: str) -> str:
    # Emails contain characters that aren't safe/portable as folder names
    # on every filesystem (the "@"), so use a short stable hash instead
    # of trying to sanitize the address itself.
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:24]
    return digest


def _brand_dir(owner_email: str) -> Path:
    d = BASE_DIR / "studio_brands" / _safe_email_folder(owner_email)
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_brand(owner_email: str) -> StudioBrand:
    return StudioBrand.query.filter_by(owner_email=owner_email).first()


def get_or_create_brand(owner_email: str) -> StudioBrand:
    brand = get_brand(owner_email)
    if not brand:
        brand = StudioBrand(owner_email=owner_email, studio_name="")
        db.session.add(brand)
        db.session.commit()
    return brand


def set_studio_name(owner_email: str, studio_name: str) -> StudioBrand:
    brand = get_or_create_brand(owner_email)
    brand.studio_name = (studio_name or "").strip()[:200]
    db.session.commit()
    return brand


def save_logo(owner_email: str, file_storage, allowed_ext: set) -> StudioBrand:
    """
    Saves an uploaded logo image for this creator, replacing any
    previous one. Resizes down (never up) to MAX_LOGO_DIMENSION on the
    longer side so an oversized upload doesn't balloon every export.
    `file_storage` is a Werkzeug FileStorage (the same kind media
    uploads already use).
    """
    from PIL import Image  # local import: keeps Pillow's cost off every
                            # branding.py import, only paid when actually
                            # saving a logo.

    filename = file_storage.filename or "logo"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed_ext:
        raise ValueError(f"Unsupported logo file type: .{ext or '?'}")

    brand = get_or_create_brand(owner_email)
    brand_dir = _brand_dir(owner_email)

    # Clear any previous logo file (a different extension than the new
    # one would otherwise be left behind alongside it).
    if brand.logo_storage_path and Path(brand.logo_storage_path).exists():
        Path(brand.logo_storage_path).unlink()

    dest_path = brand_dir / f"logo.{ext}"
    file_storage.save(str(dest_path))

    # Normalize to RGBA and cap the size so it can't be an oversized
    # multi-megapixel file that slows down every watermark it's used in.
    try:
        img = Image.open(dest_path).convert("RGBA")
        longer_side = max(img.size)
        if longer_side > MAX_LOGO_DIMENSION:
            scale = MAX_LOGO_DIMENSION / longer_side
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
        img.save(dest_path)
    except Exception:
        # If Pillow can't touch it for some reason, keep the raw upload
        # rather than losing the file -- watermarking will simply fail
        # clearly later if it truly isn't a valid image.
        pass

    brand.logo_filename = filename
    brand.logo_storage_path = str(dest_path)
    db.session.commit()
    return brand


def clear_logo(owner_email: str) -> StudioBrand:
    brand = get_or_create_brand(owner_email)
    if brand.logo_storage_path and Path(brand.logo_storage_path).exists():
        Path(brand.logo_storage_path).unlink()
    brand.logo_filename = None
    brand.logo_storage_path = None
    db.session.commit()
    return brand
