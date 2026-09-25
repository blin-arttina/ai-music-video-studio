"""
Project system: new, open, rename, duplicate, delete, backup (ZIP),
export-as-ZIP, and import-from-ZIP. Each project gets its own organized
folder under projects/, mirroring the top-level app structure at a
smaller scale.

Export/backup ZIPs embed a manifest.json alongside the real media files,
recording every database row that makes up the project (media asset
metadata, saved text + its ownership/version history, and the full
Timeline of tracks and clips) -- not just the files themselves. Without
it, an imported ZIP would just be a pile of files with no project
structure behind them. Import reads that manifest back and recreates
those rows under a brand-new project, so re-importing an exported
project restores a working project rather than an empty shell.
"""

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from config import BASE_DIR, get_config
from source.project.models import (
    Project, MediaAsset, TextContent, TextRevision, OwnershipRecord,
    Track, Clip, db,
)

CONFIG = get_config()

PROJECT_SUBFOLDERS = [
    "audio", "music", "video", "images", "animation", "voice",
    "lyrics", "scripts", "timeline", "exports", "backups",
]

MANIFEST_FORMAT = "ai-music-studio-project-export"
MANIFEST_VERSION = 1


def _safe_folder_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in name.strip())
    return keep or "untitled-project"


def create_project(owner_email: str, name: str, description: str = "") -> Project:
    folder_name = f"{_safe_folder_name(name)}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    project_dir = CONFIG.PROJECTS_DIR / folder_name
    for sub in PROJECT_SUBFOLDERS:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)

    project = Project(
        owner_email=owner_email,
        name=name,
        description=description,
        folder_path=str(project_dir),
    )
    db.session.add(project)
    db.session.commit()
    return project


def rename_project(project: Project, new_name: str) -> Project:
    project.name = new_name
    db.session.commit()
    return project


def duplicate_project(project: Project) -> Project:
    new_proj = create_project(project.owner_email, f"{project.name} (copy)", project.description)
    src = Path(project.folder_path)
    dst = Path(new_proj.folder_path)
    if src.exists():
        for item in src.iterdir():
            target = dst / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
    return new_proj


def delete_project(project: Project, hard: bool = False):
    folder = Path(project.folder_path)
    if hard and folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    db.session.delete(project)
    db.session.commit()


def backup_project(project: Project) -> Path:
    """Creates a timestamped ZIP backup and returns its path."""
    folder = Path(project.folder_path)
    backups_dir = folder / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    zip_path = backups_dir / f"{_safe_folder_name(project.name)}-backup-{stamp}.zip"
    _zip_project(project, zip_path, exclude_dirs={"backups"})
    return zip_path


def export_project_zip(project: Project) -> Path:
    """Exports the complete project as a ZIP archive for download/sharing,
    including a manifest.json of the project's database rows so it can be
    imported back later with its media, text, and Timeline intact."""
    exports_dir = CONFIG.EXPORTS_DIR
    exports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    zip_path = exports_dir / f"{_safe_folder_name(project.name)}-{stamp}.zip"
    _zip_project(project, zip_path)
    return zip_path


def _zip_project(project: Project, zip_path: Path, exclude_dirs=None):
    exclude_dirs = exclude_dirs or set()
    folder = Path(project.folder_path)
    manifest = build_project_manifest(project)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if path.is_dir():
                continue
            if any(part in exclude_dirs for part in path.relative_to(folder).parts):
                continue
            zf.write(path, arcname=str(Path(folder.name) / path.relative_to(folder)))
        zf.writestr(str(Path(folder.name) / "manifest.json"), json.dumps(manifest, indent=2))


def _zip_directory(folder: Path, zip_path: Path, exclude_dirs=None):
    """Kept for anything that just needs a plain folder zipped with no
    manifest (not used by project export/backup anymore -- see _zip_project)."""
    exclude_dirs = exclude_dirs or set()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if path.is_dir():
                continue
            if any(part in exclude_dirs for part in path.relative_to(folder).parts):
                continue
            zf.write(path, arcname=str(Path(folder.name) / path.relative_to(folder)))


# ------------------------------------------------------------------
# Manifest build (export side)
# ------------------------------------------------------------------

