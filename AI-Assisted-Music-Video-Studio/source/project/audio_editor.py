"""
Audio editing engine (spec §5): trim, fade, volume, and effects
(equalization, reverb, echo, compression, noise reduction, pitch),
built entirely on ffmpeg's audio filters so it needs no extra Python
audio library — just the same ffmpeg binary already used for video
watermarking.

Each function is a thin, testable wrapper around one ffmpeg filter.
`render_clip_audio` composes all of a clip's settings (trim, fades,
volume, effects) into a single ffmpeg call, so processing a clip is one
fast pass over the file rather than several lossy re-encodes stacked
on top of each other.
"""

import shutil
import subprocess
from pathlib import Path


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


class AudioEditError(RuntimeError):
    pass


def _run_ffmpeg(args: list):
    if not ffmpeg_available():
        raise AudioEditError("ffmpeg is not installed on this server.")
    cmd = ["ffmpeg", "-y"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioEditError(f"ffmpeg audio processing failed: {result.stderr[-2000:]}")


def build_audio_filter_chain(
    volume: float = 1.0,
    fade_in_seconds: float = 0.0,
    fade_out_seconds: float = 0.0,
    clip_duration_seconds: float = None,
    eq_low_db: float = 0.0,
    eq_mid_db: float = 0.0,
    eq_high_db: float = 0.0,
    reverb_amount: float = 0.0,     # 0.0 (none) - 1.0 (heavy)
    echo_amount: float = 0.0,       # 0.0 (none) - 1.0 (heavy)
    compression: float = 0.0,       # 0.0 (none) - 1.0 (heavy)
    noise_reduction: float = 0.0,   # 0.0 (none) - 1.0 (heavy)
    pitch_semitones: float = 0.0,   # -12 to +12
) -> str:
    """Builds an ffmpeg -af filter chain string from clip/effect settings.
    Every parameter is optional and defaults to a no-op, so callers only
    pay for the effects they actually turn on."""
    filters = []

    volume = max(0.0, min(2.0, volume))
    if volume != 1.0:
        filters.append(f"volume={volume:.3f}")

    if eq_low_db or eq_mid_db or eq_high_db:
        # Three-band EQ approximated with parametric equalizer filters
        # centered on typical low/mid/high bands.
        if eq_low_db:
            filters.append(f"equalizer=f=100:t=q:w=1:g={eq_low_db:.1f}")
        if eq_mid_db:
            filters.append(f"equalizer=f=1000:t=q:w=1:g={eq_mid_db:.1f}")
        if eq_high_db:
            filters.append(f"equalizer=f=8000:t=q:w=1:g={eq_high_db:.1f}")

    if noise_reduction > 0:
        # afftdn's noise floor reduction strength scales roughly 0-97 (dB-ish)
        strength = max(0.01, min(0.97, noise_reduction)) * 40
        filters.append(f"afftdn=nr={strength:.1f}")

    if compression > 0:
        # acompressor: heavier setting = lower threshold + higher ratio
        threshold = 1.0 - 0.7 * max(0.0, min(1.0, compression))
        ratio = 2 + 8 * max(0.0, min(1.0, compression))
        filters.append(f"acompressor=threshold={threshold:.2f}:ratio={ratio:.1f}:attack=20:release=250")

    if pitch_semitones:
        # Pitch shift without changing tempo: resample then correct speed back.
        semitone_ratio = 2 ** (pitch_semitones / 12.0)
        filters.append(f"asetrate=44100*{semitone_ratio:.5f},aresample=44100,atempo={1/semitone_ratio:.5f}")

    if echo_amount > 0:
        amt = max(0.0, min(1.0, echo_amount))
        decay = 0.3 + 0.5 * amt
        filters.append(f"aecho=0.8:0.9:{int(60 + 400 * amt)}:{decay:.2f}")

    if reverb_amount > 0:
        # Reverb approximated with layered short echoes (no external IR needed).
        amt = max(0.0, min(1.0, reverb_amount))
        filters.append(
            f"aecho=0.8:0.88:{int(40 + 120 * amt)}|{int(80 + 200 * amt)}:{0.25*amt:.2f}|{0.18*amt:.2f}"
        )

    if fade_in_seconds > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in_seconds:.2f}")

    if fade_out_seconds > 0 and clip_duration_seconds:
        fade_start = max(0.0, clip_duration_seconds - fade_out_seconds)
        filters.append(f"afade=t=out:st={fade_start:.2f}:d={fade_out_seconds:.2f}")

    return ",".join(filters) if filters else "anull"


