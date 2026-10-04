"""
Video editing engine (spec §7): trim, crop, rotate, fade, and a text
caption/overlay, built on ffmpeg the same way audio_editor.py builds on
it for audio — one composed filter chain per render rather than
several stacked re-encodes.

This is deliberately separate from the required watermarking in
protection.py: editing (this module) shapes the footage; watermarking
is the mandatory protection step applied at export time (spec §8). A
clip can be edited and re-edited freely without ever touching the
watermark logic, and the final "Export With Watermark" step (already
built) still runs on top of whatever this module produces.
"""

import shutil
import subprocess
from pathlib import Path


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


class VideoEditError(RuntimeError):
    pass


def _run_ffmpeg(args: list):
    if not ffmpeg_available():
        raise VideoEditError("ffmpeg is not installed on this server.")
    cmd = ["ffmpeg", "-y"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VideoEditError(f"ffmpeg video processing failed: {result.stderr[-2000:]}")


VALID_ROTATIONS = {0, 90, 180, 270}
VALID_CAPTION_POSITIONS = {"top", "center", "bottom"}


def _rotation_filter(rotation_degrees: int) -> str:
    rotation_degrees = rotation_degrees % 360
    if rotation_degrees == 90:
        return "transpose=1"
    if rotation_degrees == 180:
        return "transpose=1,transpose=1"
    if rotation_degrees == 270:
        return "transpose=2"
    return ""


def _crop_filter(crop_x: float, crop_y: float, crop_width: float, crop_height: float) -> str:
    """Crop expressed as fractions (0.0-1.0) of the frame, so it stays
    correct regardless of the source resolution."""
    crop_x = max(0.0, min(1.0, crop_x))
    crop_y = max(0.0, min(1.0, crop_y))
    crop_width = max(0.05, min(1.0 - crop_x, crop_width))
    crop_height = max(0.05, min(1.0 - crop_y, crop_height))
    if crop_x == 0 and crop_y == 0 and crop_width == 1.0 and crop_height == 1.0:
        return ""
    return f"crop=iw*{crop_width:.4f}:ih*{crop_height:.4f}:iw*{crop_x:.4f}:ih*{crop_y:.4f}"


def _caption_filter(caption_text: str, position: str = "bottom") -> str:
    if not caption_text:
        return ""
    position = position if position in VALID_CAPTION_POSITIONS else "bottom"
    safe_text = caption_text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")
    pos_expr = {
        "top": "x=(w-tw)/2:y=40",
        "center": "x=(w-tw)/2:y=(h-th)/2",
        "bottom": "x=(w-tw)/2:y=h-th-40",
    }[position]
    return (
        f"drawtext=text='{safe_text}':fontcolor=white:fontsize=h/18:"
        f"box=1:boxcolor=black@0.6:boxborderw=8:{pos_expr}"
    )


def build_video_filter_chain(
    crop_x: float = 0.0, crop_y: float = 0.0, crop_width: float = 1.0, crop_height: float = 1.0,
    rotation_degrees: int = 0,
    fade_in_seconds: float = 0.0, fade_out_seconds: float = 0.0,
    clip_duration_seconds: float = None,
    caption_text: str = "", caption_position: str = "bottom",
) -> str:
    """Builds an ffmpeg -vf filter chain from a clip's edit settings.
    Every parameter defaults to a no-op."""
    filters = []

    crop = _crop_filter(crop_x, crop_y, crop_width, crop_height)
    if crop:
        filters.append(crop)

    rotation = _rotation_filter(rotation_degrees if rotation_degrees in VALID_ROTATIONS else 0)
    if rotation:
        filters.append(rotation)

    caption = _caption_filter(caption_text, caption_position)
    if caption:
        filters.append(caption)

    if fade_in_seconds > 0:
        filters.append(f"fade=t=in:st=0:d={fade_in_seconds:.2f}")

    if fade_out_seconds > 0 and clip_duration_seconds:
        fade_start = max(0.0, clip_duration_seconds - fade_out_seconds)
        filters.append(f"fade=t=out:st={fade_start:.2f}:d={fade_out_seconds:.2f}")

    return ",".join(filters) if filters else "null"


def render_clip_video(
    source_path: str,
    dest_path: str,
    trim_in_seconds: float = 0.0,
    trim_out_seconds: float = None,
    crop_x: float = 0.0, crop_y: float = 0.0, crop_width: float = 1.0, crop_height: float = 1.0,
    rotation_degrees: int = 0,
    fade_in_seconds: float = 0.0, fade_out_seconds: float = 0.0,
    caption_text: str = "", caption_position: str = "bottom",
    mute: bool = False,
) -> str:
    """
    Applies a clip's trim, crop, rotation, fades, and caption to its
    source video in a single ffmpeg pass and writes the result to
    dest_path. Does NOT apply the required watermark — that stays a
    separate, mandatory step at export time (see source/project/
    protection.py's watermark_video), so editing never accidentally
    skips it.
    """
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

    duration = None
    if trim_out_seconds is not None:
        duration = max(0.01, trim_out_seconds - trim_in_seconds)

    filter_chain = build_video_filter_chain(
        crop_x=crop_x, crop_y=crop_y, crop_width=crop_width, crop_height=crop_height,
        rotation_degrees=rotation_degrees, fade_in_seconds=fade_in_seconds, fade_out_seconds=fade_out_seconds,
        clip_duration_seconds=duration, caption_text=caption_text, caption_position=caption_position,
    )

    args = ["-i", source_path, "-ss", f"{max(0.0, trim_in_seconds):.3f}"]
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]
    args += ["-vf", filter_chain]
    if mute:
        args += ["-an"]
    else:
        args += ["-c:a", "aac"]
    args += ["-c:v", "libx264", "-preset", "fast", dest_path]

    _run_ffmpeg(args)
    return dest_path


