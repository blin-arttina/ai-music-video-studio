"""
Optional invisible/forensic watermarking -- one tier beyond the always-on
VISIBLE text+logo watermark in protection.py. This is opt-in and additive:
turning it on never replaces or weakens the visible mark, and it's off by
default everywhere it appears.

Two different techniques are used, chosen for what's actually achievable
with only Pillow and ffmpeg (no specialized audio/video watermarking
library is available in this build environment), and each is documented
here honestly rather than oversold:

  IMAGES -- real steganography. A short JSON payload (who made this, the
  project name, and the original file's content hash) is hidden in the
  least-significant bit of every RGB value, which is invisible to the eye
  but recoverable later with extract_invisible_watermark_image(). This
  genuinely hides data in the pixels themselves. Its real limitation: it
  is FRAGILE. It only survives in a losslessly-saved PNG that is never
  resized, recompressed, or re-saved as JPEG -- any of those silently
  destroy it, whether the person doing it means to strip a watermark or
  is just resizing a photo for a website.

  AUDIO/VIDEO -- ffmpeg metadata tagging, not steganography. The same
  JSON payload is attached as a metadata tag via a stream copy (no
  re-encoding, so playback quality is untouched). This is NOT hidden in
  the actual audio/video signal, and it is NOT resistant to tampering:
  deleting metadata, converting the file to a different format, or many
  ordinary editing tools will strip it in one step. It's offered as a
  basic, easy "invisible" marker for casual reuse -- not a forensic-grade
  watermark. Genuine audio/video forensic watermarking embeds the payload
  in the signal itself (e.g. spread-spectrum techniques in the frequency
  domain), which needs specialized DSP tooling this ffmpeg-only pipeline
  doesn't have. This limitation is shown in the app's UI, not just here,
  so nobody relies on it for more protection than it actually gives.

  Confirmed by direct testing: MP4/MOV's muxer silently drops an unknown
  metadata key unless `-movflags use_metadata_tags` is passed (handled
  below); WebM/Matroska keeps a custom tag with no extra flag needed;
  and a plain WAV file's container has no format-level tag storage at
  all, so this only applies to this app's actual VIDEO exports (MP4/
  WebM), not to raw uploaded/recorded audio files.
"""

import json
import subprocess
from pathlib import Path

METADATA_TAG_KEY = "ownership_watermark"


def build_payload(owner: str, project_name: str, content_hash: str = "") -> str:
    return json.dumps({
        "owner": owner,
        "project": project_name,
        "content_hash": content_hash,
    })


# ------------------------------------------------------------------
# Images: LSB steganography (needs numpy + Pillow, both already used
# elsewhere in this app's image pipeline).
# ------------------------------------------------------------------

def _bits_from_bytes(data: bytes):
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def _bytes_from_bits(bits) -> bytes:
    out = bytearray()
    for i in range(0, len(bits) - 7, 8):
        value = 0
        for j in range(8):
            value = (value << 1) | bits[i + j]
        out.append(value)
    return bytes(out)


def embed_invisible_watermark_image(image_path, payload: str, out_path=None) -> str:
    """Writes `payload` into the LSBs of every RGB value of the image and
    saves the result as a PNG (the only lossless format this app exports
    to). Raises ValueError if out_path isn't a .png path, or if the image
    is too small to hold the payload -- callers should surface these as
    plain error messages, not let them propagate as a crash."""
    from PIL import Image
    import numpy as np

    out_path = str(out_path or image_path)
    if Path(out_path).suffix.lower() != ".png":
        raise ValueError(
            "An invisible watermark only survives in a lossless PNG file -- "
            "choose PNG as the export format to use this, or turn the invisible "
            "watermark off."
        )

    img = Image.open(image_path).convert("RGB")
    arr = np.array(img)
    flat = arr.reshape(-1).copy()

    payload_bytes = payload.encode("utf-8")
    header = len(payload_bytes).to_bytes(4, "big")
    bits = _bits_from_bytes(header + payload_bytes)

    if len(bits) > flat.size:
        raise ValueError("This image is too small to hold the invisible watermark payload.")

    for i, bit in enumerate(bits):
        flat[i] = (int(flat[i]) & 0xFE) | bit

    out_arr = flat.reshape(arr.shape).astype("uint8")
    Image.fromarray(out_arr, "RGB").save(out_path, format="PNG")
    return out_path


def extract_invisible_watermark_image(image_path):
    """Returns the hidden payload string if one is found, else None. Never
    raises -- an image with no watermark, or one that's been resized/
    recompressed since embedding, just comes back as None."""
    from PIL import Image
    import numpy as np

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception:
        return None

    arr = np.array(img)
    flat = arr.reshape(-1)
    if flat.size < 32:
        return None

    header_bits = [int(v) & 1 for v in flat[:32]]
    length = int.from_bytes(_bytes_from_bits(header_bits), "big")
    if length <= 0 or length > 10_000 or (32 + length * 8) > flat.size:
        return None

    payload_bits = [int(v) & 1 for v in flat[32:32 + length * 8]]
    payload_bytes = _bytes_from_bits(payload_bits)
    try:
        return payload_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ------------------------------------------------------------------
# Audio/video: ffmpeg metadata tagging (stream copy, no re-encode).
# ------------------------------------------------------------------

def embed_invisible_watermark_media(file_path, payload: str, out_path) -> str:
    out_path = str(out_path)
    cmd = [
        "ffmpeg", "-y", "-i", str(file_path),
        "-map", "0", "-c", "copy",
    ]
    # MP4/MOV's muxer silently drops any metadata key it doesn't already
    # know about unless told to keep custom ones -- confirmed by testing:
    # without this flag, the tag written below never actually lands in
    # the file. WebM/Matroska keeps custom tags without needing this.
    if Path(out_path).suffix.lower() in (".mp4", ".mov", ".m4a", ".m4v"):
        cmd += ["-movflags", "use_metadata_tags"]
    cmd += ["-metadata", f"{METADATA_TAG_KEY}={payload}", out_path]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            "Could not attach the invisible watermark metadata: "
            + result.stderr.decode(errors="ignore")[-400:]
        )
    return out_path


def extract_invisible_watermark_media(file_path):
    """Returns the tagged payload string if present, else None."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", f"format_tags={METADATA_TAG_KEY}",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return None
    text = result.stdout.decode(errors="ignore").strip()
    return text or None
