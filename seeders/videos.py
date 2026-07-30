"""Seeds videos at every pipeline stage, with their chapters, images, steps and logs.

This is the fixture that makes the app demo-able without spending anything. Each
fixture stops at a different point in the pipeline, so the video-detail UI can be
seen in every state it has: waiting on a paid approval, mid-split, images done but
narration pending, fully rendered, and failed.

Two deliberate choices:

- **Placeholder assets, real files.** Paths alone leave broken thumbnails and dead
  audio players, so short PNGs/WAVs/MP4s are written to ``media/``. Chapter and video
  durations are read back from those files rather than derived from word counts, so
  the offsets, the audio player and ``duration_seconds`` all agree. Seeded audio is a
  few seconds of quiet tone, not synthesized narration.
- **Approved steps are avoided, with one deliberate exception.**
  ``resume_waiting_steps`` claims approved steps and runs them, so an
  approved-but-unfinished step means real work starts the first time anyone opens the
  page. Seeded steps are pending, completed or failed — except the ``narrated``
  fixture, whose final render step is left ``approved`` because that is genuinely
  where the pipeline leaves it once the merge finishes. Opening that video runs the
  part and final renders for real, which is the point: it demonstrates the live
  progress UI without a paid call.

  That step has to be created here. ``_advance`` only creates the video-level render
  step when a ``merge`` step *completes at runtime*, and this fixture seeds merge as
  already done, so nothing else would ever queue it.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.videos.models import Provider, StepStatus, StepType, VideoStatus
from apps.videos.repositories import (
    ApiCallLogRepository,
    ChapterImageRepository,
    ChapterRepository,
    StepRepository,
    VideoRepository,
)
from apps.videos.services.cost_estimator import CostEstimator

from . import media
from .base import Seeder
from .data import CHAPTER_TITLES, VIDEO_FIXTURES, paragraphs_for


class VideoSeeder(Seeder):
    name = "Videos"

    def run(self, templates=None, actor=None, audio_seconds=8, with_media=True,
            with_video_files=True, **options):
        if not templates:
            self.fail("Templates must be seeded before videos.")

        self.audio_seconds = audio_seconds
        self.with_media = with_media
        self.ffmpeg = (
            with_media and with_video_files and media.ffmpeg_available()
        )
        if with_media and with_video_files and not self.ffmpeg:
            self.warn(
                f"ffmpeg not runnable ({settings.FFMPEG_BINARY}) — seeding without "
                "rendered MP4s. Set FFMPEG_BINARY in .env to include them."
            )

        built = {}
        for index, spec in enumerate(VIDEO_FIXTURES):
            template = templates.get(spec["template"])
            if template is None:
                self.skipped(f"{spec['key']} — template '{spec['template']}' not seeded")
                continue
            built[spec["key"]] = self._video(spec, template, actor, index)
        return built

    # ---- One fixture ----

    def _video(self, spec, template, actor, index):
        existing = VideoRepository.get_by_premise(template, spec["premise"])
        if existing is not None:
            self.existed(f"{spec['key']}: {existing}")
            return existing

        stage = spec["stage"]
        # A stable, receding creation time per fixture, so the list view has an order
        # that is not just "everything at once".
        clock = timezone.now() - timedelta(days=len(VIDEO_FIXTURES) - index, hours=2)

        chapter_count = spec.get("chapters", 3)
        bodies, titles = self._chapter_text(index, chapter_count)
        # The split step slices the finished script, so the script has to be exactly
        # the concatenation of the parts for the fixture to be coherent.
        script = "\n\n".join(bodies)

        video = VideoRepository.create(
            template=template,
            created_by=actor,
            premise=spec["premise"],
            target_minutes=spec["target_minutes"],
            status=VideoStatus.DRAFT,
            title=spec.get("title", ""),
            description=spec.get("description", ""),
            hashtags=spec.get("hashtags", []),
        )

        if stage == "draft":
            self._script_step(video, StepStatus.PENDING_APPROVAL, clock, actor)
            self._describe(video, spec, "script step waiting for approval")
            return video

        if stage == "failed":
            self._script_step(
                video, StepStatus.FAILED, clock, actor, error=spec["error"]
            )
            VideoRepository.update(
                video, status=VideoStatus.FAILED, error_message=spec["error"]
            )
            self._describe(video, spec, "script step failed, retryable")
            return video

        # Every remaining stage has a finished script.
        total_words = len(script.split())
        cost = self._script_step(
            video, StepStatus.COMPLETED, clock, actor, words=total_words
        )
        VideoRepository.update(
            video,
            script=script,
            total_words=total_words,
            status=VideoStatus.SCRIPT,
            total_cost_usd=cost,
        )
        clock += timedelta(minutes=6)

        if stage == "scripted":
            self._describe(video, spec, f"script written ({total_words} words)")
            return video

        chapters = self._chapters(video, bodies, titles)
        self._local_step(video, StepType.SPLIT, clock, chapters=len(chapters))
        VideoRepository.update(video, status=VideoStatus.SPLIT)
        clock += timedelta(minutes=1)

        images_done = stage in ("imaged", "narrated", "completed")
        narration_done = stage in ("narrated", "completed")

        cost += self._image_steps(video, chapters, clock, actor, done=images_done)
        if images_done:
            VideoRepository.update(
                video, status=VideoStatus.IMAGES, total_cost_usd=cost
            )
        clock += timedelta(minutes=12)

        self._narration_steps(video, chapters, clock, actor, done=narration_done)
        if narration_done:
            self._merge(video, chapters, clock)
            VideoRepository.update(video, status=VideoStatus.NARRATION)
        clock += timedelta(minutes=20)

        if stage == "completed":
            self._render(video, chapters, clock)
        elif stage == "narrated":
            self._queue_render(video, clock)

        note = {
            "split": f"{len(chapters)} parts, images + narration pending",
            "imaged": f"{len(chapters)} parts with images, narration pending",
            "narrated": f"{len(chapters)} parts narrated and merged, render left to the app",
            "completed": f"{len(chapters)} parts, fully rendered",
        }[stage]
        self._describe(video, spec, note)
        return video

    def _describe(self, video, spec, note):
        self.created(f"{spec['key']}: {video} — {note}")

    # ---- Pieces ----

    def _chapter_text(self, index, count):
        bodies, titles = [], []
        for n in range(count):
            bodies.append("\n\n".join(paragraphs_for(index + n, 3)))
            titles.append(CHAPTER_TITLES[(index + n) % len(CHAPTER_TITLES)])
        return bodies, titles

    def _chapters(self, video, bodies, titles):
        chapters = []
        for number, (body, title) in enumerate(zip(bodies, titles), start=1):
            chapters.append(
                ChapterRepository.create(
                    video=video,
                    chapter_number=number,
                    title=title,
                    body=body,
                    word_count=len(body.split()),
                )
            )
        return chapters

    def _script_step(self, video, status, clock, actor, words=0, error=""):
        """The paid script step. Returns its actual cost (zero unless completed)."""
        model = settings.OPENAI_TEXT_MODEL
        estimate = CostEstimator.estimate_script(video.target_minutes, model)
        payload = {
            "model": model,
            "target_minutes": video.target_minutes,
            "target_words": CostEstimator.target_words(video.target_minutes),
            "premise": video.premise,
            "style_prompt": video.template.style_prompt,
        }

        actual = Decimal("0")
        meta = {}
        if status == StepStatus.COMPLETED:
            # Plausible usage for the text actually stored, priced with the real
            # estimator so the seeded spend figures are not invented numbers.
            output_tokens = int(words * 1.35) or 1
            input_tokens = int(output_tokens * 0.4)
            actual = CostEstimator.actual_text_cost(model, input_tokens, output_tokens)
            meta = {
                "calls": 1,
                "total_words": words,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

        step = self._step(
            video,
            StepType.SCRIPT,
            Provider.OPENAI,
            status,
            clock,
            estimate=estimate,
            actual=actual if status == StepStatus.COMPLETED else None,
            payload=payload,
            meta=meta,
            actor=actor if status != StepStatus.PENDING_APPROVAL else None,
            error=error,
        )

        if status == StepStatus.COMPLETED:
            ApiCallLogRepository.create(
                step=step,
                provider=Provider.OPENAI,
                endpoint="chat.completions",
                model=model,
                units={
                    "input_tokens": meta["input_tokens"],
                    "output_tokens": meta["output_tokens"],
                },
                cost_usd=actual,
                duration_ms=42_000,
            )
        return actual

    def _local_step(self, video, step_type, clock, chapter=None, **meta):
        """A free, local step. Recorded as completed — free steps never wait."""
        return self._step(
            video,
            step_type,
            Provider.LOCAL,
            StepStatus.COMPLETED,
            clock,
            estimate=Decimal("0"),
            actual=Decimal("0"),
            chapter=chapter,
            meta=meta,
        )

    def _image_steps(self, video, chapters, clock, actor, done):
        per_part = settings.IMAGES_PER_PART
        model = settings.OPENAI_IMAGE_MODEL
        estimate = CostEstimator.estimate_images(per_part, model)
        spent = Decimal("0")

        for chapter in chapters:
            status = StepStatus.COMPLETED if done else StepStatus.PENDING_APPROVAL
            actual = (
                CostEstimator.actual_image_cost(model, per_part) if done else None
            )
            step = self._step(
                video,
                StepType.IMAGES,
                Provider.OPENAI,
                status,
                clock + timedelta(minutes=chapter.chapter_number),
                estimate=estimate,
                actual=actual,
                chapter=chapter,
                payload={
                    "model": model,
                    "num_images": per_part,
                    "chapter_number": chapter.chapter_number,
                },
                meta={"images": per_part} if done else {},
                actor=actor if done else None,
            )
            if not done:
                continue

            spent += actual
            ApiCallLogRepository.create(
                step=step,
                provider=Provider.OPENAI,
                endpoint="images.generate",
                model=model,
                units={"images": per_part},
                cost_usd=actual,
                duration_ms=per_part * 9_000,
            )
            self._images_for(video, chapter, per_part)
        return spent

    def _images_for(self, video, chapter, count):
        directory = media.part_dir(video.pk, chapter.chapter_number)
        for order in range(1, count + 1):
            path = directory / f"img_{order}.png"
            # Without media the row is still worth having for its prompt, but the
            # path stays blank: recording one for a file that was never written would
            # give the detail page a broken thumbnail to render.
            image_path = ""
            if self.with_media:
                media.write_png(path, swatch=chapter.chapter_number + order)
                image_path = media.rel(path)
            ChapterImageRepository.create(
                chapter=chapter,
                order=order,
                image_prompt=(
                    f"{chapter.title}, shot {order} of {count}: wide cinematic frame, "
                    "muted palette, volumetric light, no text, no people's faces, 16:9"
                ),
                image_path=image_path,
            )

    def _narration_steps(self, video, chapters, clock, actor, done):
        """Narration is local and free, but still waits for a manual start."""
        voice = video.template.narrator_voice or settings.DEFAULT_KOKORO_VOICE

        for chapter in chapters:
            status = StepStatus.COMPLETED if done else StepStatus.PENDING_APPROVAL
            self._step(
                video,
                StepType.NARRATION,
                Provider.LOCAL,
                status,
                clock + timedelta(minutes=chapter.chapter_number),
                estimate=Decimal("0"),
                actual=Decimal("0") if done else None,
                chapter=chapter,
                payload={
                    "voice": voice,
                    "chars": len(chapter.body),
                    "chapter_number": chapter.chapter_number,
                },
                meta={"seconds": self.audio_seconds} if done else {},
                actor=actor if done else None,
            )
            if not (done and self.with_media):
                continue

            path = media.part_dir(video.pk, chapter.chapter_number) / "narration.wav"
            media.write_wav(path, self.audio_seconds, sample_rate=16_000)
            ChapterRepository.update(
                chapter,
                narration_audio_path=media.rel(path),
                audio_end_seconds=float(self.audio_seconds),
            )

    def _merge(self, video, chapters, clock):
        """Concatenate the part WAVs and record the real offsets, as merge does."""
        parts = [c for c in chapters if c.narration_audio_path]
        if not parts or not self.with_media:
            return

        out = media.video_dir(video.pk) / "narration.wav"
        offsets, total = media.concat_wavs(
            [settings.MEDIA_ROOT / c.narration_audio_path for c in parts], out
        )
        for chapter, (start, end) in zip(parts, offsets):
            ChapterRepository.update(
                chapter, audio_start_seconds=start, audio_end_seconds=end
            )

        VideoRepository.update(
            video,
            narration_audio_path=media.rel(out),
            duration_seconds=total,
        )
        self._local_step(
            video, StepType.MERGE, clock, parts=len(parts), seconds=round(total, 2)
        )

    def _queue_render(self, video, clock):
        """Leave the final render approved and unrun, as a finished merge would.

        Free steps are created already approved, so this is the real post-merge state
        rather than a contrivance — ``resume_waiting_steps`` will pick it up and render
        for real on the first page view.
        """
        self._step(
            video,
            StepType.RENDER,
            Provider.LOCAL,
            StepStatus.APPROVED,
            clock,
            estimate=Decimal("0"),
        )
        self.note("final render left queued — opening this video will run it")

    def _render(self, video, chapters, clock):
        """Per-part previews plus the final video. Needs ffmpeg; skipped without it."""
        # Re-read: _merge wrote narration_audio_path and duration_seconds.
        video = VideoRepository.get(video.pk)
        if not video.narration_audio_path:
            # --no-media: there is nothing to render from, so this fixture cannot
            # reach 'completed'. Left at 'narration' rather than claiming a render.
            self.note("left at 'narration' — no media was written to render from")
            return
        if not self.ffmpeg:
            self.note(
                "left at 'narration' — no ffmpeg, so there is no final.mp4 to point at"
            )
            return

        for chapter in chapters:
            images = list(chapter.images.all())
            if not (images and chapter.narration_audio_path):
                continue
            out = media.part_dir(video.pk, chapter.chapter_number) / "part.mp4"
            ok = media.write_mp4(
                out,
                settings.MEDIA_ROOT / images[0].image_path,
                settings.MEDIA_ROOT / chapter.narration_audio_path,
                self.audio_seconds,
            )
            if ok:
                ChapterRepository.update(chapter, video_path=media.rel(out))
                self._local_step(
                    video,
                    StepType.RENDER_PART,
                    clock + timedelta(minutes=chapter.chapter_number),
                    chapter=chapter,
                    seconds=self.audio_seconds,
                )

        first = next(
            (i for c in chapters for i in c.images.all() if i.image_path), None
        )
        if first is None:
            return

        final = media.video_dir(video.pk) / "final.mp4"
        ok = media.write_mp4(
            final,
            settings.MEDIA_ROOT / first.image_path,
            settings.MEDIA_ROOT / video.narration_audio_path,
            video.duration_seconds or self.audio_seconds,
        )
        if not ok:
            self.note("final render failed — left at 'narration'")
            return

        self._local_step(
            video,
            StepType.RENDER,
            clock + timedelta(minutes=30),
            seconds=round(video.duration_seconds or 0, 2),
            width=settings.VIDEO_WIDTH,
            height=settings.VIDEO_HEIGHT,
        )
        VideoRepository.update(
            video,
            final_video_path=media.rel(final),
            status=VideoStatus.COMPLETED,
            error_message="",
        )

    # ---- Step construction ----

    def _step(self, video, step_type, provider, status, clock, estimate,
              actual=None, chapter=None, payload=None, meta=None, actor=None,
              error=""):
        fields = {
            "video": video,
            "chapter": chapter,
            "step_type": step_type,
            "provider": provider,
            "status": status,
            "estimated_cost_usd": estimate,
            "actual_cost_usd": actual,
            "request_payload": payload or {},
            "response_metadata": meta or {},
            "error_message": error,
        }
        if status in (StepStatus.COMPLETED, StepStatus.FAILED):
            fields["approved_by"] = actor
            fields["approved_at"] = clock
            fields["started_at"] = clock + timedelta(seconds=2)
            fields["finished_at"] = clock + timedelta(minutes=4)
        return StepRepository.create(**fields)
