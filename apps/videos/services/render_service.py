"""Render step (free/local): build the final MP4 from each part's images
(Ken Burns) over the merged narration track. Registered as the 'render' executor.
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


def _part_duration(chapter):
    start = chapter.audio_start_seconds
    end = chapter.audio_end_seconds
    if start is not None and end is not None and end > start:
        return end - start
    # Fallback: probe the part's audio file.
    if chapter.narration_audio_path:
        return ff.ffprobe_duration(Path(settings.MEDIA_ROOT) / chapter.narration_audio_path)
    return 0.0


def run_render_step(step):
    video = step.video
    if not video.narration_audio_path:
        raise ValueError("No merged narration track; run narration + merge first.")

    w, h, fps = settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT, settings.RENDER_FPS
    preset, crf = settings.RENDER_PRESET, settings.RENDER_CRF

    chapters = list(ChapterRepository.for_video(video.pk))
    plan = []  # (chapter, [image_paths], duration)
    total_units = 0
    for ch in chapters:
        imgs = [i.image_path for i in ch.images.all() if i.image_path]
        plan.append((ch, imgs, _part_duration(ch)))
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
    for ch, imgs, dur in plan:
        if dur <= 0:
            continue
        if not imgs:
            idx += 1
            clip = render_dir / f"clip_{idx:04d}.mp4"
            ff.make_color_clip(dur, clip, w, h, fps, preset, crf)
            clips.append(clip)
            PipelineService.update_progress(step, current=idx)
            continue
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
            PipelineService.update_progress(
                step, current=idx, message=f"Rendering clip {idx}/{total_units}"
            )

    if not clips:
        raise ValueError("No clips were produced (missing durations/images).")

    # Join clips.
    PipelineService.update_progress(
        step, current=total_units + 1, message="Joining clips..."
    )
    video_only = render_dir / "video_only.mp4"
    ff.concat_clips(clips, render_dir / "list.txt", video_only)

    # Mux narration (+ optional background music).
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


register_executor(StepType.RENDER, run_render_step)
