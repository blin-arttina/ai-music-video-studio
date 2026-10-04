"""
Content protection engine.

Two required systems live here, per the project spec:

1. Text ownership protection — lyrics, notes, scripts, poems, captions.
   Every save gets a hash, a timestamp, a version, and a server-side
   ownership record. This is documentation of authorship, NOT legal
   copyright registration — see NOTICE below and CONTENT_PROTECTION_GUIDE.txt.

2. Image/video watermarking — applied automatically on export, on by
   default, with opacity/size clamped so it can't be silently disabled.

NOTICE (must stay user-visible wherever protection is discussed):
    A watermark discourages unauthorized use but cannot make copying
    technically impossible. This system does not legally register or
    guarantee copyright; it documents authorship. Formal copyright
    registration and legal enforcement are separate legal processes.
"""

import hashlib
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import get_config

CONFIG = get_config()

PROTECTION_NOTICE = (
    "A watermark discourages unauthorized use but cannot make copying "
    "technically impossible. This application documents authorship using "
    "ownership metadata, timestamps, version history, and cryptographic "
    "hashes — it does not legally register or guarantee copyright. Formal "
    "copyright registration and legal enforcement remain separate legal "
    "processes."
)


# --------------------------------------------------------------------------
# Text ownership protection
# --------------------------------------------------------------------------

