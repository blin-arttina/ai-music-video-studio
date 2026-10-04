"""
AI Modules: Music, Lyrics, Voice, Video, Image, Animation, Script,
Project Manager, and Help Assistant.

Each module is a real, callable function with a real API route in front
of it (see server.py). None of them fabricate output: if no provider API
key is configured for a module, it returns a clear "not connected"
result instead of pretending to generate something. This keeps the app
honest and makes it a one-line job to wire in a real provider later —
add the key as an environment variable and fill in the marked section.

Lyrics/script/help text assistance can run today using the same Claude
API key this workspace already uses for such tasks, if ANTHROPIC_API_KEY
is set in the environment — that module is the one exception with a
working default implementation.

AI Voice is a second working implementation, but a self-hosted one: it
uses Chatterbox (resemble-ai/chatterbox, MIT-licensed, free) instead of a
paid API. There is no account or key to configure -- the only
requirement is that the `chatterbox-tts` package (and PyTorch) be
installed on whatever server actually runs this app. This sandbox can't
install those (no working pip/network access to fetch them, confirmed
directly), so this module can be written and unit-tested against a stand-
in for the real package, but not run end-to-end here -- see
PROJECT_NOTES.txt for exactly what that means and how to finish setting
it up on a real host.
"""

import os
import uuid
from pathlib import Path

from config import get_config

CONFIG = get_config()

NOT_CONNECTED = "not_connected"
OK = "ok"

# Lazily-loaded Chatterbox model, kept in memory after the first
# successful load so repeated AI Voice calls don't reload it (loading is
# slow and, on first run, downloads the model weights).
_CHATTERBOX_MODEL = None
_CHATTERBOX_LOAD_ERROR = None


def _get_chatterbox_model():
    """Returns a loaded Chatterbox model, or None if the package isn't
    installed / failed to load. Only ever attempts the load once per
    process -- if it fails, later calls get the same cached failure
    instead of retrying (and re-failing) every time."""
    global _CHATTERBOX_MODEL, _CHATTERBOX_LOAD_ERROR
    if _CHATTERBOX_MODEL is not None:
        return _CHATTERBOX_MODEL
    if _CHATTERBOX_LOAD_ERROR is not None:
        return None
    try:
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        _CHATTERBOX_MODEL = ChatterboxTurboTTS.from_pretrained(
            device=CONFIG.CHATTERBOX_DEVICE, nano=CONFIG.CHATTERBOX_NANO,
        )
        return _CHATTERBOX_MODEL
    except Exception as exc:  # noqa: BLE001 -- package missing, bad device, etc.
        _CHATTERBOX_LOAD_ERROR = str(exc)
        return None


def _not_connected(module: str, needs: str) -> dict:
    return {
        "status": NOT_CONNECTED,
        "module": module,
        "message": (
            f"The {module} module isn't connected to a generation provider yet. "
            f"Add {needs} as an environment variable on the server to enable it."
        ),
    }


# --------------------------------------------------------------------
# AI Music Module
# --------------------------------------------------------------------

def generate_music(prompt: str, genre: str = "", mood: str = "", tempo: int = None, key: str = "") -> dict:
    if not CONFIG.AI_MUSIC_PROVIDER_API_KEY:
        return _not_connected("AI Music", "AI_MUSIC_PROVIDER_API_KEY (e.g. from a music-generation provider)")
    # --- Wire a real provider here, e.g.: ---
    # response = requests.post("https://api.<provider>.com/generate", ...)
    # return {"status": OK, "audio_url": response.json()["url"]}
    return _not_connected("AI Music", "AI_MUSIC_PROVIDER_API_KEY")


# --------------------------------------------------------------------
# AI Lyrics / Script / Help Module (text assistance)
# --------------------------------------------------------------------

def _anthropic_text_complete(system_prompt: str, user_prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in message.content if hasattr(block, "text"))


def generate_lyrics(idea: str, genre: str = "", mood: str = "", structure: str = "", project_context: str = "") -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or CONFIG.AI_TEXT_PROVIDER_API_KEY
    if not api_key:
        return _not_connected("AI Lyrics", "ANTHROPIC_API_KEY or AI_TEXT_PROVIDER_API_KEY")
    try:
        os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
        context_block = f"Project context (for awareness only -- don't just restate it):\n{project_context}\n\n" if project_context else ""
        text = _anthropic_text_complete(
            "You are a songwriting assistant. Write original song lyrics only. "
            "Keep the creator fully in control: offer the material as a draft, "
            "not a finished decision. Use the project context to stay consistent "
            "with what the creator has already saved (mood, existing verses, "
            "etc.) when it's relevant, but don't quote or assume the content of "
            "text items you haven't been shown directly.",
            f"{context_block}Idea: {idea}\nGenre: {genre}\nMood: {mood}\nStructure: {structure or 'verse/chorus/verse/chorus/bridge/chorus'}",
        )
        return {"status": OK, "lyrics": text}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}


