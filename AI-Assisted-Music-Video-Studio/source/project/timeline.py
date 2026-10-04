"""
Multi-track timeline logic: tracks for music, vocals, dialogue, sound
effects, images, video, animation, text, lyrics, and AI-generated
elements; move/resize/split/rename/lock/hide/mute/edit clips (spec §6).

This is a form-driven editor (exact start/duration/trim numbers typed or
adjusted in a field), not a drag-and-drop canvas — deliberately, since
precise numeric fields with descriptive labels are far more usable with
a screen reader than dragging a block on a canvas (spec §16).
"""

from source.project.models import Track, Clip, db

VALID_TRACK_KINDS = {
    "music", "vocals", "dialogue", "sfx", "image", "video",
    "animation", "text", "lyrics", "ai",
}


def create_track(project_id: str, name: str, kind: str) -> Track:
    kind = kind if kind in VALID_TRACK_KINDS else "music"
    next_index = db.session.query(db.func.coalesce(db.func.max(Track.order_index), -1)).filter_by(
        project_id=project_id
    ).scalar() + 1
    track = Track(project_id=project_id, name=name or "New Track", kind=kind, order_index=next_index)
    db.session.add(track)
    db.session.commit()
    return track


def reorder_track(track: Track, new_index: int) -> Track:
    track.order_index = max(0, new_index)
    db.session.commit()
    return track


def add_clip(track: Track, label: str, start_seconds: float, duration_seconds: float,
             media_asset_id: str = None, text_content_id: str = None) -> Clip:
    clip = Clip(
        track_id=track.id,
        media_asset_id=media_asset_id,
        text_content_id=text_content_id,
        label=label or "Clip",
        start_seconds=max(0.0, start_seconds),
        duration_seconds=max(0.1, duration_seconds),
    )
    db.session.add(clip)
    db.session.commit()
    return clip


def move_clip(clip: Clip, new_start_seconds: float) -> Clip:
    clip.start_seconds = max(0.0, new_start_seconds)
    db.session.commit()
    return clip


def resize_clip(clip: Clip, new_duration_seconds: float) -> Clip:
    clip.duration_seconds = max(0.1, new_duration_seconds)
    db.session.commit()
    return clip


def trim_clip(clip: Clip, trim_in: float = None, trim_out: float = None) -> Clip:
    if trim_in is not None:
        clip.trim_in_seconds = max(0.0, trim_in)
    if trim_out is not None:
        clip.trim_out_seconds = trim_out
    db.session.commit()
    return clip


def split_clip(clip: Clip, split_at_seconds: float) -> tuple:
    """
    Splits a clip into two clips at an absolute timeline position.
    Returns (left_clip, right_clip). Raises ValueError if the split
    point isn't inside the clip.
    """
    clip_end = clip.start_seconds + clip.duration_seconds
    if not (clip.start_seconds < split_at_seconds < clip_end):
        raise ValueError("Split point must fall strictly inside the clip.")

    offset_into_clip = split_at_seconds - clip.start_seconds
    original_duration = clip.duration_seconds

    # Shrink the original clip to become the left half.
    clip.duration_seconds = offset_into_clip
    if clip.trim_out_seconds is not None:
        pass  # left half keeps existing trim_in; trim_out recalculated below
    left_trim_out = clip.trim_in_seconds + offset_into_clip

    right_clip = Clip(
        track_id=clip.track_id,
        media_asset_id=clip.media_asset_id,
        text_content_id=clip.text_content_id,
        label=f"{clip.label} (cont.)",
        start_seconds=split_at_seconds,
        duration_seconds=original_duration - offset_into_clip,
        trim_in_seconds=left_trim_out,
        trim_out_seconds=clip.trim_out_seconds,
        volume=clip.volume,
        muted=clip.muted,
        locked=clip.locked,
    )
    clip.trim_out_seconds = left_trim_out
    db.session.add(right_clip)
    db.session.commit()
    return clip, right_clip


def delete_clip(clip: Clip):
    db.session.delete(clip)
    db.session.commit()


def set_clip_flags(clip: Clip, muted: bool = None, locked: bool = None) -> Clip:
    if muted is not None:
        clip.muted = muted
    if locked is not None:
        clip.locked = locked
    db.session.commit()
    return clip


def set_track_flags(track: Track, muted: bool = None, locked: bool = None, hidden: bool = None) -> Track:
    if muted is not None:
        track.muted = muted
    if locked is not None:
        track.locked = locked
    if hidden is not None:
        track.hidden = hidden
    db.session.commit()
    return track


def project_duration_seconds(tracks) -> float:
    """The overall timeline length: the furthest clip end across all tracks."""
    end = 0.0
    for track in tracks:
        for clip in track.clips:
            end = max(end, clip.start_seconds + clip.duration_seconds)
    return end
