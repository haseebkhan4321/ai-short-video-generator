"""Render steps (free/local).

- ``render_part``: one part's images (Ken Burns) over that part's narration ->
  a per-part preview MP4 stored on the chapter. Auto-runs when a part has both
  its images and narration, so parts can be previewed before the whole video.
- ``render``: the full video. All parts' clips over the merged narration track.

Both registered as executors.
"""
import shutil
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from ..integrations import ffmpeg_renderer as ff
from ..models import StepType, VideoStatus
from ..repositories import ChapterRepository, VideoRepository
from .pipeline import PipelineService, StepResult, register_executor


def _music_path():
    name = settings.BACKGROUND_MUSIC
    if not name:
        return None
    path = Path(settings.BASE_DIR) / "assets" / "music" / name
    return str(path) if path.exists() else None


def _render_settings():
    return (
        settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT, settings.RENDER_FPS,
        settings.RENDER_PRESET, settings.RENDER_CRF,
    )


def _part_duration(chapter):
    start = chapter.audio_start_seconds
    end = chapter.audio_end_seconds
    if start is not None and end is not None and end > start:
        return end - start
    # Fallback: probe the part's audio file (offsets are only set after merge).
    if chapter.narration_audio_path:
        return ff.ffprobe_duration(Path(settings.MEDIA_ROOT) / chapter.narration_audio_path)
    return 0.0


def _build_clips(chapter, dur, render_dir, start_idx, w, h, fps, preset, crf, step=None, total=None):
    """Render this part's images as Ken Burns clips spanning ``dur`` seconds.
    Returns (clip_paths, next_idx)."""
    imgs = [i.image_path for i in chapter.images.all() if i.image_path]
    clips = []
    idx = start_idx
    if not imgs:
        idx += 1
        clip = render_dir / f"clip_{idx:04d}.mp4"
        ff.make_color_clip(dur, clip, w, h, fps, preset, crf)
        clips.append(clip)
        if step is not None:
            PipelineService.update_progress(step, current=idx)
        return clips, idx

    per = dur / len(imgs)
    for j, img in enumerate(imgs):
        idx += 1
        # Last image absorbs rounding so the part matches its audio span.
        d = per if j < len(imgs) - 1 else dur - per * (len(imgs) - 1)
        clip = render_dir / f"clip_{idx:04d}.mp4"
        ff.make_image_clip(
            Path(settings.MEDIA_ROOT) / img, d, clip, w, h, fps, preset, crf,
            zoom_in=(j % 2 == 0),
        )
        clips.append(clip)
        if step is not None:
            msg = f"Rendering clip {idx}" + (f"/{total}" if total else "")
            PipelineService.update_progress(step, current=idx, message=msg)
    return clips, idx


def run_render_part_step(step):
    """Render a single part's preview video (its images over its narration)."""
    chapter = step.chapter
    if chapter is None:
        raise ValueError("Render-part step has no associated part.")
    if not chapter.narration_audio_path:
        raise ValueError("Cannot render part: narration is missing.")

    w, h, fps, preset, crf = _render_settings()
    dur = _part_duration(chapter)
    if dur <= 0:
        raise ValueError("Cannot render part: unknown narration duration.")

    imgs = [i for i in chapter.images.all() if i.image_path]
    PipelineService.update_progress(
        step, current=0, total=max(1, len(imgs)) + 1, message="Rendering part clips..."
    )

    render_dir = Path(settings.MEDIA_ROOT) / f"videos/{chapter.video_id}/parts/{chapter.chapter_number:02d}/render"
    render_dir.mkdir(parents=True, exist_ok=True)
    try:
        clips, _ = _build_clips(
            chapter, dur, render_dir, 0, w, h, fps, preset, crf,
            step=step, total=max(1, len(imgs)),
        )
        video_only = render_dir / "video_only.mp4"
        ff.concat_clips(clips, render_dir / "list.txt", video_only)

        PipelineService.update_progress(
            step, current=len(clips) + 1, message="Adding narration..."
        )
        rel_path = f"videos/{chapter.video_id}/parts/{chapter.chapter_number:02d}/part.mp4"
        ff.mux_audio(
            video_only,
            Path(settings.MEDIA_ROOT) / chapter.narration_audio_path,
            Path(settings.MEDIA_ROOT) / rel_path,
        )
    finally:
        shutil.rmtree(render_dir, ignore_errors=True)

    ChapterRepository.update(chapter, video_path=rel_path)
    return StepResult(
        actual_cost_usd=Decimal("0"),
        response_metadata={"seconds": round(dur, 2), "images": len(imgs)},
    )


def run_render_step(step):
    video = step.video
    if not video.narration_audio_path:
        raise ValueError("No merged narration track; run narration + merge first.")

    w, h, fps, preset, crf = _render_settings()

    chapters = list(ChapterRepository.for_video(video.pk))
    total_units = 0
    for ch in chapters:
        imgs = [i.image_path for i in ch.images.all() if i.image_path]
        total_units += max(1, len(imgs))

    if total_units == 0:
        raise ValueError("Nothing to render: no parts/images.")

    VideoRepository.update(video, status=VideoStatus.RENDERING)
    PipelineService.update_progress(
        step, current=0, total=total_units + 2, message="Rendering clips..."
    )

    render_dir = Path(settings.MEDIA_ROOT) / f"videos/{video.pk}/render"
    render_dir.mkdir(parents=True, exist_ok=True)

    clips = []
    idx = 0
    for ch in chapters:
        dur = _part_duration(ch)
        if dur <= 0:
            continue
        part_clips, idx = _build_clips(
            ch, dur, render_dir, idx, w, h, fps, preset, crf,
            step=step, total=total_units,
        )
        clips.extend(part_clips)

    if not clips:
        raise ValueError("No clips were produced (missing durations/images).")

    PipelineService.update_progress(
        step, current=total_units + 1, message="Joining clips..."
    )
    video_only = render_dir / "video_only.mp4"
    ff.concat_clips(clips, render_dir / "list.txt", video_only)

    PipelineService.update_progress(
        step, current=total_units + 2, message="Adding narration..."
    )
    final_rel = f"videos/{video.pk}/final.mp4"
    final_abs = Path(settings.MEDIA_ROOT) / final_rel
    ff.mux_audio(
        video_only,
        Path(settings.MEDIA_ROOT) / video.narration_audio_path,
        final_abs,
        music_path=_music_path(),
        music_vol=settings.BACKGROUND_MUSIC_VOLUME,
    )

    VideoRepository.update(video, final_video_path=final_rel)
    shutil.rmtree(render_dir, ignore_errors=True)  # keep only final.mp4

    return StepResult(
        actual_cost_usd=Decimal("0"),
        response_metadata={
            "clips": len(clips),
            "seconds": video.duration_seconds,
            "resolution": f"{w}x{h}",
        },
    )


register_executor(StepType.RENDER_PART, run_render_part_step)
register_executor(StepType.RENDER, run_render_step)