def generate_script(concept: str, scene_count: int = 3, project_context: str = "") -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or CONFIG.AI_TEXT_PROVIDER_API_KEY
    if not api_key:
        return _not_connected("AI Script", "ANTHROPIC_API_KEY or AI_TEXT_PROVIDER_API_KEY")
    try:
        os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
        context_block = f"Project context (for awareness only -- don't just restate it):\n{project_context}\n\n" if project_context else ""
        text = _anthropic_text_complete(
            "You are a video/animation scriptwriting assistant. Produce a scene "
            "list with brief descriptions, not final prose the user hasn't asked for.",
            f"{context_block}Concept: {concept}\nNumber of scenes: {scene_count}",
        )
        return {"status": OK, "script": text}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}


def help_assistant(question: str, project_context: str = "") -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or CONFIG.AI_TEXT_PROVIDER_API_KEY
    if not api_key:
        return _not_connected("AI Help Assistant", "ANTHROPIC_API_KEY or AI_TEXT_PROVIDER_API_KEY")
    try:
        os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
        text = _anthropic_text_complete(
            "You are the in-app help assistant for an accessible music/video "
            "creation studio. Answer clearly and briefly; suggest, never take "
            "control of the user's project. The project context lists counts, "
            "titles, and kinds of what the creator has saved -- not the actual "
            "content of their text items -- so don't claim to know what's "
            "written inside them.",
            f"Project context: {project_context}\nQuestion: {question}",
        )
        return {"status": OK, "answer": text}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}


# --------------------------------------------------------------------
# AI Voice Module (self-hosted Chatterbox -- see module docstring)
# --------------------------------------------------------------------

def generate_voice(text: str, reference_audio_path: str = None,
                    exaggeration: float = 0.5, cfg_weight: float = 0.5,
                    out_dir: str = None) -> dict:
    """Generates speech for `text`.

    If `reference_audio_path` points to a real audio file (e.g. a voice
    recording already in the project's Media Library), Chatterbox clones
    that voice from it (about 10 seconds of clean speech is enough).
    Without one, it falls back to the model's own built-in default voice
    -- still real generation, just not a cloned voice.

    Returns {"status": "ok", "audio_path": "<wav file written to out_dir>"}
    on success, or a "not_connected"/"error" status dict otherwise -- the
    same honest shape every other AI module in this app uses.
    """
    model = _get_chatterbox_model()
    if model is None:
        return _not_connected(
            "AI Voice",
            "the chatterbox-tts package (and PyTorch) on the server -- run "
            "`pip install chatterbox-tts` where this app is hosted, then "
            "restart it. No account or API key is needed, this runs "
            f"locally. (Load attempt failed with: {_CHATTERBOX_LOAD_ERROR})"
            if _CHATTERBOX_LOAD_ERROR else
            "the chatterbox-tts package (and PyTorch) on the server -- run "
            "`pip install chatterbox-tts` where this app is hosted, then "
            "restart it. No account or API key is needed, this runs locally.",
        )
    if not text or not text.strip():
        return {"status": "error", "message": "No text was given to speak."}
    try:
        import torchaudio as ta
        kwargs = {"exaggeration": exaggeration, "cfg_weight": cfg_weight}
        if reference_audio_path:
            kwargs["audio_prompt_path"] = reference_audio_path
        wav = model.generate(text, **kwargs)
        dest_dir = Path(out_dir) if out_dir else Path(".")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{uuid.uuid4().hex}-ai-voice.wav"
        ta.save(str(dest_path), wav, model.sr)
        return {
            "status": OK,
            "audio_path": str(dest_path),
            "cloned": bool(reference_audio_path),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}


# --------------------------------------------------------------------
# AI Image / Animation / Video Modules
# --------------------------------------------------------------------

def generate_image(prompt: str, style: str = "") -> dict:
    if not CONFIG.AI_IMAGE_PROVIDER_API_KEY:
        return _not_connected("AI Image", "AI_IMAGE_PROVIDER_API_KEY")
    return _not_connected("AI Image", "AI_IMAGE_PROVIDER_API_KEY")


def generate_animation(prompt: str, duration_seconds: int = 5) -> dict:
    if not CONFIG.AI_VIDEO_PROVIDER_API_KEY:
        return _not_connected("AI Animation", "AI_VIDEO_PROVIDER_API_KEY")
    return _not_connected("AI Animation", "AI_VIDEO_PROVIDER_API_KEY")


def generate_video_plan(concept: str, project_context: str = "") -> dict:
    """Video *planning* (concepts, scene lists, production plans) uses the
    same text assistant as scripts — this doesn't need a video-generation
    provider, only a text one."""
    return generate_script(concept, scene_count=5, project_context=project_context)


# --------------------------------------------------------------------
# AI Project Manager Module
# --------------------------------------------------------------------

def project_manager_summary(project_name: str, asset_counts: dict, text_count: int) -> dict:
    """Local, deterministic summary — no external AI needed for this one."""
    parts = [f'Project "{project_name}"']
    if asset_counts:
        parts.append(", ".join(f"{v} {k}" for k, v in asset_counts.items() if v))
    parts.append(f"{text_count} protected text item(s)")
    return {"status": OK, "summary": " — ".join(parts)}
