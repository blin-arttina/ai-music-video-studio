"""
AI-Assisted Music Studio and Video Generator — server entry point.

Run locally:
    pip install -r requirements.txt
    export FLASK_ENV=development
    python server.py

Deploy: see documentation/DEPLOYMENT.md for the Render + Blind Art Server
steps (same pattern used for Blind-Art-Server and BuildYourAppAI).
"""

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, session, send_file, render_template, redirect, url_for
from werkzeug.utils import secure_filename

from config import get_config
from source.project.auth_client import BlindArtAuthClient, BlindArtAuthError
from source.project.models import (
    db, Project, MediaAsset, TextContent, TextRevision,
    OwnershipRecord, AuditLogEntry, Collaborator, Track, Clip, new_id,
    LibraryItem,
)
from source.project import manager
from source.project import timeline as tl
from source.project import audio_editor
from source.project import video_editor
from source.project import history as tl_history
from source.project import branding
from source.project import library as lib
from source.project import invisible_watermark as iwm
from source.project.protection import (
    hash_text, build_ownership_metadata, embed_ownership_in_text_export,
    verify_text_against_hash, watermark_image, watermark_video,
    PROTECTION_NOTICE, ffmpeg_available,
)
from source.ai import modules as ai
from source.ai import context as ai_context

CONFIG = get_config()

BASE_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    template_folder="templates_html",
    static_folder="static",
)
app.config.from_object(CONFIG)
app.config["MAX_CONTENT_LENGTH"] = CONFIG.MAX_CONTENT_LENGTH

db.init_app(app)
auth_client = BlindArtAuthClient()


# --------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("email") or not session.get("token"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "authentication required"}), 401
            return redirect(url_for("login_page"))
        return fn(*args, **kwargs)
    return wrapper


def current_user_email() -> str:
    return session.get("email", "")


def current_user_name() -> str:
    return session.get("name") or session.get("email", "Creator")


def owns_or_has_permission(project: Project, permission_needed="view") -> bool:
    if project.owner_email == current_user_email():
        return True
    rank = {"view": 0, "comment": 1, "edit": 2, "full": 3}
    collab = Collaborator.query.filter_by(
        project_id=project.id, email=current_user_email(), revoked=False
    ).first()
    if not collab:
        return False
    return rank.get(collab.permission, -1) >= rank.get(permission_needed, 99)


def log_audit(project_id: str, action: str, detail: str = ""):
    try:
        entry = AuditLogEntry(project_id=project_id, actor_email=current_user_email(),
                               action=action, detail=detail)
        db.session.add(entry)
        db.session.commit()
    except Exception:  # noqa: BLE001 - auditing must never break the main flow
        db.session.rollback()


# --------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------

@app.route("/")
def index():
    if not session.get("email"):
        return redirect(url_for("login_page"))
    projects = Project.query.filter_by(owner_email=current_user_email()).order_by(
        Project.updated_at.desc()
    ).all()
    return render_template("index.html", projects=projects, user_name=current_user_name())


@app.route("/login")
def login_page():
    return render_template("login.html", server_url=CONFIG.BLIND_ART_SERVER_URL)


@app.route("/auth/login", methods=["POST"])
def do_login():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    try:
        token = auth_client.login(email, password)
        me = auth_client.me(token)
    except BlindArtAuthError as exc:
        return render_template("login.html", server_url=CONFIG.BLIND_ART_SERVER_URL, error=str(exc))
    session["token"] = token
    session["email"] = email
    session["name"] = me.get("name") or email
    return redirect(url_for("index"))


@app.route("/auth/logout", methods=["POST"])
def do_logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/project/<project_id>")
@login_required
def project_page(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    return render_template("project.html", project=project, user_name=current_user_name())


@app.route("/project/<project_id>/text/<text_id>/ownership")
@login_required
def ownership_page(project_id, text_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    text = TextContent.query.get_or_404(text_id)
    records = OwnershipRecord.query.filter_by(content_id=text.content_id).order_by(
        OwnershipRecord.version.asc()
    ).all()
    return render_template(
        "ownership.html", project=project, text=text, records=records,
        notice=PROTECTION_NOTICE,
    )


@app.route("/health")
def health():
    return jsonify({"status": "ok", "app": CONFIG.APP_NAME})


# --------------------------------------------------------------------
# API: Projects
# --------------------------------------------------------------------

@app.route("/api/projects", methods=["GET", "POST"])
@login_required
def api_projects():
    if request.method == "POST":
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        project = manager.create_project(current_user_email(), name, data.get("description", ""))
        log_audit(project.id, "create_project")
        return jsonify(project.to_dict()), 201

    projects = Project.query.filter_by(owner_email=current_user_email()).order_by(
        Project.updated_at.desc()
    ).all()
    return jsonify([p.to_dict() for p in projects])


@app.route("/api/projects/import", methods=["POST"])
@login_required
def api_project_import():
    file = request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "no file provided"}), 400
    if not file.filename.lower().endswith(".zip"):
        return jsonify({"error": "please upload a .zip file"}), 400

    tmp_path = Path(tempfile.gettempdir()) / f"import-{uuid.uuid4().hex}.zip"
    file.save(tmp_path)
    try:
        project = manager.import_project_zip(current_user_email(), tmp_path)
    except manager.ImportError_ as e:
        return jsonify({"error": str(e)}), 400
    finally:
        tmp_path.unlink(missing_ok=True)

    log_audit(project.id, "import_project", f"imported from {file.filename}")
    return jsonify(project.to_dict()), 201


