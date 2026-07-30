"""The optional subtitles step.

Transcription itself is stubbed. The provider boundary is exactly where the seam
belongs: running real Whisper in a test would download the weights and spend a minute
per case to check nothing this code owns. What is covered here is what this code does
own — SRT formatting, where the step sits in the pipeline, and the failure modes.
"""
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from apps.accounts.tests.factories import (
    make_account,
    make_template,
    make_user,
    make_video,
)
from apps.videos.integrations.base import Cue, ProviderError, TranscriptionResult
from apps.videos.models import Provider, StepStatus, StepType
from apps.videos.repositories import StepRepository, VideoRepository
from apps.videos.services import subtitle_service
from apps.videos.services.pipeline import PipelineService
from apps.videos.services.subtitle_service import (
    format_timestamp,
    run_subtitles_step,
    to_srt,
    wrap_cue,
)


class TimestampTests(TestCase):
    def test_it_formats_as_srt_expects(self):
        self.assertEqual(format_timestamp(0), "00:00:00,000")
        self.assertEqual(format_timestamp(1.5), "00:00:01,500")
        self.assertEqual(format_timestamp(61.25), "00:01:01,250")
        self.assertEqual(format_timestamp(3661.007), "01:01:01,007")

    def test_it_survives_nonsense(self):
        self.assertEqual(format_timestamp(None), "00:00:00,000")
        self.assertEqual(format_timestamp(-4), "00:00:00,000")

    def test_it_rounds_rather_than_truncates(self):
        self.assertEqual(format_timestamp(0.9999), "00:00:01,000")


class WrapTests(TestCase):
    @override_settings(SUBTITLE_LINE_WIDTH=20)
    def test_a_short_cue_is_left_alone(self):
        self.assertEqual(wrap_cue("a short line"), "a short line")

    @override_settings(SUBTITLE_LINE_WIDTH=20)
    def test_a_long_cue_wraps_to_two_lines(self):
        wrapped = wrap_cue("the quick brown fox jumps over the lazy dog")
        self.assertEqual(len(wrapped.split("\n")), 2)

    @override_settings(SUBTITLE_LINE_WIDTH=12)
    def test_it_never_exceeds_two_lines_and_never_drops_words(self):
        """A caption three or four lines tall covers the image it is captioning, but
        losing words is worse than one long line."""
        text = " ".join(f"word{n}" for n in range(20))

        wrapped = wrap_cue(text)

        self.assertEqual(len(wrapped.split("\n")), 2)
        self.assertEqual(wrapped.replace("\n", " ").split(), text.split())

    def test_whitespace_is_normalised(self):
        self.assertEqual(wrap_cue("  spaced   out \n text "), "spaced out text")


class SrtTests(TestCase):
    def test_it_writes_numbered_blocks(self):
        srt = to_srt([Cue(0, 1.5, "first"), Cue(1.5, 3, "second")])

        self.assertEqual(
            srt,
            "1\n00:00:00,000 --> 00:00:01,500\nfirst\n"
            "\n"
            "2\n00:00:01,500 --> 00:00:03,000\nsecond\n",
        )

    def test_a_zero_length_cue_is_given_time_on_screen(self):
        """Some players drop the rest of the file after an invalid cue."""
        srt = to_srt([Cue(2, 2, "blink")])

        self.assertIn("00:00:02,000 --> 00:00:02,200", srt)

    def test_a_reversed_cue_is_repaired(self):
        srt = to_srt([Cue(5, 3, "backwards")])

        self.assertIn("00:00:05,000 --> 00:00:05,200", srt)

    def test_no_cues_gives_empty_output(self):
        self.assertEqual(to_srt([]), "")


class StubProvider:
    def __init__(self, cues=None, language="en"):
        self.cues = cues if cues is not None else [Cue(0, 2, "hello there"), Cue(2, 4, "again")]
        self.language = language
        self.calls = []

    def transcribe(self, audio_path, language=None, on_progress=None):
        self.calls.append({"path": Path(audio_path), "language": language})
        if on_progress:
            for cue in self.cues:
                on_progress(cue.end)
        return TranscriptionResult(
            cues=self.cues, language=self.language, model="stub", duration=4.0
        )


class RunStepTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls._override = override_settings(MEDIA_ROOT=Path(cls._tmp.name))
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        cls._tmp.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        VideoRepository.update(
            self.video, narration_audio_path=f"videos/{self.video.pk}/narration.wav",
            duration_seconds=4.0,
        )
        audio = Path(self.tmp()) / self.video.narration_audio_path
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"not really a wav")

        self.step = StepRepository.create(
            video=self.video,
            step_type=StepType.SUBTITLES,
            provider=Provider.LOCAL,
            status=StepStatus.APPROVED,
            estimated_cost_usd=Decimal("0"),
        )

    def tmp(self):
        return type(self)._tmp.name

    def _run(self, provider):
        with mock.patch.object(
            subtitle_service, "get_transcription_provider", return_value=provider
        ):
            return run_subtitles_step(self.step)

    def test_it_writes_an_srt_and_records_the_path(self):
        result = self._run(StubProvider())

        self.video.refresh_from_db()
        self.assertEqual(
            self.video.subtitles_path, f"videos/{self.video.pk}/subtitles.srt"
        )
        srt = (Path(self.tmp()) / self.video.subtitles_path).read_text(encoding="utf-8")
        self.assertIn("hello there", srt)
        self.assertIn("00:00:00,000 --> 00:00:02,000", srt)
        self.assertEqual(result.actual_cost_usd, Decimal("0"))
        self.assertEqual(result.response_metadata["cues"], 2)
        self.assertEqual(result.response_metadata["language"], "en")

    def test_it_is_free(self):
        result = self._run(StubProvider())
        self.assertEqual(result.actual_cost_usd, Decimal("0"))

    def test_it_passes_the_templates_language_through(self):
        provider = StubProvider()
        self._run(provider)
        self.assertEqual(provider.calls[0]["language"], "en")

    def test_it_reports_progress_in_seconds_of_audio(self):
        self._run(StubProvider())

        self.step.refresh_from_db()
        # total is the track length, so the bar tracks the audio rather than an
        # unknown number of segments.
        self.assertEqual(self.step.progress_total, 4)
        self.assertEqual(self.step.progress_current, 4)

    def test_no_narration_track_is_refused(self):
        VideoRepository.update(self.video, narration_audio_path="")

        with self.assertRaises(ValueError):
            self._run(StubProvider())

    def test_a_missing_audio_file_is_refused(self):
        (Path(self.tmp()) / self.video.narration_audio_path).unlink()

        with self.assertRaises(ValueError):
            self._run(StubProvider())

    def test_an_empty_transcription_is_refused(self):
        """Better to fail and be retryable than to write an empty SRT and call it
        done."""
        with self.assertRaises(ValueError):
            self._run(StubProvider(cues=[]))

        self.video.refresh_from_db()
        self.assertEqual(self.video.subtitles_path, "")

    def test_a_provider_error_propagates(self):
        class Broken:
            def transcribe(self, *a, **k):
                raise ProviderError("faster-whisper is not installed")

        with self.assertRaises(ProviderError):
            self._run(Broken())


class PipelinePositionTests(TestCase):
    """Subtitles sit between merge and render, so the render can burn them in."""

    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.merge = StepRepository.create(
            video=self.video,
            step_type=StepType.MERGE,
            provider=Provider.LOCAL,
            status=StepStatus.COMPLETED,
            estimated_cost_usd=Decimal("0"),
        )

    def _advance_merge(self):
        # Patch run_step: _trigger_singleton_free runs a free step as soon as it
        # creates it, and this test is about which step gets created.
        with mock.patch.object(PipelineService, "run_step"):
            PipelineService._advance(self.merge)
        return set(
            StepRepository.for_video(self.video.pk).values_list("step_type", flat=True)
        )

    @override_settings(SUBTITLES_ENABLED=False)
    def test_merge_goes_straight_to_render_when_disabled(self):
        created = self._advance_merge()

        self.assertIn(StepType.RENDER, created)
        self.assertNotIn(StepType.SUBTITLES, created)

    @override_settings(SUBTITLES_ENABLED=True)
    def test_merge_goes_to_subtitles_when_enabled(self):
        created = self._advance_merge()

        self.assertIn(StepType.SUBTITLES, created)
        self.assertNotIn(StepType.RENDER, created)

    @override_settings(SUBTITLES_ENABLED=True)
    def test_subtitles_then_hands_on_to_render(self):
        self._advance_merge()
        subtitles = StepRepository.for_video(self.video.pk).get(
            step_type=StepType.SUBTITLES
        )
        StepRepository.update(subtitles, status=StepStatus.COMPLETED)

        with mock.patch.object(PipelineService, "run_step"):
            PipelineService._advance(subtitles)

        self.assertTrue(
            StepRepository.for_video(self.video.pk)
            .filter(step_type=StepType.RENDER)
            .exists()
        )

    @override_settings(SUBTITLES_ENABLED=True)
    def test_the_subtitles_step_is_free_and_local(self):
        self._advance_merge()

        step = StepRepository.for_video(self.video.pk).get(step_type=StepType.SUBTITLES)
        self.assertEqual(step.provider, Provider.LOCAL)
        self.assertFalse(step.is_paid)
        self.assertEqual(step.estimated_cost_usd, Decimal("0"))
