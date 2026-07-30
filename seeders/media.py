"""Placeholder asset writers for the development seeder.

Seeding a path on a model is not enough: the video detail page shows image
thumbnails, an audio player and a video element, and all three are broken if the
file behind the path does not exist. These writers produce small, real files so the
seeded UI is actually usable.

Nothing here needs Pillow. PNGs are written by hand (a PNG is a fixed header plus
zlib-compressed scanlines) and WAVs go through soundfile, which is already a
dependency for the narration merge. MP4s need ffmpeg, which is optional — when it is
missing the seeder says so and leaves the render paths unset rather than pointing at
a file that will not play.
"""
import struct
import subprocess
import zlib
from pathlib import Path

import numpy as np
import soundfile as sf
from django.conf import settings

# Muted palette, cycled per image so seeded parts are visually distinguishable.
_SWATCHES = [
    (34, 38, 49),
    (46, 38, 52),
    (30, 45, 48),
    (52, 42, 34),
    (38, 34, 52),
    (44, 48, 38),
]


def _png_chunk(kind, payload):
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def write_png(path, width=480, height=270, swatch=0):
    """A small PNG with a vertical gradient. Real bytes, no image library."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    base = _SWATCHES[swatch % len(_SWATCHES)]
    raw = bytearray()
    for y in range(height):
        # Each scanline starts with its filter byte (0 = none).
        raw.append(0)
        lift = int(60 * (y / max(height - 1, 1)))
        row = bytes((min(base[0] + lift, 255), min(base[1] + lift, 255),
                     min(base[2] + lift, 255)))
        raw += row * width

    header = struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0)  # 8-bit truecolour
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    return path


def write_wav(path, seconds, sample_rate=None):
    """A quiet tone, so the audio player shows a real duration and can seek.

    Deliberately near-silent (and fading at both ends) — a seeded fixture that
    played a loud tone would be unpleasant to click on.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    sample_rate = sample_rate or settings.TTS_SAMPLE_RATE
    count = max(int(seconds * sample_rate), sample_rate // 10)
    t = np.linspace(0.0, seconds, count, endpoint=False, dtype=np.float32)
    tone = 0.02 * np.sin(2 * np.pi * 110.0 * t).astype(np.float32)

    fade = min(sample_rate // 2, count // 2)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        tone[:fade] *= ramp
        tone[-fade:] *= ramp[::-1]

    sf.write(str(path), tone, sample_rate)
    return path


def concat_wavs(paths, out_path):
    """Merge part WAVs the same way the merge step does, returning per-part offsets."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    chunks, offsets, cursor, rate = [], [], 0.0, settings.TTS_SAMPLE_RATE
    for path in paths:
        data, rate = sf.read(str(path), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        start = cursor
        cursor += len(data) / float(rate)
        offsets.append((start, cursor))
        chunks.append(data)

    sf.write(str(out_path), np.concatenate(chunks), rate)
    return offsets, cursor


def ffmpeg_available():
    try:
        subprocess.run(
            [settings.FFMPEG_BINARY, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=20,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def write_mp4(path, image_path, audio_path, seconds):
    """A still image over an audio track — the shape of a real render, cheaply.

    Returns False if ffmpeg is unavailable or errors, so the caller can leave the
    render path unset instead of recording one that will not play.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        settings.FFMPEG_BINARY, "-y", "-loglevel", "error",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
        "-pix_fmt", "yuv420p",
        "-vf", f"scale={settings.VIDEO_WIDTH}:{settings.VIDEO_HEIGHT}",
        "-r", "12",
        "-c:a", "aac", "-b:a", "64k",
        "-t", f"{seconds:.2f}",
        "-shortest",
        str(path),
    ]
    try:
        subprocess.run(command, check=True, timeout=300,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True
    except (OSError, subprocess.SubprocessError):
        path.unlink(missing_ok=True)
        return False


def video_dir(video_id):
    return Path(settings.MEDIA_ROOT) / "videos" / str(video_id)


def part_dir(video_id, chapter_number):
    return video_dir(video_id) / "parts" / f"{chapter_number:02d}"


def rel(path):
    """The MEDIA_ROOT-relative, forward-slashed form the models store."""
    return Path(path).relative_to(Path(settings.MEDIA_ROOT)).as_posix()