VALID_TRANSITION_STYLES = {
    "fade", "wipeleft", "wiperight", "slideleft", "slideright", "dissolve",
}


def crossfade_video(
    path_a: str, path_b: str, dest_path: str,
    duration_seconds: float = 1.0, style: str = "fade",
) -> str:
    """
    Joins two video clips end-to-end with a real crossfade transition
    (ffmpeg's xfade filter), with the audio crossfaded to match via
    acrossfade in the same pass. xfade needs both inputs at the same
    resolution/frame rate, so both are normalized to clip A's dimensions
    and a common frame rate first.
    """
    duration_seconds = max(0.1, min(10.0, duration_seconds))
    style = style if style in VALID_TRANSITION_STYLES else "fade"
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

    width, height = get_video_dimensions(path_a)
    duration_a = get_video_duration_seconds(path_a)
    offset = max(0.0, duration_a - duration_seconds)

    filter_complex = (
        f"[0:v]scale={width}:{height},setsar=1,fps=30[v0];"
        f"[1:v]scale={width}:{height},setsar=1,fps=30[v1];"
        f"[v0][v1]xfade=transition={style}:duration={duration_seconds:.2f}:offset={offset:.2f}[v];"
        f"[0:a][1:a]acrossfade=d={duration_seconds:.2f}:c1=tri:c2=tri[a]"
    )

    args = [
        "-i", path_a, "-i", path_b,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
        dest_path,
    ]
    _run_ffmpeg(args)
    return dest_path


def get_video_duration_seconds(path: str) -> float:
    if not shutil.which("ffprobe"):
        raise VideoEditError("ffprobe is not installed on this server.")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise VideoEditError(f"ffprobe failed: {result.stderr[-500:]}")
    return float(result.stdout.strip())


def get_video_dimensions(path: str) -> tuple:
    if not shutil.which("ffprobe"):
        raise VideoEditError("ffprobe is not installed on this server.")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise VideoEditError(f"ffprobe failed: {result.stderr[-500:]}")
    width_str, height_str = result.stdout.strip().split("x")
    return int(width_str), int(height_str)
