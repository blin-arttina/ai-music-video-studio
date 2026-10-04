"""
AI Project Memory (spec §14): assembles a short, human-readable summary
of one project's current state so the AI Assistant (Help, Lyrics,
Script/Video-plan drafts) can answer with real awareness of the project
instead of a blank slate, without the user having to type it in by hand
every time.

Deliberately privacy-conscious by default: this includes COUNTS, TITLES,
and KINDS of the project's saved text (lyrics/notes/scripts/etc.), never
the text BODIES themselves. The project's protected text is otherwise
kept private by design (see protection.py / CONTENT_PROTECTION_GUIDE.txt)
and this module doesn't change that -- it gives the assistant enough to
be useful ("you have 3 verses saved called...") without silently sending
a user's actual lyrics to an external AI provider on every question.

This function takes plain values, not SQLAlchemy model objects, so it
can be tested on its own without a database -- server.py is responsible
for pulling those values out of the real models.
"""

MAX_RECENT_TEXT_ITEMS = 5
MAX_TITLE_LEN = 80
MAX_DESCRIPTION_LEN = 300


def build_project_context(
    project_name: str,
    description: str = "",
    status: str = "",
    studio_name: str = "",
    asset_counts: dict = None,
    text_items: list = None,  # list of {"title": str, "kind": str}, most recent first
    track_count: int = 0,
    clip_count: int = 0,
    duration_seconds: float = 0.0,
) -> str:
    lines = [f'Project: "{project_name}"']
    if status:
        lines.append(f"Status: {status}")
    if description and description.strip():
        lines.append(f"Description: {description.strip()[:MAX_DESCRIPTION_LEN]}")
    if studio_name and studio_name.strip():
        lines.append(f"Studio/creator brand: {studio_name.strip()}")

    asset_counts = asset_counts or {}
    nonzero_assets = {k: v for k, v in asset_counts.items() if v}
    if nonzero_assets:
        lines.append("Media library: " + ", ".join(f"{v} {k}" for k, v in sorted(nonzero_assets.items())))
    else:
        lines.append("Media library: empty so far")

    text_items = text_items or []
    if text_items:
        recent = text_items[:MAX_RECENT_TEXT_ITEMS]
        titled = ", ".join(f'"{t["title"][:MAX_TITLE_LEN]}" ({t["kind"]})' for t in recent)
        remaining = len(text_items) - len(recent)
        more = f", and {remaining} more" if remaining > 0 else ""
        lines.append(f"Saved text ({len(text_items)} total, titles/kinds only, not the content): {titled}{more}")
    else:
        lines.append("Saved text: none yet")

    if track_count:
        lines.append(
            f"Timeline: {track_count} track(s), {clip_count} clip(s), "
            f"{duration_seconds:.1f} second(s) total so far"
        )
    else:
        lines.append("Timeline: no tracks yet")

    return "\n".join(lines)