@app.route("/api/projects/<project_id>", methods=["GET", "PATCH", "DELETE"])
@login_required
def api_project_detail(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403

    if request.method == "GET":
        return jsonify(project.to_dict())

    if request.method == "PATCH":
        if not owns_or_has_permission(project, "edit"):
            return jsonify({"error": "forbidden"}), 403
        data = request.get_json(force=True)
        if "name" in data:
            manager.rename_project(project, data["name"])
        if "description" in data:
            project.description = data["description"]
        if "status" in data:
            project.status = data["status"]
        if "is_private" in data:
            project.is_private = bool(data["is_private"])
        db.session.commit()
        log_audit(project.id, "update_project")
        return jsonify(project.to_dict())

    if request.method == "DELETE":
        if project.owner_email != current_user_email():
            return jsonify({"error": "only the owner can delete a project"}), 403
        log_audit(project.id, "delete_project")
        manager.delete_project(project, hard=True)
        return jsonify({"status": "deleted"})


@app.route("/api/projects/<project_id>/duplicate", methods=["POST"])
@login_required
def api_project_duplicate(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    new_proj = manager.duplicate_project(project)
    log_audit(new_proj.id, "duplicate_project", f"from {project.id}")
    return jsonify(new_proj.to_dict()), 201


@app.route("/api/projects/<project_id>/backup", methods=["POST"])
@login_required
def api_project_backup(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    zip_path = manager.backup_project(project)
    log_audit(project.id, "backup_project", str(zip_path.name))
    return jsonify({"status": "ok", "backup_file": zip_path.name})


@app.route("/api/projects/<project_id>/export", methods=["POST"])
@login_required
def api_project_export(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    zip_path = manager.export_project_zip(project)
    log_audit(project.id, "export_project_zip", str(zip_path.name))
    return send_file(zip_path, as_attachment=True, download_name=zip_path.name)


# --------------------------------------------------------------------
# API: Media Library
# --------------------------------------------------------------------

CATEGORY_EXT_MAP = {
    "image": CONFIG.ALLOWED_IMAGE_EXT,
    "audio": CONFIG.ALLOWED_AUDIO_EXT,
    "music": CONFIG.ALLOWED_AUDIO_EXT,
    "video": CONFIG.ALLOWED_VIDEO_EXT,
    "voice": CONFIG.ALLOWED_AUDIO_EXT,
    "animation": CONFIG.ALLOWED_VIDEO_EXT | CONFIG.ALLOWED_IMAGE_EXT,
    "font": CONFIG.ALLOWED_FONT_EXT,
}


@app.route("/api/projects/<project_id>/media", methods=["GET", "POST"])
@login_required
def api_media(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403

    if request.method == "GET":
        assets = MediaAsset.query.filter_by(project_id=project.id).all()
        return jsonify([a.to_dict() for a in assets])

    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    file = request.files.get("file")
    category = request.form.get("category", "image")
    if not file or file.filename == "":
        return jsonify({"error": "no file provided"}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    allowed = CATEGORY_EXT_MAP.get(category)
    if allowed is not None and ext not in allowed:
        return jsonify({"error": f"'{ext}' is not an allowed extension for category '{category}'"}), 400

    filename = secure_filename(file.filename)
    dest_dir = Path(project.folder_path) / _category_folder(category)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{uuid.uuid4().hex}-{filename}"
    file.save(dest_path)

    file_hash = hashlib.sha256(dest_path.read_bytes()).hexdigest()
    asset = MediaAsset(
        project_id=project.id, category=category, filename=filename,
        storage_path=str(dest_path), original_hash=file_hash,
    )
    db.session.add(asset)
    db.session.commit()
    log_audit(project.id, "upload_media", filename)
    return jsonify(asset.to_dict()), 201


def _category_folder(category: str) -> str:
    return {
        "image": "images", "audio": "audio", "music": "music", "video": "video",
        "voice": "voice", "animation": "animation", "font": "fonts",
    }.get(category, "images")


@app.route("/api/projects/<project_id>/media/<media_id>/file", methods=["GET"])
@login_required
def api_media_file(project_id, media_id):
    """Streams a media asset's actual bytes for in-app playback (audio/video
    preview). Uses conditional=True so the browser can seek/scrub via HTTP
    Range requests instead of downloading the whole file first."""
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    asset = MediaAsset.query.get_or_404(media_id)
    if asset.project_id != project.id:
        return jsonify({"error": "not found"}), 404
    path = Path(asset.storage_path)
    if not path.exists():
        return jsonify({"error": "file missing on server"}), 404
    return send_file(path, conditional=True, download_name=asset.filename)


@app.route("/api/projects/<project_id>/media/<media_id>", methods=["DELETE"])
@login_required
def api_media_delete(project_id, media_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    asset = MediaAsset.query.get_or_404(media_id)
    path = Path(asset.storage_path)
    if path.exists():
        path.unlink()
    db.session.delete(asset)
    db.session.commit()
    log_audit(project.id, "delete_media", asset.filename)
    return jsonify({"status": "deleted"})


# --------------------------------------------------------------------
# API: Protected text (lyrics, notes, scripts, poems, captions)
# --------------------------------------------------------------------

@app.route("/api/projects/<project_id>/text", methods=["GET", "POST"])
@login_required
def api_text_list(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403

    if request.method == "GET":
        items = TextContent.query.filter_by(project_id=project.id).order_by(
            TextContent.updated_at.desc()
        ).all()
        return jsonify([t.to_dict(include_body=False) for t in items])

    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(force=True)
    body = data.get("body", "")
    content_hash = hash_text(body)
    text = TextContent(
        project_id=project.id,
        content_id=new_id(),
        kind=data.get("kind", "lyrics"),
        title=data.get("title", "Untitled"),
        body=body,
        creator_email=current_user_email(),
        creator_name=current_user_name(),
        version=1,
        content_hash=content_hash,
        is_private=data.get("is_private", True),
    )
    db.session.add(text)
    db.session.flush()

    revision = TextRevision(
        text_content_id=text.id, version=1, body_hash=content_hash,
        body_snapshot=body, edited_by=current_user_email(),
    )
    record = OwnershipRecord(
        content_id=text.content_id, project_id=project.id,
        creator_email=current_user_email(), creator_name=current_user_name(),
        project_name=project.name, version=1, content_hash=content_hash,
    )
    db.session.add_all([revision, record])
    db.session.commit()
    log_audit(project.id, "create_text", text.title)
    return jsonify(text.to_dict()), 201


@app.route("/api/projects/<project_id>/text/<text_id>", methods=["GET", "PUT", "DELETE"])
@login_required
def api_text_detail(project_id, text_id):
    project = Project.query.get_or_404(project_id)
    text = TextContent.query.get_or_404(text_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403

    if request.method == "GET":
        log_audit(project.id, "view_text", text.title)
        return jsonify(text.to_dict())

    if request.method == "DELETE":
        if not owns_or_has_permission(project, "edit"):
            return jsonify({"error": "forbidden"}), 403
        log_audit(project.id, "delete_text", text.title)
        db.session.delete(text)
        db.session.commit()
        return jsonify({"status": "deleted"})

    # PUT — new version, never overwrites history
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(force=True)
    if "title" in data:
        text.title = data["title"]
    if "is_private" in data:
        text.is_private = bool(data["is_private"])
    if "body" in data and data["body"] != text.body:
        text.body = data["body"]
        text.version += 1
        text.content_hash = hash_text(text.body)
        db.session.add(TextRevision(
            text_content_id=text.id, version=text.version, body_hash=text.content_hash,
            body_snapshot=text.body, edited_by=current_user_email(),
        ))
        db.session.add(OwnershipRecord(
            content_id=text.content_id, project_id=project.id,
            creator_email=text.creator_email, creator_name=text.creator_name,
            project_name=project.name, version=text.version, content_hash=text.content_hash,
        ))
    db.session.commit()
    log_audit(project.id, "update_text", f"{text.title} v{text.version}")
    return jsonify(text.to_dict())


@app.route("/api/projects/<project_id>/text/<text_id>/revisions")
@login_required
def api_text_revisions(project_id, text_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    text = TextContent.query.get_or_404(text_id)
    revisions = TextRevision.query.filter_by(text_content_id=text.id).order_by(
        TextRevision.version.asc()
    ).all()
    return jsonify([r.to_dict() for r in revisions])


@app.route("/api/projects/<project_id>/text/<text_id>/restore/<int:version>", methods=["POST"])
@login_required
def api_text_restore(project_id, text_id, version):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    text = TextContent.query.get_or_404(text_id)
    revision = TextRevision.query.filter_by(text_content_id=text.id, version=version).first_or_404()

    text.body = revision.body_snapshot
    text.version += 1
    text.content_hash = hash_text(text.body)
    db.session.add(TextRevision(
        text_content_id=text.id, version=text.version, body_hash=text.content_hash,
        body_snapshot=text.body, edited_by=current_user_email(),
    ))
    db.session.add(OwnershipRecord(
        content_id=text.content_id, project_id=project.id,
        creator_email=text.creator_email, creator_name=text.creator_name,
        project_name=project.name, version=text.version, content_hash=text.content_hash,
    ))
    db.session.commit()
    log_audit(project.id, "restore_text_version", f"{text.title} -> v{version} (as new v{text.version})")
    return jsonify(text.to_dict())


@app.route("/api/projects/<project_id>/text/<text_id>/export")
@login_required
def api_text_export(project_id, text_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    text = TextContent.query.get_or_404(text_id)
    include_copyright = request.args.get("copyright", "true").lower() != "false"

    metadata = build_ownership_metadata(
        text.content_id, text.creator_name, project.name, text.version, text.content_hash,
    )
    exported = embed_ownership_in_text_export(text.body, metadata, include_copyright)

    export_dir = Path(project.folder_path) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{secure_filename(text.title)}-v{text.version}.txt"
    export_path = export_dir / filename
    export_path.write_text(exported, encoding="utf-8")

    log_audit(project.id, "export_text", filename)
    return send_file(export_path, as_attachment=True, download_name=filename)


@app.route("/api/projects/<project_id>/text/<text_id>/verify", methods=["POST"])
@login_required
def api_text_verify(project_id, text_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    text = TextContent.query.get_or_404(text_id)
    candidate = request.get_json(force=True).get("body", "")
    matches = verify_text_against_hash(candidate, text.content_hash)
    return jsonify({"matches_current_version": matches, "checked_version": text.version})


@app.route("/api/projects/<project_id>/audit")
@login_required
def api_audit(project_id):
    project = Project.query.get_or_404(project_id)
    if project.owner_email != current_user_email():
        return jsonify({"error": "only the owner can view the audit log"}), 403
    entries = AuditLogEntry.query.filter_by(project_id=project.id).order_by(
        AuditLogEntry.created_at.desc()
    ).limit(200).all()
    return jsonify([e.to_dict() for e in entries])


# --------------------------------------------------------------------
# API: Studio branding (a creator's own name/logo, reused as the default
# watermark across every one of their projects -- not scoped to any one
# project, since a creator's brand isn't a property of a single project)
# --------------------------------------------------------------------

@app.route("/api/studio-brand", methods=["GET", "POST"])
@login_required
def api_studio_brand():
    owner_email = current_user_email()

    if request.method == "GET":
        brand = branding.get_brand(owner_email)
        return jsonify(brand.to_dict() if brand else {"studio_name": "", "has_logo": False})

    studio_name = request.form.get("studio_name", "")
    brand = branding.set_studio_name(owner_email, studio_name)

    logo_file = request.files.get("logo")
    if logo_file and logo_file.filename:
        try:
            brand = branding.save_logo(owner_email, logo_file, CONFIG.ALLOWED_IMAGE_EXT)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return jsonify(brand.to_dict())


@app.route("/api/studio-brand/logo", methods=["GET", "DELETE"])
@login_required
def api_studio_brand_logo():
    owner_email = current_user_email()
    brand = branding.get_brand(owner_email)

    if request.method == "DELETE":
        if brand:
            branding.clear_logo(owner_email)
        return jsonify({"status": "cleared"})

    if not brand or not brand.logo_storage_path or not Path(brand.logo_storage_path).exists():
        return jsonify({"error": "no logo saved"}), 404
    return send_file(brand.logo_storage_path, conditional=True)


# --------------------------------------------------------------------
# API: Protected export (watermarking)
# --------------------------------------------------------------------

@app.route("/api/projects/<project_id>/export/image", methods=["POST"])
@login_required
def api_export_image(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    media_id = request.form.get("media_id")
    asset = MediaAsset.query.get_or_404(media_id)

    brand = branding.get_brand(current_user_email())
    watermark_text = (
        request.form.get("watermark_text")
        or (brand.studio_name if brand else "")
        or CONFIG.DEFAULT_WATERMARK_TEXT
        or current_user_name()
    )
    position = request.form.get("position", CONFIG.DEFAULT_WATERMARK_POSITION)
    try:
        opacity = float(request.form.get("opacity", CONFIG.DEFAULT_WATERMARK_OPACITY))
    except ValueError:
        opacity = CONFIG.DEFAULT_WATERMARK_OPACITY

    # Export settings (spec §18) -- all optional, all default to "keep
    # the source as it is" so existing callers that don't send them are
    # unaffected.
    resolution = request.form.get("resolution", "source")
    output_format = request.form.get("format")  # "png" or "jpg"; None keeps the source's own format
    ext = ".jpg" if output_format in ("jpg", "jpeg") else (".png" if output_format == "png" else Path(asset.filename).suffix or ".png")

    # Optional invisible/forensic watermark (opt-in, additive -- never a
    # substitute for the always-on visible mark above). Only survives in
    # a lossless PNG, so it's rejected up front for any other format
    # rather than silently doing nothing.
    add_invisible = request.form.get("invisible_watermark", "false").lower() == "true"
    if add_invisible and ext.lower() != ".png":
        return jsonify({
            "error": "An invisible watermark only survives in a lossless PNG file. "
                     "Set the file format to PNG to use it, or turn it off."
        }), 400

    # Studio branding: include the creator's saved logo unless they
    # explicitly opt out for this export (default "true" -- if you saved
    # a logo, it appears until you say otherwise).
    include_logo = request.form.get("include_studio_logo", "true").lower() != "false"
    logo_path = brand.logo_storage_path if (brand and include_logo and brand.logo_storage_path) else None

    export_dir = Path(project.folder_path) / "exports"
    dest_path = export_dir / f"watermarked-{Path(asset.filename).stem}{ext}"
    watermark_image(
        asset.storage_path, str(dest_path), watermark_text, position, opacity,
        resolution=resolution, output_format=output_format, logo_path=logo_path,
    )

    if add_invisible:
        payload = iwm.build_payload(watermark_text, project.name, asset.original_hash or "")
        try:
            iwm.embed_invisible_watermark_image(dest_path, payload, dest_path)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    log_audit(project.id, "export_image_watermarked", asset.filename)
    return send_file(dest_path, as_attachment=True, download_name=dest_path.name)


@app.route("/api/projects/<project_id>/export/video", methods=["POST"])
@login_required
def api_export_video(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    if not ffmpeg_available():
        return jsonify({"error": "ffmpeg is not installed on this server; video export is unavailable until it is."}), 503

    media_id = request.form.get("media_id")
    asset = MediaAsset.query.get_or_404(media_id)

    brand = branding.get_brand(current_user_email())
    watermark_text = (
        request.form.get("watermark_text")
        or (brand.studio_name if brand else "")
        or CONFIG.DEFAULT_WATERMARK_TEXT
        or current_user_name()
    )
    position = request.form.get("position", CONFIG.DEFAULT_WATERMARK_POSITION)
    try:
        opacity = float(request.form.get("opacity", CONFIG.DEFAULT_WATERMARK_OPACITY))
    except ValueError:
        opacity = CONFIG.DEFAULT_WATERMARK_OPACITY

    # Export settings (spec §18) -- all optional, all default to "keep
    # the source as it is" so existing callers that don't send them are
    # unaffected.
    resolution = request.form.get("resolution", "source")
    frame_rate = request.form.get("frame_rate", "source")
    video_quality = request.form.get("video_quality", "medium")
    audio_bitrate = request.form.get("audio_bitrate", "192k")
    output_format = request.form.get("format", "mp4")
    ext = ".webm" if output_format == "webm" else ".mp4"

    include_logo = request.form.get("include_studio_logo", "true").lower() != "false"
    logo_path = brand.logo_storage_path if (brand and include_logo and brand.logo_storage_path) else None

    # Optional invisible/forensic watermark (opt-in, additive). For video
    # this is a metadata tag, not steganography -- see invisible_watermark.py
    # for exactly what that does and does not protect against.
    add_invisible = request.form.get("invisible_watermark", "false").lower() == "true"

    export_dir = Path(project.folder_path) / "exports"
    dest_path = export_dir / f"watermarked-{Path(asset.filename).stem}{ext}"
    try:
        watermark_video(
            asset.storage_path, str(dest_path), watermark_text, position, opacity,
            resolution=resolution, frame_rate=frame_rate, video_quality=video_quality,
            audio_bitrate=audio_bitrate, output_format=output_format, logo_path=logo_path,
        )
        if add_invisible:
            payload = iwm.build_payload(watermark_text, project.name, asset.original_hash or "")
            tagged_path = dest_path.with_name(dest_path.name + ".tagged" + ext)
            iwm.embed_invisible_watermark_media(dest_path, payload, tagged_path)
            tagged_path.replace(dest_path)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    log_audit(project.id, "export_video_watermarked", asset.filename)
    return send_file(dest_path, as_attachment=True, download_name=dest_path.name)


@app.route("/api/verify-invisible-watermark", methods=["POST"])
@login_required
def api_verify_invisible_watermark():
    """Checks an uploaded file (not tied to any project) for an invisible
    watermark this app embedded, and returns the hidden payload if found.
    Useful for checking a file you find elsewhere for your own mark."""
    file = request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "no file provided"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    tmp_path = Path(tempfile.gettempdir()) / f"verify-{uuid.uuid4().hex}.{ext or 'bin'}"
    file.save(tmp_path)
    try:
        if ext in CONFIG.ALLOWED_IMAGE_EXT:
            raw = iwm.extract_invisible_watermark_image(tmp_path)
        elif ext in CONFIG.ALLOWED_VIDEO_EXT:
            raw = iwm.extract_invisible_watermark_media(tmp_path)
        else:
            return jsonify({
                "error": f"'.{ext}' isn't a supported file type for invisible watermark checking "
                         "(images and video are supported)."
            }), 400
    finally:
        tmp_path.unlink(missing_ok=True)

    if not raw:
        return jsonify({"found": False})

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        payload = None
    return jsonify({"found": True, "payload": payload, "raw": raw})


# --------------------------------------------------------------------
# API: Multi-track timeline
# --------------------------------------------------------------------

@app.route("/api/projects/<project_id>/tracks", methods=["GET", "POST"])
@login_required
def api_tracks(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403

    if request.method == "GET":
        tracks = Track.query.filter_by(project_id=project.id).order_by(Track.order_index).all()
        return jsonify({
            "tracks": [t.to_dict() for t in tracks],
            "duration_seconds": tl.project_duration_seconds(tracks),
            "history": tl_history.history_status(project.id),
        })

    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    tl_history.record_action(project.id)
    data = request.get_json(force=True)
    track = tl.create_track(project.id, data.get("name", "New Track"), data.get("kind", "music"))
    log_audit(project.id, "create_track", track.name)
    return jsonify(track.to_dict()), 201


@app.route("/api/projects/<project_id>/tracks/<track_id>", methods=["PATCH", "DELETE"])
@login_required
def api_track_detail(project_id, track_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    track = Track.query.get_or_404(track_id)
    tl_history.record_action(project.id)

    if request.method == "DELETE":
        log_audit(project.id, "delete_track", track.name)
        db.session.delete(track)
        db.session.commit()
        return jsonify({"status": "deleted"})

    data = request.get_json(force=True)
    if "name" in data:
        track.name = data["name"]
    if "order_index" in data:
        tl.reorder_track(track, int(data["order_index"]))
    tl.set_track_flags(
        track,
        muted=data.get("muted"), locked=data.get("locked"), hidden=data.get("hidden"),
    )
    log_audit(project.id, "update_track", track.name)
    return jsonify(track.to_dict())


@app.route("/api/projects/<project_id>/tracks/<track_id>/clips", methods=["POST"])
@login_required
def api_clip_create(project_id, track_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    track = Track.query.get_or_404(track_id)
    if track.locked:
        return jsonify({"error": "track is locked"}), 409
    tl_history.record_action(project.id)

    data = request.get_json(force=True)
    clip = tl.add_clip(
        track, data.get("label", "Clip"),
        float(data.get("start_seconds", 0)), float(data.get("duration_seconds", 5)),
        media_asset_id=data.get("media_asset_id"), text_content_id=data.get("text_content_id"),
    )
    log_audit(project.id, "add_clip", clip.label)
    return jsonify(clip.to_dict()), 201


@app.route("/api/projects/<project_id>/clips/<clip_id>", methods=["PATCH", "DELETE"])
@login_required
def api_clip_detail(project_id, clip_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    clip = Clip.query.get_or_404(clip_id)
    if clip.track.locked and request.method != "GET":
        return jsonify({"error": "track is locked"}), 409
    tl_history.record_action(project.id)

    if request.method == "DELETE":
        log_audit(project.id, "delete_clip", clip.label)
        tl.delete_clip(clip)
        return jsonify({"status": "deleted"})

    data = request.get_json(force=True)
    if "label" in data:
        clip.label = data["label"]
    if "start_seconds" in data:
        tl.move_clip(clip, float(data["start_seconds"]))
    if "duration_seconds" in data:
        tl.resize_clip(clip, float(data["duration_seconds"]))
    if "trim_in_seconds" in data or "trim_out_seconds" in data:
        tl.trim_clip(clip, data.get("trim_in_seconds"), data.get("trim_out_seconds"))
    if "volume" in data:
        clip.volume = max(0.0, min(2.0, float(data["volume"])))
    if "fade_in_seconds" in data:
        clip.fade_in_seconds = max(0.0, float(data["fade_in_seconds"]))
    if "fade_out_seconds" in data:
        clip.fade_out_seconds = max(0.0, float(data["fade_out_seconds"]))
    for field, bounds in (
        ("eq_low_db", (-24, 24)), ("eq_mid_db", (-24, 24)), ("eq_high_db", (-24, 24)),
        ("reverb_amount", (0, 1)), ("echo_amount", (0, 1)),
        ("compression", (0, 1)), ("noise_reduction", (0, 1)),
        ("pitch_semitones", (-12, 12)),
        ("crop_x", (0, 1)), ("crop_y", (0, 1)), ("crop_width", (0.05, 1)), ("crop_height", (0.05, 1)),
    ):
        if field in data:
            lo, hi = bounds
            setattr(clip, field, max(lo, min(hi, float(data[field]))))
    if "rotation_degrees" in data:
        deg = int(data["rotation_degrees"]) % 360
        clip.rotation_degrees = deg if deg in (0, 90, 180, 270) else 0
    if "caption_text" in data:
        clip.caption_text = data["caption_text"][:300]
    if "caption_position" in data:
        clip.caption_position = data["caption_position"] if data["caption_position"] in ("top", "center", "bottom") else "bottom"
    tl.set_clip_flags(clip, muted=data.get("muted"), locked=data.get("locked"))
    db.session.commit()
    log_audit(project.id, "update_clip", clip.label)
    return jsonify(clip.to_dict())


@app.route("/api/projects/<project_id>/clips/<clip_id>/render-audio", methods=["POST"])
@login_required
def api_clip_render_audio(project_id, clip_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    if not audio_editor.ffmpeg_available():
        return jsonify({"error": "ffmpeg is not installed on this server; audio rendering is unavailable."}), 503

    clip = Clip.query.get_or_404(clip_id)
    if not clip.media_asset_id or not clip.media_asset:
        return jsonify({"error": "this clip has no audio file attached"}), 400
    if clip.media_asset.category not in ("audio", "music", "voice"):
        return jsonify({"error": "this clip's media is not an audio file"}), 400

    export_dir = Path(project.folder_path) / "exports"
    dest_path = export_dir / f"rendered-{Path(clip.media_asset.filename).stem}-{clip.id[:8]}.wav"
    try:
        audio_editor.render_clip_audio(
            clip.media_asset.storage_path, str(dest_path),
            trim_in_seconds=clip.trim_in_seconds, trim_out_seconds=clip.trim_out_seconds,
            volume=0.0 if clip.muted else clip.volume,
            fade_in_seconds=clip.fade_in_seconds, fade_out_seconds=clip.fade_out_seconds,
            eq_low_db=clip.eq_low_db, eq_mid_db=clip.eq_mid_db, eq_high_db=clip.eq_high_db,
            reverb_amount=clip.reverb_amount, echo_amount=clip.echo_amount,
            compression=clip.compression, noise_reduction=clip.noise_reduction,
            pitch_semitones=clip.pitch_semitones,
        )
    except audio_editor.AudioEditError as exc:
        return jsonify({"error": str(exc)}), 500

    log_audit(project.id, "render_clip_audio", clip.label)
    return send_file(dest_path, as_attachment=True, download_name=dest_path.name)


@app.route("/api/projects/<project_id>/clips/<clip_id>/render-video", methods=["POST"])
@login_required
def api_clip_render_video(project_id, clip_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    if not video_editor.ffmpeg_available():
        return jsonify({"error": "ffmpeg is not installed on this server; video rendering is unavailable."}), 503

    clip = Clip.query.get_or_404(clip_id)
    if not clip.media_asset_id or not clip.media_asset:
        return jsonify({"error": "this clip has no video file attached"}), 400
    if clip.media_asset.category not in ("video", "animation"):
        return jsonify({"error": "this clip's media is not a video file"}), 400

    export_dir = Path(project.folder_path) / "exports"
    dest_path = export_dir / f"edited-{Path(clip.media_asset.filename).stem}-{clip.id[:8]}.mp4"
    try:
        video_editor.render_clip_video(
            clip.media_asset.storage_path, str(dest_path),
            trim_in_seconds=clip.trim_in_seconds, trim_out_seconds=clip.trim_out_seconds,
            crop_x=clip.crop_x, crop_y=clip.crop_y, crop_width=clip.crop_width, crop_height=clip.crop_height,
            rotation_degrees=clip.rotation_degrees,
            fade_in_seconds=clip.fade_in_seconds, fade_out_seconds=clip.fade_out_seconds,
            caption_text=clip.caption_text, caption_position=clip.caption_position,
            mute=clip.muted,
        )
    except video_editor.VideoEditError as exc:
        return jsonify({"error": str(exc)}), 500

    log_audit(project.id, "render_clip_video", clip.label)
    return send_file(dest_path, as_attachment=True, download_name=dest_path.name)


@app.route("/api/projects/<project_id>/clips/<clip_id>/crossfade-with-next", methods=["POST"])
@login_required
def api_clip_crossfade_with_next(project_id, clip_id):
    """Crossfades this clip into whichever clip starts next on the same
    track. Each clip's own trim/effects are applied first (via the same
    render_clip_audio/render_clip_video used elsewhere), then the two
    resulting files are joined with a real crossfade transition."""
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    if not (audio_editor.ffmpeg_available() and video_editor.ffmpeg_available()):
        return jsonify({"error": "ffmpeg is not installed on this server."}), 503

    clip_a = Clip.query.get_or_404(clip_id)
    next_clip = (
        Clip.query.filter(Clip.track_id == clip_a.track_id, Clip.start_seconds > clip_a.start_seconds)
        .order_by(Clip.start_seconds.asc())
        .first()
    )
    if not next_clip:
        return jsonify({"error": "there is no later clip on this track to crossfade into"}), 400
    if not (clip_a.media_asset and next_clip.media_asset):
        return jsonify({"error": "both clips need an attached media file"}), 400

    data = request.get_json(force=True) if request.data else {}
    duration = max(0.1, min(10.0, float(data.get("duration_seconds", 1.0))))
    style = data.get("style", "fade")

    cat_a, cat_b = clip_a.media_asset.category, next_clip.media_asset.category
    audio_categories = {"audio", "music", "voice"}
    video_categories = {"video", "animation"}

    export_dir = Path(project.folder_path) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    temp_a = export_dir / f"_xfade_a_{clip_a.id[:8]}.tmp"
    temp_b = export_dir / f"_xfade_b_{next_clip.id[:8]}.tmp"

    try:
        if cat_a in audio_categories and cat_b in audio_categories:
            rendered_a = audio_editor.render_clip_audio(
                clip_a.media_asset.storage_path, str(temp_a) + ".wav",
                trim_in_seconds=clip_a.trim_in_seconds, trim_out_seconds=clip_a.trim_out_seconds,
                volume=clip_a.volume, eq_low_db=clip_a.eq_low_db, eq_mid_db=clip_a.eq_mid_db,
                eq_high_db=clip_a.eq_high_db, reverb_amount=clip_a.reverb_amount,
                echo_amount=clip_a.echo_amount, compression=clip_a.compression,
                noise_reduction=clip_a.noise_reduction, pitch_semitones=clip_a.pitch_semitones,
            )
            rendered_b = audio_editor.render_clip_audio(
                next_clip.media_asset.storage_path, str(temp_b) + ".wav",
                trim_in_seconds=next_clip.trim_in_seconds, trim_out_seconds=next_clip.trim_out_seconds,
                volume=next_clip.volume, eq_low_db=next_clip.eq_low_db, eq_mid_db=next_clip.eq_mid_db,
                eq_high_db=next_clip.eq_high_db, reverb_amount=next_clip.reverb_amount,
                echo_amount=next_clip.echo_amount, compression=next_clip.compression,
                noise_reduction=next_clip.noise_reduction, pitch_semitones=next_clip.pitch_semitones,
            )
            dest_path = export_dir / f"crossfaded-{clip_a.id[:8]}-{next_clip.id[:8]}.wav"
            audio_editor.crossfade_audio(rendered_a, rendered_b, str(dest_path), duration)
        elif cat_a in video_categories and cat_b in video_categories:
            rendered_a = video_editor.render_clip_video(
                clip_a.media_asset.storage_path, str(temp_a) + ".mp4",
                trim_in_seconds=clip_a.trim_in_seconds, trim_out_seconds=clip_a.trim_out_seconds,
                crop_x=clip_a.crop_x, crop_y=clip_a.crop_y, crop_width=clip_a.crop_width,
                crop_height=clip_a.crop_height, rotation_degrees=clip_a.rotation_degrees,
                caption_text=clip_a.caption_text, caption_position=clip_a.caption_position,
                mute=clip_a.muted,
            )
            rendered_b = video_editor.render_clip_video(
                next_clip.media_asset.storage_path, str(temp_b) + ".mp4",
                trim_in_seconds=next_clip.trim_in_seconds, trim_out_seconds=next_clip.trim_out_seconds,
                crop_x=next_clip.crop_x, crop_y=next_clip.crop_y, crop_width=next_clip.crop_width,
                crop_height=next_clip.crop_height, rotation_degrees=next_clip.rotation_degrees,
                caption_text=next_clip.caption_text, caption_position=next_clip.caption_position,
                mute=next_clip.muted,
            )
            dest_path = export_dir / f"crossfaded-{clip_a.id[:8]}-{next_clip.id[:8]}.mp4"
            video_editor.crossfade_video(rendered_a, rendered_b, str(dest_path), duration, style)
        else:
            return jsonify({"error": "both clips must be the same kind of media (both audio-like or both video-like)"}), 400
    except (audio_editor.AudioEditError, video_editor.VideoEditError) as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        for tmp in (temp_a, temp_b):
            for suffix in (".wav", ".mp4"):
                p = Path(str(tmp) + suffix)
                if p.exists():
                    p.unlink()

    log_audit(project.id, "crossfade_clips", f"{clip_a.label} -> {next_clip.label}")
    return send_file(dest_path, as_attachment=True, download_name=dest_path.name)


@app.route("/api/projects/<project_id>/clips/<clip_id>/split", methods=["POST"])
@login_required
def api_clip_split(project_id, clip_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    clip = Clip.query.get_or_404(clip_id)
    if clip.track.locked:
        return jsonify({"error": "track is locked"}), 409
    tl_history.record_action(project.id)

    split_at = float(request.get_json(force=True).get("split_at_seconds", 0))
    try:
        left, right = tl.split_clip(clip, split_at)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    log_audit(project.id, "split_clip", clip.label)
    return jsonify({"left": left.to_dict(), "right": right.to_dict()}), 201


def _timeline_state_response(project_id):
    tracks = Track.query.filter_by(project_id=project_id).order_by(Track.order_index).all()
    return {
        "tracks": [t.to_dict() for t in tracks],
        "duration_seconds": tl.project_duration_seconds(tracks),
        "history": tl_history.history_status(project_id),
    }


@app.route("/api/projects/<project_id>/timeline/undo", methods=["POST"])
@login_required
def api_timeline_undo(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    try:
        tl_history.undo(project.id)
    except tl_history.NothingToUndoError as exc:
        return jsonify({"error": str(exc)}), 400
    log_audit(project.id, "timeline_undo", "")
    return jsonify(_timeline_state_response(project.id))


@app.route("/api/projects/<project_id>/timeline/redo", methods=["POST"])
@login_required
def api_timeline_redo(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    try:
        tl_history.redo(project.id)
    except tl_history.NothingToRedoError as exc:
        return jsonify({"error": str(exc)}), 400
    log_audit(project.id, "timeline_redo", "")
    return jsonify(_timeline_state_response(project.id))


@app.route("/api/projects/<project_id>/timeline/history-status", methods=["GET"])
@login_required
def api_timeline_history_status(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    return jsonify(tl_history.history_status(project.id))


# --------------------------------------------------------------------
# API: Collaboration (Phase 5)
# --------------------------------------------------------------------

@app.route("/api/projects/<project_id>/collaborators", methods=["GET", "POST"])
@login_required
def api_collaborators(project_id):
    project = Project.query.get_or_404(project_id)
    if project.owner_email != current_user_email():
        return jsonify({"error": "only the owner can manage collaborators"}), 403

    if request.method == "GET":
        return jsonify([c.to_dict() for c in project.collaborators])

    data = request.get_json(force=True)
    collab = Collaborator(project_id=project.id, email=data["email"],
                           permission=data.get("permission", "view"))
    db.session.add(collab)
    db.session.commit()
    log_audit(project.id, "invite_collaborator", f"{collab.email} ({collab.permission})")
    return jsonify(collab.to_dict()), 201


@app.route("/api/projects/<project_id>/collaborators/<collab_id>/revoke", methods=["POST"])
@login_required
def api_collaborator_revoke(project_id, collab_id):
    project = Project.query.get_or_404(project_id)
    if project.owner_email != current_user_email():
        return jsonify({"error": "only the owner can manage collaborators"}), 403
    collab = Collaborator.query.get_or_404(collab_id)
    collab.revoked = True
    db.session.commit()
    log_audit(project.id, "revoke_collaborator", collab.email)
    return jsonify(collab.to_dict())


@app.route("/api/projects/<project_id>/collaborators/<collab_id>", methods=["PATCH"])
@login_required
def api_collaborator_update(project_id, collab_id):
    """Changes an existing collaborator's permission tier, and/or
    restores (un-revokes) access without needing to send a whole new
    invite. Owner only, same as inviting and revoking."""
    project = Project.query.get_or_404(project_id)
    if project.owner_email != current_user_email():
        return jsonify({"error": "only the owner can manage collaborators"}), 403
    collab = Collaborator.query.get_or_404(collab_id)
    if collab.project_id != project.id:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(force=True)
    if "permission" in data:
        permission = data["permission"] if data["permission"] in ("view", "comment", "edit", "full") else collab.permission
        collab.permission = permission
    if "revoked" in data:
        collab.revoked = bool(data["revoked"])

    db.session.commit()
    log_audit(
        project.id,
        "update_collaborator",
        f"{collab.email} -> {collab.permission}{' (revoked)' if collab.revoked else ''}",
    )
    return jsonify(collab.to_dict())


# --------------------------------------------------------------------
# API: AI Modules
# --------------------------------------------------------------------

def _build_ai_project_context(project: Project) -> str:
    """AI Project Memory (spec §14): assembles this project's current
    state (counts, titles/kinds of saved text -- never the text bodies
    themselves -- media counts, timeline size, and studio brand) so the
    AI Assistant answers with real awareness of the project instead of
    a blank slate, automatically, on every call -- see source/ai/
    context.py for exactly what is and isn't included."""
    asset_counts = {}
    for a in project.media_assets:
        asset_counts[a.category] = asset_counts.get(a.category, 0) + 1

    recent_texts = (
        TextContent.query.filter_by(project_id=project.id)
        .order_by(TextContent.updated_at.desc())
        .limit(20)
        .all()
    )
    text_items = [{"title": t.title, "kind": t.kind} for t in recent_texts]

    tracks = Track.query.filter_by(project_id=project.id).order_by(Track.order_index).all()
    clip_count = sum(len(t.clips) for t in tracks)
    duration = tl.project_duration_seconds(tracks)

    brand = branding.get_brand(project.owner_email)

    return ai_context.build_project_context(
        project_name=project.name,
        description=project.description,
        status=project.status,
        studio_name=brand.studio_name if brand else "",
        asset_counts=asset_counts,
        text_items=text_items,
        track_count=len(tracks),
        clip_count=clip_count,
        duration_seconds=duration,
    )


@app.route("/api/projects/<project_id>/ai/music", methods=["POST"])
@login_required
def api_ai_music(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    d = request.get_json(force=True)
    return jsonify(ai.generate_music(d.get("prompt", ""), d.get("genre", ""), d.get("mood", ""),
                                      d.get("tempo"), d.get("key", "")))


@app.route("/api/projects/<project_id>/ai/lyrics", methods=["POST"])
@login_required
def api_ai_lyrics(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    d = request.get_json(force=True)
    result = ai.generate_lyrics(
        d.get("idea", ""), d.get("genre", ""), d.get("mood", ""), d.get("structure", ""),
        project_context=_build_ai_project_context(project),
    )
    if result.get("status") == ai.OK:
        log_audit(project.id, "ai_generate_lyrics", d.get("idea", "")[:200])
    return jsonify(result)


@app.route("/api/projects/<project_id>/ai/script", methods=["POST"])
@login_required
def api_ai_script(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    d = request.get_json(force=True)
    result = ai.generate_script(
        d.get("concept", ""), int(d.get("scene_count", 3)),
        project_context=_build_ai_project_context(project),
    )
    if result.get("status") == ai.OK:
        log_audit(project.id, "ai_generate_script", d.get("concept", "")[:200])
    return jsonify(result)


@app.route("/api/projects/<project_id>/ai/video-plan", methods=["POST"])
@login_required
def api_ai_video_plan(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    d = request.get_json(force=True)
    result = ai.generate_video_plan(d.get("concept", ""), project_context=_build_ai_project_context(project))
    if result.get("status") == ai.OK:
        log_audit(project.id, "ai_generate_video_plan", d.get("concept", "")[:200])
    return jsonify(result)


@app.route("/api/projects/<project_id>/ai/voice", methods=["POST"])
@login_required
def api_ai_voice(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    d = request.get_json(force=True)
    text = d.get("text", "")
    exaggeration = float(d.get("exaggeration", 0.5))
    cfg_weight = float(d.get("cfg_weight", 0.5))

    reference_path = None
    reference_asset_id = d.get("reference_asset_id")
    if reference_asset_id:
        reference_asset = MediaAsset.query.filter_by(id=reference_asset_id, project_id=project.id).first()
        if not reference_asset:
            return jsonify({"error": "reference media asset not found in this project"}), 404
        if reference_asset.category not in ("voice", "audio"):
            return jsonify({"error": "the reference clip must be a voice or audio Media Library item"}), 400
        reference_path = reference_asset.storage_path

    dest_dir = Path(project.folder_path) / _category_folder("voice")
    result = ai.generate_voice(text, reference_audio_path=reference_path,
                                exaggeration=exaggeration, cfg_weight=cfg_weight,
                                out_dir=str(dest_dir))
    if result.get("status") != ai.OK:
        return jsonify(result)

    audio_path = Path(result["audio_path"])
    file_hash = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    asset = MediaAsset(
        project_id=project.id, category="voice", filename=audio_path.name,
        storage_path=str(audio_path), original_hash=file_hash,
    )
    db.session.add(asset)
    db.session.commit()
    log_audit(project.id, "ai_generate_voice", "cloned" if result.get("cloned") else "default voice")
    return jsonify({"status": ai.OK, "cloned": result.get("cloned", False), "asset": asset.to_dict()}), 201


@app.route("/api/projects/<project_id>/ai/voice/reference-options")
@login_required
def api_ai_voice_reference_options(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    assets = MediaAsset.query.filter_by(project_id=project.id).filter(
        MediaAsset.category.in_(["voice", "audio"])
    ).all()
    return jsonify([a.to_dict() for a in assets])


@app.route("/api/projects/<project_id>/ai/image", methods=["POST"])
@login_required
def api_ai_image(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    d = request.get_json(force=True)
    return jsonify(ai.generate_image(d.get("prompt", ""), d.get("style", "")))


@app.route("/api/projects/<project_id>/ai/animation", methods=["POST"])
@login_required
def api_ai_animation(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    d = request.get_json(force=True)
    return jsonify(ai.generate_animation(d.get("prompt", ""), int(d.get("duration_seconds", 5))))


@app.route("/api/projects/<project_id>/ai/help", methods=["POST"])
@login_required
def api_ai_help(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    d = request.get_json(force=True)
    result = ai.help_assistant(d.get("question", ""), project_context=_build_ai_project_context(project))
    return jsonify(result)


@app.route("/api/projects/<project_id>/ai/summary")
@login_required
def api_ai_project_summary(project_id):
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "view"):
        return jsonify({"error": "forbidden"}), 403
    counts = {}
    for a in project.media_assets:
        counts[a.category] = counts.get(a.category, 0) + 1
    return jsonify(ai.project_manager_summary(project.name, counts, len(project.text_contents)))


# --------------------------------------------------------------------
# API: Downloadable Asset & Template Library (spec section 23)
# --------------------------------------------------------------------

@app.route("/api/library", methods=["GET"])
@login_required
def api_library_list():
    items = lib.list_library_items()
    return jsonify([i.to_dict() for i in items])


@app.route("/api/library/<item_id>/apply-template", methods=["POST"])
@login_required
def api_library_apply_template(item_id):
    item = LibraryItem.query.get_or_404(item_id)
    d = request.get_json(force=True)
    project_id = d.get("project_id", "")
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    if item.kind != "project_template":
        return jsonify({"error": "this library item is not a project template"}), 400
    created = lib.apply_project_template(item, project)
    log_audit(project.id, "apply_library_template", item.title)
    return jsonify({"tracks_created": [t.to_dict() for t in created]}), 201


@app.route("/api/library/<item_id>/import-asset", methods=["POST"])
@login_required
def api_library_import_asset(item_id):
    item = LibraryItem.query.get_or_404(item_id)
    d = request.get_json(force=True)
    project_id = d.get("project_id", "")
    project = Project.query.get_or_404(project_id)
    if not owns_or_has_permission(project, "edit"):
        return jsonify({"error": "forbidden"}), 403
    if item.kind != "media_asset":
        return jsonify({"error": "this library item is not a media asset"}), 400
    try:
        asset = lib.copy_media_asset_to_project(item, project)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 500
    log_audit(project.id, "import_library_asset", item.title)
    return jsonify(asset.to_dict()), 201


# --------------------------------------------------------------------

with app.app_context():
    db.create_all()
    lib.seed_library()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=(os.environ.get("FLASK_ENV") == "development"))
