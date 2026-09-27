"""
Database models for the AI-Assisted Music Studio and Video Generator.

Users themselves are NOT stored here — that's the Blind Art Server's job.
Only the JWT-verified Blind Art user id/email is kept, so every row in
this app can be tied back to a real, authenticated creator.
"""

import uuid
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def new_id() -> str:
    return uuid.uuid4().hex


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    owner_email = db.Column(db.String(255), nullable=False, index=True)  # from Blind Art Server auth
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(20), default="ACTIVE")  # ACTIVE, PLANNED, COMPLETED, DISCONTINUED
    is_private = db.Column(db.Boolean, default=True)
    folder_path = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    media_assets = db.relationship("MediaAsset", backref="project", cascade="all, delete-orphan")
    text_contents = db.relationship("TextContent", backref="project", cascade="all, delete-orphan")
    collaborators = db.relationship("Collaborator", backref="project", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "is_private": self.is_private,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MediaAsset(db.Model):
    __tablename__ = "media_assets"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    project_id = db.Column(db.String(32), db.ForeignKey("projects.id"), nullable=False)
    category = db.Column(db.String(30), nullable=False)  # image, audio, music, video, voice, animation, font, effect
    filename = db.Column(db.String(300), nullable=False)
    storage_path = db.Column(db.String(600), nullable=False)
    watermarked = db.Column(db.Boolean, default=False)
    original_hash = db.Column(db.String(128))  # sha256 of the file at import time
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "filename": self.filename,
            "watermarked": self.watermarked,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


class TextContent(db.Model):
    """Lyrics, notes, scripts, poems, captions — protected creator text."""
    __tablename__ = "text_contents"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    project_id = db.Column(db.String(32), db.ForeignKey("projects.id"), nullable=False)
    content_id = db.Column(db.String(64), unique=True, nullable=False)  # ownership content ID
    kind = db.Column(db.String(30), default="lyrics")  # lyrics, note, script, poem, caption, dialogue, narration
    title = db.Column(db.String(200), default="Untitled")
    body = db.Column(db.Text, default="")
    creator_email = db.Column(db.String(255), nullable=False)
    creator_name = db.Column(db.String(200), default="")
    version = db.Column(db.Integer, default=1)
    content_hash = db.Column(db.String(128))  # sha256 of `body` at current version
    is_private = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    revisions = db.relationship("TextRevision", backref="text_content", cascade="all, delete-orphan")

    def to_dict(self, include_body=True):
        d = {
            "id": self.id,
            "content_id": self.content_id,
            "kind": self.kind,
            "title": self.title,
            "creator_name": self.creator_name,
            "version": self.version,
            "content_hash": self.content_hash,
            "is_private": self.is_private,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_body:
            d["body"] = self.body
        return d


class TextRevision(db.Model):
    """One immutable snapshot per saved version, for revision history / audit."""
    __tablename__ = "text_revisions"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    text_content_id = db.Column(db.String(32), db.ForeignKey("text_contents.id"), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    body_hash = db.Column(db.String(128), nullable=False)
    body_snapshot = db.Column(db.Text)  # full snapshot so "restore previous version" works
    edited_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "version": self.version,
            "body_hash": self.body_hash,
            "edited_by": self.edited_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class OwnershipRecord(db.Model):
    """
    Server-side ownership record for a TextContent, protected against
    unauthorized modification: once written, a row is never updated in
    place — a change creates a new record, so history can't be rewritten.
    """
    __tablename__ = "ownership_records"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    content_id = db.Column(db.String(64), nullable=False, index=True)
    project_id = db.Column(db.String(32), nullable=False)
    creator_email = db.Column(db.String(255), nullable=False)
    creator_name = db.Column(db.String(200))
    project_name = db.Column(db.String(200))
    version = db.Column(db.Integer, nullable=False)
    content_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "content_id": self.content_id,
            "project_name": self.project_name,
            "creator_name": self.creator_name,
            "version": self.version,
            "content_hash": self.content_hash,
            "recorded_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLogEntry(db.Model):
    """Access/export audit trail, kept 'where practical' per the spec."""
    __tablename__ = "audit_log"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    project_id = db.Column(db.String(32), nullable=False, index=True)
    actor_email = db.Column(db.String(255), nullable=False)
    action = db.Column(db.String(100), nullable=False)  # e.g. "export_text", "view_lyrics", "export_video"
    detail = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "action": self.action,
            "detail": self.detail,
            "actor_email": self.actor_email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Track(db.Model):
    """A single lane on the multi-track timeline (music, vocals, dialogue,
    sound effects, images, video, animation, text, lyrics, AI-generated)."""
    __tablename__ = "tracks"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    project_id = db.Column(db.String(32), db.ForeignKey("projects.id"), nullable=False)
    name = db.Column(db.String(200), default="New Track")
    kind = db.Column(db.String(30), default="audio")  # music, vocals, dialogue, sfx, image, video, animation, text, lyrics, ai
    order_index = db.Column(db.Integer, default=0)
    muted = db.Column(db.Boolean, default=False)
    locked = db.Column(db.Boolean, default=False)
    hidden = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    clips = db.relationship("Clip", backref="track", cascade="all, delete-orphan",
                             order_by="Clip.start_seconds")
    project = db.relationship("Project", backref=db.backref("tracks", cascade="all, delete-orphan"))

    def to_dict(self, include_clips=True):
        d = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "order_index": self.order_index,
            "muted": self.muted,
            "locked": self.locked,
            "hidden": self.hidden,
        }
        if include_clips:
            d["clips"] = [c.to_dict() for c in self.clips]
        return d


class Clip(db.Model):
    """One piece of media (or text) placed on a track's timeline."""
    __tablename__ = "clips"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    track_id = db.Column(db.String(32), db.ForeignKey("tracks.id"), nullable=False)
    media_asset_id = db.Column(db.String(32), db.ForeignKey("media_assets.id"), nullable=True)
    text_content_id = db.Column(db.String(32), db.ForeignKey("text_contents.id"), nullable=True)
    label = db.Column(db.String(200), default="Clip")
    start_seconds = db.Column(db.Float, default=0.0)
    duration_seconds = db.Column(db.Float, default=5.0)
    trim_in_seconds = db.Column(db.Float, default=0.0)   # offset into the source media where playback starts
    trim_out_seconds = db.Column(db.Float, nullable=True)  # offset into the source media where playback ends
    volume = db.Column(db.Float, default=1.0)
    fade_in_seconds = db.Column(db.Float, default=0.0)
    fade_out_seconds = db.Column(db.Float, default=0.0)
    muted = db.Column(db.Boolean, default=False)
    locked = db.Column(db.Boolean, default=False)

    # Audio effects (spec §5) — all optional, all default to a no-op.
    eq_low_db = db.Column(db.Float, default=0.0)
    eq_mid_db = db.Column(db.Float, default=0.0)
    eq_high_db = db.Column(db.Float, default=0.0)
    reverb_amount = db.Column(db.Float, default=0.0)     # 0.0-1.0
    echo_amount = db.Column(db.Float, default=0.0)       # 0.0-1.0
    compression = db.Column(db.Float, default=0.0)       # 0.0-1.0
    noise_reduction = db.Column(db.Float, default=0.0)   # 0.0-1.0
    pitch_semitones = db.Column(db.Float, default=0.0)   # -12 to +12

    # Video effects (spec §7) — all optional, all default to a no-op.
    crop_x = db.Column(db.Float, default=0.0)       # fraction of frame width, 0.0-1.0
    crop_y = db.Column(db.Float, default=0.0)       # fraction of frame height, 0.0-1.0
    crop_width = db.Column(db.Float, default=1.0)   # fraction of frame width, 0.05-1.0
    crop_height = db.Column(db.Float, default=1.0)  # fraction of frame height, 0.05-1.0
    rotation_degrees = db.Column(db.Integer, default=0)  # 0, 90, 180, or 270
    caption_text = db.Column(db.String(300), default="")
    caption_position = db.Column(db.String(10), default="bottom")  # top, center, bottom

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    media_asset = db.relationship("MediaAsset")
    text_content = db.relationship("TextContent")

    def to_dict(self):
        return {
            "id": self.id,
            "track_id": self.track_id,
            "media_asset_id": self.media_asset_id,
            "text_content_id": self.text_content_id,
            "label": self.label,
            "start_seconds": self.start_seconds,
            "duration_seconds": self.duration_seconds,
            "trim_in_seconds": self.trim_in_seconds,
            "trim_out_seconds": self.trim_out_seconds,
            "volume": self.volume,
            "fade_in_seconds": self.fade_in_seconds,
            "fade_out_seconds": self.fade_out_seconds,
            "muted": self.muted,
            "locked": self.locked,
            "eq_low_db": self.eq_low_db,
            "eq_mid_db": self.eq_mid_db,
            "eq_high_db": self.eq_high_db,
            "reverb_amount": self.reverb_amount,
            "echo_amount": self.echo_amount,
            "compression": self.compression,
            "noise_reduction": self.noise_reduction,
            "pitch_semitones": self.pitch_semitones,
            "crop_x": self.crop_x,
            "crop_y": self.crop_y,
            "crop_width": self.crop_width,
            "crop_height": self.crop_height,
            "rotation_degrees": self.rotation_degrees,
            "caption_text": self.caption_text,
            "caption_position": self.caption_position,
        }


class StudioBrand(db.Model):
    """
    A creator's own studio branding -- their studio/label name and an
    optional logo image -- used as the default watermark across every
    one of their projects (not just one), since a creator's brand is
    who THEY are, not a property of any single project. Keyed by the
    Blind Art Server account email, the same identity everything else
    in this app is scoped to.
    """
    __tablename__ = "studio_brands"

    owner_email = db.Column(db.String(255), primary_key=True)
    studio_name = db.Column(db.String(200), default="")
    logo_filename = db.Column(db.String(300))
    logo_storage_path = db.Column(db.String(600))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "studio_name": self.studio_name or "",
            "has_logo": bool(self.logo_storage_path),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TimelineHistory(db.Model):
    """
    Undo/redo state for one project's Timeline (spec §17). Rather than a
    long, ever-growing log of individual actions, this keeps two JSON
    stacks of full timeline snapshots (all tracks and their clips): an
    undo stack of past states and a redo stack of states given up by an
    undo. See source/project/history.py for how these are used — this
    class only holds the data.
    """
    __tablename__ = "timeline_history"

    project_id = db.Column(db.String(32), primary_key=True)
    undo_stack_json = db.Column(db.Text, default="[]")
    redo_stack_json = db.Column(db.Text, default="[]")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LibraryItem(db.Model):
    """
    Downloadable Asset & Template Library (spec section 23): a small set of
    reusable resources any signed-in creator can pull into their own
    project -- either a ready-made project TEMPLATE (a starter set of
    tracks, described as data, applied by creating real Track rows) or a
    MEDIA ASSET (an actual bundled file copied into a project's Media
    Library). Everything here is free -- this app has no payment provider
    and isn't meant to (the only account/key this project ever needed from
    the owner is an AI provider key for AI Music/Voice); there is no paid
    tier to unlock or report as unavailable.
    """
    __tablename__ = "library_items"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    kind = db.Column(db.String(20), nullable=False)  # project_template, media_asset
    category = db.Column(db.String(30), default="")  # e.g. music, image, video, song, video_project
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    file_path = db.Column(db.String(600), nullable=True)      # media_asset items: bundled source file
    file_category = db.Column(db.String(30), nullable=True)   # media_asset items: MediaAsset category to import as
    template_data_json = db.Column(db.Text, nullable=True)    # project_template items: tracks/clips to create
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Collaborator(db.Model):
    """Phase 5: project invitations with tiered permissions."""
    __tablename__ = "collaborators"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    project_id = db.Column(db.String(32), db.ForeignKey("projects.id"), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    permission = db.Column(db.String(20), default="view")  # view, comment, edit, full
    invited_at = db.Column(db.DateTime, default=datetime.utcnow)
    revoked = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "permission": self.permission,
            "revoked": self.revoked,
            "invited_at": self.invited_at.isoformat() if self.invited_at else None,
        }