def build_project_manifest(project: Project) -> dict:
    folder = Path(project.folder_path)

    media_assets = []
    for a in MediaAsset.query.filter_by(project_id=project.id).all():
        try:
            rel = str(Path(a.storage_path).relative_to(folder))
        except ValueError:
            continue  # file lives outside the project folder somehow -- skip rather than guess
        media_assets.append({
            "relative_path": rel,
            "category": a.category,
            "filename": a.filename,
            "watermarked": a.watermarked,
            "original_hash": a.original_hash,
        })

    text_contents = []
    for t in TextContent.query.filter_by(project_id=project.id).all():
        revisions = [
            {
                "version": r.version,
                "body_hash": r.body_hash,
                "body_snapshot": r.body_snapshot,
                "edited_by": r.edited_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in TextRevision.query.filter_by(text_content_id=t.id).all()
        ]
        text_contents.append({
            "content_id": t.content_id,
            "kind": t.kind,
            "title": t.title,
            "body": t.body,
            "creator_email": t.creator_email,
            "creator_name": t.creator_name,
            "version": t.version,
            "content_hash": t.content_hash,
            "is_private": t.is_private,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "revisions": revisions,
        })

    ownership_records = [
        {
            "content_id": o.content_id,
            "creator_email": o.creator_email,
            "creator_name": o.creator_name,
            "version": o.version,
            "content_hash": o.content_hash,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in OwnershipRecord.query.filter_by(project_id=project.id).all()
    ]

    tracks = []
    for tr in Track.query.filter_by(project_id=project.id).order_by(Track.order_index).all():
        clips = []
        for c in tr.clips:
            asset_rel = None
            if c.media_asset_id and c.media_asset:
                try:
                    asset_rel = str(Path(c.media_asset.storage_path).relative_to(folder))
                except ValueError:
                    asset_rel = None
            text_cid = c.text_content.content_id if c.text_content_id and c.text_content else None
            clips.append({
                "media_asset_relative_path": asset_rel,
                "text_content_id": text_cid,
                "label": c.label,
                "start_seconds": c.start_seconds,
                "duration_seconds": c.duration_seconds,
                "trim_in_seconds": c.trim_in_seconds,
                "trim_out_seconds": c.trim_out_seconds,
                "volume": c.volume,
                "fade_in_seconds": c.fade_in_seconds,
                "fade_out_seconds": c.fade_out_seconds,
                "muted": c.muted,
                "locked": c.locked,
                "eq_low_db": c.eq_low_db,
                "eq_mid_db": c.eq_mid_db,
                "eq_high_db": c.eq_high_db,
                "reverb_amount": c.reverb_amount,
                "echo_amount": c.echo_amount,
                "compression": c.compression,
                "noise_reduction": c.noise_reduction,
                "pitch_semitones": c.pitch_semitones,
                "crop_x": c.crop_x,
                "crop_y": c.crop_y,
                "crop_width": c.crop_width,
                "crop_height": c.crop_height,
                "rotation_degrees": c.rotation_degrees,
                "caption_text": c.caption_text,
                "caption_position": c.caption_position,
            })
        tracks.append({
            "name": tr.name,
            "kind": tr.kind,
            "order_index": tr.order_index,
            "muted": tr.muted,
            "locked": tr.locked,
            "hidden": tr.hidden,
            "clips": clips,
        })

    return {
        "format": MANIFEST_FORMAT,
        "format_version": MANIFEST_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "project": {
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "is_private": project.is_private,
        },
        "media_assets": media_assets,
        "text_contents": text_contents,
        "ownership_records": ownership_records,
        "tracks": tracks,
    }


# ------------------------------------------------------------------
# Import (reverse of the above): given an uploaded ZIP file, extract its
# files into a brand-new project and, when a manifest.json is present,
# recreate the database rows it describes.
# ------------------------------------------------------------------

class ImportError_(Exception):
    """Raised for a ZIP that can't be imported (not our format, corrupt, etc.)."""


def import_project_zip(owner_email: str, zip_file_path) -> Project:
    import tempfile

    zip_file_path = Path(zip_file_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        try:
            with zipfile.ZipFile(zip_file_path) as zf:
                zf.extractall(tmp_path)
        except zipfile.BadZipFile:
            raise ImportError_("that file isn't a valid ZIP archive")

        entries = list(tmp_path.iterdir())
        root = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp_path

        manifest = None
        manifest_path = root / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError):
                manifest = None

        if manifest and manifest.get("project", {}).get("name"):
            base_name = manifest["project"]["name"]
            description = manifest["project"].get("description", "")
        else:
            base_name = zip_file_path.stem
            description = ""

        new_proj = create_project(owner_email, f"{base_name} (imported)", description)
        if manifest:
            new_proj.status = manifest["project"].get("status", "ACTIVE")
            new_proj.is_private = manifest["project"].get("is_private", True)
            db.session.commit()

        dest_folder = Path(new_proj.folder_path)
        for path in root.rglob("*"):
            if path.is_dir():
                continue
            if path.parent == root and path.name == "manifest.json":
                continue
            rel = path.relative_to(root)
            target = dest_folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

        if not manifest:
            # A plain ZIP with no manifest -- files are copied in, but there's
            # no way to know what media/text/timeline rows to recreate, so
            # the project comes back as files only (matching what an older,
            # manifest-less export would have contained).
            return new_proj

        asset_map = {}
        for a in manifest.get("media_assets", []):
            rel_path = a.get("relative_path")
            if not rel_path:
                continue
            storage_path = dest_folder / rel_path
            if not storage_path.exists():
                continue  # referenced file missing from the ZIP -- skip rather than create a dangling record
            asset = MediaAsset(
                project_id=new_proj.id,
                category=a.get("category", "image"),
                filename=a.get("filename", storage_path.name),
                storage_path=str(storage_path),
                watermarked=a.get("watermarked", False),
                original_hash=a.get("original_hash"),
            )
            db.session.add(asset)
            db.session.flush()
            asset_map[rel_path] = asset

        text_map = {}
        for t in manifest.get("text_contents", []):
            tc = TextContent(
                project_id=new_proj.id,
                content_id=t.get("content_id"),
                kind=t.get("kind", "note"),
                title=t.get("title", "Untitled"),
                body=t.get("body", ""),
                creator_email=t.get("creator_email", owner_email),
                creator_name=t.get("creator_name", ""),
                version=t.get("version", 1),
                content_hash=t.get("content_hash"),
                is_private=t.get("is_private", True),
            )
            db.session.add(tc)
            db.session.flush()
            text_map[t.get("content_id")] = tc
            for rev in t.get("revisions", []):
                db.session.add(TextRevision(
                    text_content_id=tc.id,
                    version=rev.get("version", 1),
                    body_hash=rev.get("body_hash"),
                    body_snapshot=rev.get("body_snapshot"),
                    edited_by=rev.get("edited_by"),
                ))

        for o in manifest.get("ownership_records", []):
            db.session.add(OwnershipRecord(
                content_id=o.get("content_id"),
                project_id=new_proj.id,
                creator_email=o.get("creator_email", owner_email),
                creator_name=o.get("creator_name"),
                project_name=new_proj.name,
                version=o.get("version", 1),
                content_hash=o.get("content_hash", ""),
            ))

        for t in manifest.get("tracks", []):
            track = Track(
                project_id=new_proj.id,
                name=t.get("name", "Track"),
                kind=t.get("kind", "audio"),
                order_index=t.get("order_index", 0),
                muted=t.get("muted", False),
                locked=t.get("locked", False),
                hidden=t.get("hidden", False),
            )
            db.session.add(track)
            db.session.flush()
            for c in t.get("clips", []):
                asset = asset_map.get(c.get("media_asset_relative_path"))
                text = text_map.get(c.get("text_content_id"))
                db.session.add(Clip(
                    track_id=track.id,
                    media_asset_id=asset.id if asset else None,
                    text_content_id=text.id if text else None,
                    label=c.get("label", "Clip"),
                    start_seconds=c.get("start_seconds", 0.0),
                    duration_seconds=c.get("duration_seconds", 5.0),
                    trim_in_seconds=c.get("trim_in_seconds", 0.0),
                    trim_out_seconds=c.get("trim_out_seconds"),
                    volume=c.get("volume", 1.0),
                    fade_in_seconds=c.get("fade_in_seconds", 0.0),
                    fade_out_seconds=c.get("fade_out_seconds", 0.0),
                    muted=c.get("muted", False),
                    locked=c.get("locked", False),
                    eq_low_db=c.get("eq_low_db", 0.0),
                    eq_mid_db=c.get("eq_mid_db", 0.0),
                    eq_high_db=c.get("eq_high_db", 0.0),
                    reverb_amount=c.get("reverb_amount", 0.0),
                    echo_amount=c.get("echo_amount", 0.0),
                    compression=c.get("compression", 0.0),
                    noise_reduction=c.get("noise_reduction", 0.0),
                    pitch_semitones=c.get("pitch_semitones", 0.0),
                    crop_x=c.get("crop_x", 0.0),
                    crop_y=c.get("crop_y", 0.0),
                    crop_width=c.get("crop_width", 1.0),
                    crop_height=c.get("crop_height", 1.0),
                    rotation_degrees=c.get("rotation_degrees", 0),
                    caption_text=c.get("caption_text", ""),
                    caption_position=c.get("caption_position", "bottom"),
                ))

        db.session.commit()
        return new_proj