def trim_audio(source_path: str, dest_path: str, start_seconds: float, end_seconds: float = None):
    """Cuts [start_seconds, end_seconds) out of the source file. end_seconds=None means to the end."""
    args = ["-i", source_path, "-ss", f"{max(0.0, start_seconds):.3f}"]
    if end_seconds is not None:
        duration = max(0.01, end_seconds - start_seconds)
        args += ["-t", f"{duration:.3f}"]
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    args += ["-c:a", "pcm_s16le" if dest_path.endswith(".wav") else "aac", dest_path]
    _run_ffmpeg(args)
    return dest_path


def render_clip_audio(
    source_path: str,
    dest_path: str,
    trim_in_seconds: float = 0.0,
    trim_out_seconds: float = None,
    volume: float = 1.0,
    fade_in_seconds: float = 0.0,
    fade_out_seconds: float = 0.0,
    eq_low_db: float = 0.0,
    eq_mid_db: float = 0.0,
    eq_high_db: float = 0.0,
    reverb_amount: float = 0.0,
    echo_amount: float = 0.0,
    compression: float = 0.0,
    noise_reduction: float = 0.0,
    pitch_semitones: float = 0.0,
) -> str:
    """
    Applies a clip's trim, volume, fades, and effects to its source media
    in a single ffmpeg pass and writes the result to dest_path.
    """
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

    duration = None
    if trim_out_seconds is not None:
        duration = max(0.01, trim_out_seconds - trim_in_seconds)

    filter_chain = build_audio_filter_chain(
        volume=volume, fade_in_seconds=fade_in_seconds, fade_out_seconds=fade_out_seconds,
        clip_duration_seconds=duration, eq_low_db=eq_low_db, eq_mid_db=eq_mid_db, eq_high_db=eq_high_db,
        reverb_amount=reverb_amount, echo_amount=echo_amount, compression=compression,
        noise_reduction=noise_reduction, pitch_semitones=pitch_semitones,
    )

    args = ["-i", source_path, "-ss", f"{max(0.0, trim_in_seconds):.3f}"]
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]
    args += ["-af", filter_chain]
    args += ["-c:a", "pcm_s16le" if dest_path.endswith(".wav") else "aac", dest_path]

    _run_ffmpeg(args)
    return dest_path


def crossfade_audio(path_a: str, path_b: str, dest_path: str, duration_seconds: float = 1.0) -> str:
    """
    Joins two audio clips end-to-end with a crossfade transition between
    them, using ffmpeg's acrossfade filter: the tail of A fades out while
    the head of B fades in, over `duration_seconds`.
    """
    duration_seconds = max(0.1, min(10.0, duration_seconds))
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-i", path_a, "-i", path_b,
        "-filter_complex", f"[0:a][1:a]acrossfade=d={duration_seconds:.2f}:c1=tri:c2=tri",
        "-c:a", "pcm_s16le" if dest_path.endswith(".wav") else "aac",
        dest_path,
    ]
    _run_ffmpeg(args)
    return dest_path


def get_audio_duration_seconds(path: str) -> float:
    """Reads a media file's duration using ffprobe (ships alongside ffmpeg)."""
    if not shutil.which("ffprobe"):
        raise AudioEditError("ffprobe is not installed on this server.")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AudioEditError(f"ffprobe failed: {result.stderr[-500:]}")
    return float(result.stdout.strip())
