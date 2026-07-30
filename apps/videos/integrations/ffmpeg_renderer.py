"""Thin ffmpeg/ffprobe wrappers used by the render step."""
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

from .base import ProviderError


def _run(cmd, cwd=None):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    except FileNotFoundError as exc:
        raise ProviderError(
            f"'{cmd[0]}' not found. Install ffmpeg and put it on PATH, or set "
            "FFMPEG_BINARY / FFPROBE_BINARY in .env."
        ) from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1000:]
        raise ProviderError(f"ffmpeg failed:\n{tail}")
    return proc


def ffprobe_duration(path):
    proc = _run([
        settings.FFPROBE_BINARY, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ])
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def probe_streams(path):
    """Return the set of codec types present (e.g. {'video','audio'})."""
    proc = _run([
        settings.FFPROBE_BINARY, "-v", "error",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ])
    return set(line.strip() for line in proc.stdout.splitlines() if line.strip())


def make_image_clip(image_path, duration, out_path, w, h, fps, preset, crf, zoom_in=True):
    """A single still with a slow Ken Burns zoom, encoded to a WxH clip."""
    frames = max(1, int(round(duration * fps)))
    zexpr = "min(zoom+0.0006,1.25)" if zoom_in else "if(lte(zoom,1.0),1.25,max(1.001,zoom-0.0006))"
    vf = (
        f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,"
        f"crop={w * 2}:{h * 2},"
        f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={w}x{h}:fps={fps},setsar=1,format=yuv420p"
    )
    # `-t` MUST come after `-i` (an output option). Placed before `-i` it caps the
    # looped INPUT to duration*fps frames, and zoompan then emits d frames PER input
    # frame — a duration*fps multiplication that explodes a 6s clip into 900s.
    _run([
        settings.FFMPEG_BINARY, "-y", "-loop", "1",
        "-i", str(image_path), "-vf", vf, "-r", str(fps),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p", str(out_path),
    ])


def make_color_clip(duration, out_path, w, h, fps, preset, crf, color="black"):
    _run([
        settings.FFMPEG_BINARY, "-y", "-f", "lavfi",
        "-i", f"color=c={color}:s={w}x{h}:r={fps}", "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p", str(out_path),
    ])


def concat_clips(clip_paths, list_file, out_path):
    with open(list_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            safe = str(p).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe}'\n")
    _run([
        settings.FFMPEG_BINARY, "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file), "-c", "copy", str(out_path),
    ])


def burn_subtitles(video_path, srt_path, out_path, preset, crf, font_size=24):
    """Re-encode ``video_path`` with the SRT burned in.

    A re-encode is unavoidable: the render concatenates pre-encoded clips with
    ``-c:v copy``, and drawing pixels onto them means decoding and encoding once.
    Applied to the silent video, before the audio mux, so the audio is never touched.

    ffmpeg's ``subtitles=`` filter takes a filename inside a filtergraph, where a
    Windows path is a minefield: the drive colon separates filter options and the
    backslashes are escapes. Rather than escaping it, both files are staged in one
    directory and ffmpeg is run there with bare relative names.
    """
    work = Path(out_path).parent
    work.mkdir(parents=True, exist_ok=True)
    staged_srt = work / "burn.srt"
    shutil.copyfile(str(srt_path), str(staged_srt))

    style = (
        f"FontName=Arial,FontSize={font_size},PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H90000000,BorderStyle=3,Outline=2,Shadow=0,"
        "Alignment=2,MarginV=48"
    )
    _run(
        [
            settings.FFMPEG_BINARY, "-y",
            "-i", str(Path(video_path).name),
            "-vf", f"subtitles={staged_srt.name}:force_style='{style}'",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-an",
            str(Path(out_path).name),
        ],
        cwd=str(work),
    )
    staged_srt.unlink(missing_ok=True)


def mux_audio(video_path, audio_path, out_path, music_path=None, music_vol="0.08"):
    """Attach narration (and optionally ducked background music) to the video."""
    if music_path:
        cmd = [
            settings.FFMPEG_BINARY, "-y",
            "-i", str(video_path), "-i", str(audio_path),
            "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex",
            f"[2:a]volume={music_vol}[m];"
            f"[1:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(out_path),
        ]
    else:
        cmd = [
            settings.FFMPEG_BINARY, "-y",
            "-i", str(video_path), "-i", str(audio_path),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(out_path),
        ]
    _run(cmd)