def hash_text(body: str) -> str:
    """SHA-256 hash of protected text, so later copies can be compared
    against the registered version without exposing the original text."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_ownership_metadata(content_id: str, creator_name: str, project_name: str,
                              version: int, content_hash: str, created_at: datetime = None) -> dict:
    """The ownership/copyright info block shown on the app's ownership page
    and embeddable into exported files."""
    created_at = created_at or datetime.utcnow()
    return {
        "content_id": content_id,
        "creator_name": creator_name,
        "project_name": project_name,
        "version": version,
        "content_hash": content_hash,
        "created_at": created_at.isoformat() + "Z",
        "protection_notice": PROTECTION_NOTICE,
    }


def copyright_notice_line(creator_name: str, year: int = None) -> str:
    year = year or datetime.utcnow().year
    return f"© {year} {creator_name}. All rights reserved. Ownership documented, not legally registered."


def embed_ownership_in_text_export(body: str, metadata: dict, include_copyright: bool = True) -> str:
    """Appends a visible ownership block to an exported .txt/.md file."""
    lines = [body.rstrip(), "", "---", "OWNERSHIP RECORD"]
    lines.append(f"Content ID: {metadata['content_id']}")
    lines.append(f"Creator: {metadata['creator_name']}")
    lines.append(f"Project: {metadata['project_name']}")
    lines.append(f"Version: {metadata['version']}")
    lines.append(f"Content hash (SHA-256): {metadata['content_hash']}")
    lines.append(f"Created: {metadata['created_at']}")
    if include_copyright:
        lines.append("")
        lines.append(copyright_notice_line(metadata["creator_name"]))
    lines.append("")
    lines.append(PROTECTION_NOTICE)
    return "\n".join(lines)


def verify_text_against_hash(body: str, registered_hash: str) -> bool:
    """Compares a candidate text against a previously registered hash,
    without needing to expose the original text."""
    return hash_text(body) == registered_hash


# --------------------------------------------------------------------------
# Watermarking
# --------------------------------------------------------------------------

def _clamp_opacity(opacity: float) -> float:
    return max(CONFIG.MIN_WATERMARK_OPACITY, min(CONFIG.MAX_WATERMARK_OPACITY, opacity))


def _load_font(size: int):
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


# Export settings (spec §18): a shared, small set of named presets for
# resolution so the same options make sense in the UI for both images
# and video, rather than free-typed pixel values a user could get wrong.
# "source" always means "don't resize" -- the safest default.
RESOLUTION_PRESETS = {
    "source": None,
    "1080p": 1920,   # longer side, in pixels
    "720p": 1280,
    "480p": 854,
}
FRAME_RATE_PRESETS = {"source": None, "24": 24, "30": 30, "60": 60}
VIDEO_QUALITY_CRF = {"high": 18, "medium": 23, "low": 28}
VALID_AUDIO_BITRATES = {"128k", "192k", "256k", "320k"}
VALID_VIDEO_FORMATS = {"mp4", "webm"}
VALID_IMAGE_FORMATS = {"png", "jpg"}


def _resize_to_longer_side(image: Image.Image, longer_side: int) -> Image.Image:
    w, h = image.size
    if w >= h:
        new_w, new_h = longer_side, max(1, round(h * longer_side / w))
    else:
        new_h, new_w = longer_side, max(1, round(w * longer_side / h))
    return image.resize((new_w, new_h), Image.LANCZOS)


def _prepare_logo_overlay(logo_path: str, target_height: int, opacity: float):
    """Loads a logo image, scales it to target_height (preserving aspect,
    only ever downscaling from its stored size), and applies the same
    opacity as the text so the two read as one mark. Returns None if the
    logo can't be loaded, so a bad/missing logo never blocks the
    required watermark itself."""
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception:
        return None
    if logo.height != target_height:
        scale = target_height / logo.height
        logo = logo.resize((max(1, round(logo.width * scale)), target_height), Image.LANCZOS)
    r, g, b, a = logo.split()
    a = a.point(lambda v: int(v * opacity))
    return Image.merge("RGBA", (r, g, b, a))


def watermark_image(
    source_path: str,
    dest_path: str,
    text: str,
    position: str = "corner",
    opacity: float = None,
    resolution: str = "source",
    output_format: str = None,
    logo_path: str = None,
) -> str:
    """
    Embeds a visible text watermark (and, if provided, a studio logo
    right alongside it) into the exported image. Returns the dest_path.
    Watermarking cannot be skipped by callers in this module — there is
    deliberately no "watermark=False" parameter, and the logo is always
    an ADDITION next to the required text, never a replacement for it.

    `resolution` is one of RESOLUTION_PRESETS ("source" leaves the image
    at its original size). `output_format` is "png" or "jpg"/"jpeg"; if
    not given, the format is inferred from dest_path's extension as
    before, so existing callers are unaffected. `logo_path` is an
    optional path to a studio logo image (see source/project/
    branding.py) drawn immediately to the left of the watermark text, at
    the same opacity, as a single combined mark.
    """
    opacity = _clamp_opacity(opacity if opacity is not None else CONFIG.DEFAULT_WATERMARK_OPACITY)
    position = position if position in ("corner", "center", "tiled") else CONFIG.DEFAULT_WATERMARK_POSITION
    resolution = resolution if resolution in RESOLUTION_PRESETS else "source"

    base = Image.open(source_path).convert("RGBA")
    longer_side = RESOLUTION_PRESETS[resolution]
    if longer_side and longer_side < max(base.size):
        # Only downscale -- upscaling a photo/graphic past its native
        # resolution just makes it blurrier, not higher quality.
        base = _resize_to_longer_side(base, longer_side)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(16, base.width // 24)
    font = _load_font(font_size)
    text = text or ""
    if text:
        text_bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
    else:
        tw, th = 0, 0
    alpha = int(255 * opacity)
    fill = (255, 255, 255, alpha)
    shadow = (0, 0, 0, int(alpha * 0.6))

    logo_img = None
    if logo_path:
        logo_img = _prepare_logo_overlay(logo_path, max(16, int(font_size * 1.6)), opacity)
    logo_w, logo_h = logo_img.size if logo_img else (0, 0)
    gap = max(6, base.width // 150) if (logo_img and text) else 0

    mark_w = logo_w + gap + tw
    mark_h = max(logo_h, th)

    def stamp(x, y):
        """Draws the combined logo+text mark with its top-left at (x, y)."""
        if logo_img:
            logo_y = y + (mark_h - logo_h) // 2
            overlay.paste(logo_img, (int(x), int(logo_y)), logo_img)
        if text:
            text_x = x + logo_w + gap
            text_y = y + (mark_h - th) // 2
            draw.text((text_x + 1, text_y + 1), text, font=font, fill=shadow)
            draw.text((text_x, text_y), text, font=font, fill=fill)

    margin = max(8, base.width // 80)
    if position == "corner":
        stamp(base.width - mark_w - margin, base.height - mark_h - margin)
    elif position == "center":
        stamp((base.width - mark_w) // 2, (base.height - mark_h) // 2)
    elif position == "tiled":
        step_x = mark_w + margin * 4
        step_y = mark_h + margin * 4
        y = 0
        row = 0
        while y < base.height:
            x = -step_x if row % 2 else 0
            while x < base.width:
                stamp(x, y)
                x += step_x
            y += step_y
            row += 1

    watermarked = Image.alpha_composite(base, overlay)
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

    output_format = (output_format or "").lower()
    is_jpg = output_format in ("jpg", "jpeg") or (
        not output_format and Path(dest_path).suffix.lower() in (".jpg", ".jpeg")
    )
    if is_jpg:
        watermarked = watermarked.convert("RGB")
        watermarked.save(dest_path, format="JPEG", quality=92)
    else:
        watermarked.save(dest_path, format="PNG")
    return dest_path


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


LOGO_OVERLAY_HEIGHT_PX = 64  # fixed size (see docstring) rather than a
                             # percentage of frame height, since ffmpeg
                             # can't easily size one filter's input from
                             # another's output dimensions mid-graph.


def watermark_video(
    source_path: str,
    dest_path: str,
    text: str,
    position: str = "corner",
    opacity: float = None,
    resolution: str = "source",
    frame_rate: str = "source",
    video_quality: str = "medium",
    audio_bitrate: str = "192k",
    output_format: str = "mp4",
    logo_path: str = None,
) -> str:
    """
    Burns a persistent text watermark into the exported video using ffmpeg's
    drawtext filter, so it remains attached throughout playback, then
    applies the requested export settings (spec §18) in the same pass:
    resolution, frame rate, video quality, audio bitrate, and container
    format. Raises RuntimeError if ffmpeg is not installed on the host —
    callers should surface that clearly rather than silently shipping an
    unwatermarked video.

    `resolution` and `frame_rate` are keys into RESOLUTION_PRESETS /
    FRAME_RATE_PRESETS ("source" leaves each unchanged). `video_quality`
    is "high"/"medium"/"low" (mapped to an ffmpeg CRF value -- lower CRF
    is higher quality and a larger file). `audio_bitrate` is one of
    VALID_AUDIO_BITRATES. `output_format` is "mp4" (H.264/AAC) or "webm"
    (VP9/Opus); dest_path's extension should already match it. `logo_path`
    is an optional studio logo image, always drawn as an ADDITION next to
    the required text, never a replacement for it.

    The logo is scaled to a fixed LOGO_OVERLAY_HEIGHT_PX regardless of
    the output resolution, rather than a percentage of frame height like
    the image watermarker uses -- ffmpeg can't size one filter's input
    from another filter's output inside one filter graph without the
    extra complexity of `scale2ref`, so this is a deliberate, documented
    simplification: a bit large on a 480p export, a bit small on 4K, but
    a clearly visible, correctly-composited logo either way.
    """
    if not ffmpeg_available():
        raise RuntimeError(
            "ffmpeg is not installed on this server. Video export with the "
            "required watermark cannot proceed until ffmpeg is available."
        )

    opacity = _clamp_opacity(opacity if opacity is not None else CONFIG.DEFAULT_WATERMARK_OPACITY)
    position = position if position in ("corner", "center", "tiled") else CONFIG.DEFAULT_WATERMARK_POSITION
    resolution = resolution if resolution in RESOLUTION_PRESETS else "source"
    frame_rate = frame_rate if frame_rate in FRAME_RATE_PRESETS else "source"
    video_quality = video_quality if video_quality in VIDEO_QUALITY_CRF else "medium"
    audio_bitrate = audio_bitrate if audio_bitrate in VALID_AUDIO_BITRATES else "192k"
    output_format = output_format if output_format in VALID_VIDEO_FORMATS else "mp4"
    use_logo = bool(logo_path and Path(logo_path).exists())

    safe_text = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")

    # When there's a logo, nudge the text left/up out of the way of the
    # fixed-size logo mark so the two don't overlap, using the logo's
    # known pixel height/an estimated width margin (a fixed value, since
    # the logo's actual rendered width varies with its own aspect ratio
    # and isn't available to drawtext's expression evaluator).
    logo_text_gap = LOGO_OVERLAY_HEIGHT_PX + 16 if use_logo else 0
    pos_expr = {
        "corner": f"x=w-tw-{20 + (logo_text_gap if use_logo else 0)}:y=h-th-20",
        "center": "x=(w-tw)/2:y=(h-th)/2" + (f"+{logo_text_gap // 2}" if use_logo else ""),
        "tiled": "x=mod(t*20\\,w-tw):y=mod(t*15\\,h-th)",  # drifting stamp approximates tiling over time
    }[position]

    drawtext = (
        f"drawtext=text='{safe_text}':fontcolor=white@{opacity}:"
        f"fontsize=h/20:box=1:boxcolor=black@{opacity * 0.5}:boxborderw=6:{pos_expr}"
    )

    scale_filter = None
    longer_side = RESOLUTION_PRESETS[resolution]
    if longer_side:
        # Scale so the longer side matches the preset, preserving aspect
        # ratio, and round to an even number (required by libx264/vp9).
        scale_filter = (
            f"scale='if(gt(iw,ih),min(iw,{longer_side}),-2)':'if(gt(iw,ih),-2,min(ih,{longer_side}))'"
        )

    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", source_path]

    fps = FRAME_RATE_PRESETS[frame_rate]

    if use_logo:
        # A logo needs its own input stream, composited onto the main
        # video with ffmpeg's overlay filter before the text is drawn on
        # top of both, so all three graphs (main video, logo, text) are
        # tied together as one filter_complex rather than a simple -vf
        # chain (which only ever sees one input).
        cmd += ["-i", logo_path]
        logo_pos_expr = {
            "corner": "x=main_w-w-16:y=main_h-h-16",
            "center": f"x=(main_w-w)/2:y=(main_h-h)/2-{logo_text_gap // 2}",
            "tiled": "x=16:y=16",  # shown once, since tiling a static image over time isn't worth the complexity here
        }[position]
        main_chain = f"[0:v]{scale_filter}[scaled]" if scale_filter else "[0:v]copy[scaled]"
        filter_complex = (
            f"{main_chain};"
            f"[1:v]scale=-2:{LOGO_OVERLAY_HEIGHT_PX},format=rgba,colorchannelmixer=aa={opacity:.3f}[logo];"
            f"[scaled][logo]overlay={logo_pos_expr}[withlogo];"
            f"[withlogo]{drawtext}[outv]"
        )
        cmd += ["-filter_complex", filter_complex, "-map", "[outv]", "-map", "0:a?"]
        if fps:
            cmd += ["-r", str(fps)]
    else:
        filters = [scale_filter] if scale_filter else []
        filters.append(drawtext)
        vf = ",".join(filters)
        if fps:
            cmd += ["-r", str(fps)]
        cmd += ["-vf", vf]

    crf = VIDEO_QUALITY_CRF[video_quality]
    if output_format == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0"]
        cmd += ["-c:a", "libopus", "-b:a", audio_bitrate]
    else:
        cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", str(crf)]
        cmd += ["-c:a", "aac", "-b:a", audio_bitrate]

    cmd += [dest_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg watermarking failed: {result.stderr[-2000:]}")
    return dest_path
