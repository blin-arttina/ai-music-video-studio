"""
Timeline undo/redo (spec §17): every action that changes the Timeline's
structure (adding, moving, resizing, trimming, splitting, or deleting a
clip; creating, renaming, reordering, or deleting a track; muting/
locking/hiding either one) snapshots the timeline's state first, so it
can be undone, and undoing pushes the state it replaces onto a redo
stack so it can be redone.

This deliberately covers the Timeline only. The Music & Text Studio
already has its own append-only version history (TextContent /
TextRevision, with a "Restore" endpoint) that serves the same purpose
for text, and layering this mechanism on top of that one would just be
two competing sources of truth for the same content.

Design: rather than a single growing log of individual actions (which
would need every action type to know how to reverse itself), each
project keeps two small stacks of FULL timeline snapshots -- undo_stack
and redo_stack -- stored as JSON on a TimelineHistory row. Undoing pops
the most recent undo snapshot, restores it, and pushes the state it
just replaced onto the redo stack; redoing does the mirror image. A new
action clears the redo stack, matching how undo/redo works in ordinary
editors (you can't redo past a fresh edit). Both stacks are capped at
MAX_HISTORY_DEPTH entries so they can't grow without bound in a long
editing session.
"""

import json

from source.project.models import db, Track, Clip

MAX_HISTORY_DEPTH = 50


class NothingToUndoError(RuntimeError):
    pass


class NothingToRedoError(RuntimeError):
    pass


def _clip_snapshot(clip: Clip) -> dict:
    return {
        "id": clip.id,
        "media_asset_id": clip.media_asset_id,
        "text_content_id": clip.text_content_id,
        "label": clip.label,
        "start_seconds": clip.start_seconds,
        "duration_seconds": clip.duration_seconds,
        "trim_in_seconds": clip.trim_in_seconds,
        "trim_out_seconds": clip.trim_out_seconds,
        "volume": clip.volume,
        "fade_in_seconds": clip.fade_in_seconds,
        "fade_out_seconds": clip.fade_out_seconds,
        "muted": clip.muted,
        "locked": clip.locked,
        "eq_low_db": clip.eq_low_db,
        "eq_mid_db": clip.eq_mid_db,
        "eq_high_db": clip.eq_high_db,
        "reverb_amount": clip.reverb_amount,
        "echo_amount": clip.echo_amount,
        "compression": clip.compression,
        "noise_reduction": clip.noise_reduction,
        "pitch_semitones": clip.pitch_semitones,
        "crop_x": clip.crop_x,
        "crop_y": clip.crop_y,
        "crop_width": clip.crop_width,
        "crop_height": clip.crop_height,
        "rotation_degrees": clip.rotation_degrees,
        "caption_text": clip.caption_text,
        "caption_position": clip.caption_position,
    }


def _track_snapshot(track: Track) -> dict:
    return {
        "id": track.id,
        "name": track.name,
        "kind": track.kind,
        "order_index": track.order_index,
        "muted": track.muted,
        "locked": track.locked,
        "hidden": track.hidden,
        "clips": [_clip_snapshot(c) for c in track.clips],
    }


def snapshot_timeline(project_id: str) -> list:
    tracks = Track.query.filter_by(project_id=project_id).order_by(Track.order_index).all()
    return [_track_snapshot(t) for t in tracks]


def _restore_timeline(project_id: str, snapshot: list):
    """Replaces every track/clip on this project with the given
    snapshot, re-using the original ids so nothing else that might
    reference a track or clip id is left dangling."""
    Track.query.filter_by(project_id=project_id).delete()
    db.session.flush()
    for track_data in snapshot:
        track = Track(
            id=track_data["id"], project_id=project_id, name=track_data["name"],
            kind=track_data["kind"], order_index=track_data["order_index"],
            muted=track_data["muted"], locked=track_data["locked"], hidden=track_data["hidden"],
        )
        db.session.add(track)
        for clip_data in track_data["clips"]:
            clip_fields = {k: v for k, v in clip_data.items() if k != "id"}
            clip = Clip(id=clip_data["id"], track_id=track.id, **clip_fields)
            db.session.add(clip)
    db.session.commit()


def _get_or_create_history(project_id: str):
    # Imported lazily to avoid a circular import at module load time.
    from source.project.models import TimelineHistory

    history = TimelineHistory.query.filter_by(project_id=project_id).first()
    if not history:
        history = TimelineHistory(project_id=project_id, undo_stack_json="[]", redo_stack_json="[]")
        db.session.add(history)
        db.session.commit()
    return history


def record_action(project_id: str):
    """Call this BEFORE applying a timeline-mutating change: snapshots
    the current (pre-change) state onto the undo stack, and clears the
    redo stack, since a fresh action invalidates whatever could have
    been redone."""
    history = _get_or_create_history(project_id)
    undo_stack = json.loads(history.undo_stack_json or "[]")
    undo_stack.append(snapshot_timeline(project_id))
    if len(undo_stack) > MAX_HISTORY_DEPTH:
        undo_stack = undo_stack[-MAX_HISTORY_DEPTH:]
    history.undo_stack_json = json.dumps(undo_stack)
    history.redo_stack_json = "[]"
    db.session.commit()


def undo(project_id: str):
    history = _get_or_create_history(project_id)
    undo_stack = json.loads(history.undo_stack_json or "[]")
    if not undo_stack:
        raise NothingToUndoError("Nothing to undo.")

    redo_stack = json.loads(history.redo_stack_json or "[]")
    redo_stack.append(snapshot_timeline(project_id))
    if len(redo_stack) > MAX_HISTORY_DEPTH:
        redo_stack = redo_stack[-MAX_HISTORY_DEPTH:]

    previous_state = undo_stack.pop()
    history.undo_stack_json = json.dumps(undo_stack)
    history.redo_stack_json = json.dumps(redo_stack)
    db.session.commit()

    _restore_timeline(project_id, previous_state)


def redo(project_id: str):
    history = _get_or_create_history(project_id)
    redo_stack = json.loads(history.redo_stack_json or "[]")
    if not redo_stack:
        raise NothingToRedoError("Nothing to redo.")

    undo_stack = json.loads(history.undo_stack_json or "[]")
    undo_stack.append(snapshot_timeline(project_id))
    if len(undo_stack) > MAX_HISTORY_DEPTH:
        undo_stack = undo_stack[-MAX_HISTORY_DEPTH:]

    next_state = redo_stack.pop()
    history.undo_stack_json = json.dumps(undo_stack)
    history.redo_stack_json = json.dumps(redo_stack)
    db.session.commit()

    _restore_timeline(project_id, next_state)


def history_status(project_id: str) -> dict:
    from source.project.models import TimelineHistory

    history = TimelineHistory.query.filter_by(project_id=project_id).first()
    if not history:
        return {"can_undo": False, "can_redo": False}
    undo_stack = json.loads(history.undo_stack_json or "[]")
    redo_stack = json.loads(history.redo_stack_json or "[]")
    return {"can_undo": len(undo_stack) > 0, "can_redo": len(redo_stack) > 0}
