"""Tests for the seeders.

The two properties worth protecting are idempotency (re-running must not duplicate)
and the fixture invariants the video seeder relies on — particularly that no step is
left approved-but-unrun except the one documented exception, since anything approved
starts real work the first time a page is opened.

Media writing is off in most tests: it is exercised in one dedicated case against a
temporary MEDIA_ROOT rather than on every run.
"""
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth import authenticate
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.accounts.models import Account, Membership, Role, User
from apps.accounts.permissions import ALL_CODENAMES, OWNER_ROLE, Perm
from apps.accounts.repositories import MembershipRepository, RoleRepository
from apps.templates.models import Template
from apps.videos.models import (
    ApiCallLog,
    Chapter,
    ChapterImage,
    GenerationStep,
    StepStatus,
    StepType,
    Video,
)
from seeders.data import DEMO_ACCOUNTS, DEV_PASSWORD, STARTER_TEMPLATES
from seeders.development import DevelopmentSeeder
from seeders.production import ProductionSeeder
from seeders.roles import RoleSeeder
from seeders.test_videos import STAGES

ADMIN = {"email": "admin@example.com", "password": "seed-test-pass-1", "name": "A Admin"}


def run_dev(**options):
    """The development seeder without media, quietly."""
    out = StringIO()
    call_command("seed_development", stdout=out, no_media=True, **options)
    return out.getvalue()


class RoleSeederTests(TestCase):
    def test_it_seeds_the_three_defaults(self):
        RoleSeeder()(refresh=False)

        defaults = RoleRepository.system_defaults()
        self.assertEqual(
            set(defaults.values_list("name", flat=True)),
            {"Owner", "Producer", "Viewer"},
        )
        self.assertTrue(all(r.is_system_default for r in defaults))
        self.assertEqual(
            RoleRepository.get_by_name(None, OWNER_ROLE).codenames, ALL_CODENAMES
        )

    def test_re_running_creates_nothing(self):
        RoleSeeder()(refresh=False)
        RoleSeeder()(refresh=False)
        self.assertEqual(Role.objects.filter(account__isnull=True).count(), 3)

    def test_it_leaves_an_edited_default_alone(self):
        """An operator can edit a default at /console/; a seeder must not undo that."""
        RoleSeeder()(refresh=False)
        viewer = RoleRepository.get_by_name(None, "Viewer")
        RoleRepository.update(viewer, permissions=[Perm.VIDEO_VIEW])

        RoleSeeder()(refresh=False)

        viewer.refresh_from_db()
        self.assertEqual(viewer.codenames, frozenset({Perm.VIDEO_VIEW}))

    def test_refresh_restores_the_catalog(self):
        RoleSeeder()(refresh=False)
        viewer = RoleRepository.get_by_name(None, "Viewer")
        RoleRepository.update(viewer, permissions=[])

        RoleSeeder()(refresh=True)

        viewer.refresh_from_db()
        self.assertEqual(
            viewer.codenames, frozenset({Perm.TEMPLATE_VIEW, Perm.VIDEO_VIEW})
        )


class ProductionSeederTests(TestCase):
    def test_it_creates_a_working_system_admin_and_account(self):
        user, account = ProductionSeeder()(
            email=ADMIN["email"],
            password=ADMIN["password"],
            full_name=ADMIN["name"],
            account_name="Live Studio",
        )

        self.assertTrue(user.is_system_admin)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_active)
        self.assertEqual(account.name, "Live Studio")
        self.assertEqual(account.slug, "live-studio")
        self.assertEqual(account.owner_id, user.pk)

        membership = MembershipRepository.for_user(user).first()
        self.assertEqual(membership.role.name, OWNER_ROLE)
        self.assertEqual(membership.role.codenames, ALL_CODENAMES)
        self.assertIsNotNone(
            authenticate(username=ADMIN["email"], password=ADMIN["password"])
        )

    def test_it_seeds_no_demo_data(self):
        ProductionSeeder()(
            email=ADMIN["email"], password=ADMIN["password"],
            account_name="Live Studio",
        )

        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Account.objects.count(), 1)
        self.assertEqual(Template.objects.count(), 0)
        self.assertEqual(Video.objects.count(), 0)

    def test_with_templates_adds_the_starter_set(self):
        _, account = ProductionSeeder()(
            email=ADMIN["email"], password=ADMIN["password"],
            account_name="Live Studio", with_templates=True,
        )

        self.assertEqual(
            Template.objects.filter(account=account).count(), len(STARTER_TEMPLATES)
        )

    def test_re_running_changes_nothing(self):
        for _ in range(2):
            ProductionSeeder()(
                email=ADMIN["email"], password=ADMIN["password"],
                account_name="Live Studio", with_templates=True,
            )

        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Account.objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 1)
        self.assertEqual(Template.objects.count(), len(STARTER_TEMPLATES))
        self.assertEqual(Role.objects.filter(account__isnull=True).count(), 3)

    def test_an_existing_users_password_is_never_reset(self):
        User.objects.create_user(email=ADMIN["email"], password="their-own-password-9")

        ProductionSeeder()(
            email=ADMIN["email"], password="a-different-one", account_name="Live Studio"
        )

        self.assertIsNotNone(
            authenticate(username=ADMIN["email"], password="their-own-password-9")
        )

    def test_it_promotes_an_existing_user_instead_of_duplicating(self):
        existing = User.objects.create_user(
            email=ADMIN["email"], password="their-own-password-9"
        )
        self.assertFalse(existing.is_system_admin)

        user, _ = ProductionSeeder()(
            email=ADMIN["email"], account_name="Live Studio"
        )

        self.assertEqual(user.pk, existing.pk)
        self.assertTrue(user.is_system_admin)
        self.assertEqual(User.objects.count(), 1)

    def test_roles_only_creates_no_user(self):
        call_command("seed_production", roles_only=True, stdout=StringIO())

        self.assertEqual(Role.objects.filter(account__isnull=True).count(), 3)
        self.assertEqual(User.objects.count(), 0)

    def test_a_new_admin_without_a_password_is_refused(self):
        with self.assertRaises(CommandError):
            ProductionSeeder()(email=ADMIN["email"], account_name="Live Studio")

        self.assertEqual(User.objects.count(), 0)


class DevelopmentSeederGuardTests(TestCase):
    @override_settings(DEBUG=False)
    def test_it_refuses_to_run_with_debug_off(self):
        with self.assertRaises(CommandError):
            run_dev()

        self.assertEqual(User.objects.count(), 0)

    @override_settings(DEBUG=False)
    def test_force_overrides_the_guard(self):
        run_dev(force=True)
        self.assertTrue(User.objects.filter(email="admin@dev.local").exists())


@override_settings(DEBUG=True)
class DevelopmentSeederTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        run_dev()

    def test_it_creates_the_demo_accounts_and_their_roles(self):
        names = set(Account.objects.values_list("name", flat=True))
        self.assertEqual(names, {spec["name"] for spec in DEMO_ACCOUNTS})

        midnight = Account.objects.get(name="Midnight Studio")
        self.assertEqual(
            set(midnight.roles.values_list("name", flat=True)),
            {"Owner", "Producer", "Viewer", "Narrator"},
        )

    def test_the_custom_narrator_role_can_run_free_work_but_not_spend(self):
        midnight = Account.objects.get(name="Midnight Studio")
        narrator = RoleRepository.get_by_name(midnight, "Narrator")

        self.assertIn(Perm.STEP_RUN_FREE, narrator.codenames)
        self.assertNotIn(Perm.STEP_APPROVE_PAID, narrator.codenames)
        self.assertNotIn(Perm.STEP_OVERRIDE_BUDGET, narrator.codenames)

    def test_every_seeded_user_can_sign_in(self):
        for user in User.objects.all():
            with self.subTest(email=user.email):
                self.assertIsNotNone(
                    authenticate(username=user.email, password=DEV_PASSWORD)
                )

    def test_one_user_belongs_to_both_accounts(self):
        viewer = User.objects.get(email="viewer@dev.local")
        accounts = {m.account.name for m in MembershipRepository.for_user(viewer)}
        self.assertEqual(accounts, {"Midnight Studio", "Second Studio"})

    def test_templates_are_account_scoped(self):
        midnight = Account.objects.get(name="Midnight Studio")
        second = Account.objects.get(name="Second Studio")

        self.assertEqual(
            Template.objects.filter(account=midnight).count(), len(STARTER_TEMPLATES)
        )
        self.assertEqual(
            list(Template.objects.filter(account=second).values_list("name", flat=True)),
            ["Untold History"],
        )

    def test_it_seeds_a_video_at_every_stage(self):
        """``completed`` is absent here on purpose: these runs pass --no-media, and a
        fixture with no assets cannot honestly claim a finished render. The
        media-backed run in SeededMediaTests covers it."""
        statuses = set(Video.objects.values_list("status", flat=True))
        self.assertEqual(
            statuses, {"draft", "script", "split", "images", "narration", "failed"}
        )
        self.assertEqual(Video.objects.count(), 7)

    def test_all_videos_belong_to_the_main_demo_account(self):
        midnight = Account.objects.get(name="Midnight Studio")
        self.assertFalse(
            Video.objects.exclude(template__account=midnight).exists()
        )

    def test_only_the_narrated_fixture_leaves_a_step_queued(self):
        """Anything approved runs on the first page view, so this is the invariant
        that keeps a fixture from starting an ffmpeg render behind the user's back."""
        queued = GenerationStep.objects.filter(status=StepStatus.APPROVED)

        self.assertEqual(
            [(s.video.title, s.step_type) for s in queued],
            [("The Long Dusk at Weatherby Cove", StepType.RENDER)],
        )

    def test_no_step_is_left_running(self):
        self.assertFalse(
            GenerationStep.objects.filter(status=StepStatus.RUNNING).exists()
        )

    def test_the_draft_fixture_waits_on_a_paid_script_step(self):
        video = Video.objects.get(status="draft")
        step = video.steps.get()

        self.assertEqual(step.step_type, StepType.SCRIPT)
        self.assertTrue(step.is_paid)
        self.assertEqual(step.status, StepStatus.PENDING_APPROVAL)
        self.assertGreater(step.estimated_cost_usd, 0)
        self.assertIsNone(step.approved_by)

    def test_the_failed_fixture_is_retryable(self):
        video = Video.objects.get(status="failed")

        self.assertTrue(video.error_message)
        self.assertEqual(video.steps.get().status, StepStatus.FAILED)

    def test_a_split_script_is_exactly_its_parts(self):
        """The split step slices the finished script, so the fixture has to match."""
        for video in Video.objects.exclude(chapters=None):
            with self.subTest(video=str(video)):
                bodies = [
                    c.body for c in video.chapters.order_by("chapter_number")
                ]
                self.assertEqual(video.script, "\n\n".join(bodies))
                self.assertEqual(
                    video.total_words, len(video.script.split())
                )

    def test_completed_paid_steps_record_a_cost_an_approver_and_a_call_log(self):
        paid = GenerationStep.objects.filter(
            status=StepStatus.COMPLETED, provider="openai"
        )
        self.assertTrue(paid.exists())

        for step in paid:
            with self.subTest(step=str(step)):
                self.assertIsNotNone(step.actual_cost_usd)
                self.assertIsNotNone(step.approved_by_id)
                self.assertIsNotNone(step.approved_at)
                self.assertEqual(step.api_calls.count(), 1)

    def test_a_videos_cost_is_the_sum_of_its_api_calls(self):
        for video in Video.objects.all():
            with self.subTest(video=str(video)):
                logged = sum(
                    log.cost_usd
                    for step in video.steps.all()
                    for log in step.api_calls.all()
                )
                self.assertEqual(video.total_cost_usd, logged)

    def test_free_steps_never_carry_a_cost(self):
        for step in GenerationStep.objects.filter(provider="local"):
            with self.subTest(step=str(step)):
                self.assertEqual(step.estimated_cost_usd, 0)
                self.assertEqual(step.api_calls.count(), 0)

    def test_re_running_duplicates_nothing(self):
        counts = {
            model: model.objects.count()
            for model in (User, Account, Role, Membership, Template, Video,
                          Chapter, ChapterImage, GenerationStep, ApiCallLog)
        }

        run_dev()

        for model, before in counts.items():
            with self.subTest(model=model.__name__):
                self.assertEqual(model.objects.count(), before)

    def test_fresh_removes_only_its_own_output(self):
        outsider = User.objects.create_user(
            email="real.person@example.com", password="not-a-seeded-one-7"
        )

        run_dev(fresh=True)

        self.assertTrue(User.objects.filter(pk=outsider.pk).exists())
        self.assertEqual(
            Account.objects.count(), len(DEMO_ACCOUNTS)
        )
        self.assertEqual(
            User.objects.filter(email__endswith="@dev.local").count(),
            # one system admin, two owners, three members (one shared across accounts)
            len({spec["owner"]["email"] for spec in DEMO_ACCOUNTS}
                | {m["email"] for spec in DEMO_ACCOUNTS for m in spec["members"]})
            + 1,
        )


@override_settings(DEBUG=True)
class LoremTestVideoTests(TestCase):
    """``seed_test_video``: throwaway videos at a chosen stage and size.

    DEBUG on because one case also runs the development seeder, which refuses
    without it.
    """

    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com", password="seed-test-pass-1"
        )
        _, self.account = ProductionSeeder()(
            email=self.owner.email, account_name="Studio", with_templates=True,
        )

    def _run(self, **options):
        options.setdefault("no_media", True)
        call_command("seed_test_video", account=self.account.slug,
                     stdout=StringIO(), **options)

    def test_it_creates_a_video_of_the_requested_shape(self):
        self._run(count=1, stage="split", parts=6, words=200)

        video = Video.objects.get()
        self.assertEqual(video.chapters.count(), 6)
        self.assertEqual(video.status, "split")
        # Word counts are approximate by design (paragraphs vary in length), so this
        # checks the order of magnitude rather than an exact figure.
        self.assertGreater(video.total_words, 6 * 150)
        self.assertLess(video.total_words, 6 * 320)

    def test_the_text_is_lorem_ipsum(self):
        self._run(stage="split", parts=2, words=120)

        video = Video.objects.get()
        self.assertTrue(video.script.startswith("Lorem ipsum dolor sit amet"))
        self.assertIn("[lorem]", video.premise)
        self.assertIn("[lorem]", video.title)

    def test_the_script_is_still_exactly_its_parts(self):
        """The same coherence the demo fixtures keep: split slices the script."""
        self._run(stage="split", parts=4, words=150)

        video = Video.objects.get()
        bodies = [c.body for c in video.chapters.order_by("chapter_number")]
        self.assertEqual(video.script, "\n\n".join(bodies))

    def test_the_same_index_always_gives_the_same_text(self):
        """Determinism is what keeps the seeder idempotent and bugs reproducible."""
        self._run(stage="split", parts=2, words=120)
        first = Video.objects.get().script

        Video.objects.all().delete()
        self._run(stage="split", parts=2, words=120)

        self.assertEqual(Video.objects.get().script, first)

    def test_a_different_index_gives_different_text(self):
        self._run(stage="split", parts=2, words=120)
        self._run(stage="split", parts=2, words=120, start=9)

        scripts = list(Video.objects.values_list("script", flat=True))

        self.assertEqual(len(scripts), 2)
        self.assertNotEqual(scripts[0], scripts[1])

    def test_a_batch_spreads_across_the_accounts_templates(self):
        self._run(count=3, stage="draft")

        used = set(Video.objects.values_list("template_id", flat=True))
        self.assertEqual(len(used), 3)

    def test_one_template_can_be_pinned(self):
        name = Template.objects.filter(account=self.account).first().name

        self._run(count=2, stage="draft", template=name)

        used = set(Video.objects.values_list("template__name", flat=True))
        self.assertEqual(used, {name})

    def test_re_running_the_same_index_creates_nothing(self):
        self._run(count=2, stage="draft")
        self._run(count=2, stage="draft")
        self.assertEqual(Video.objects.count(), 2)

    def test_start_adds_more(self):
        self._run(count=2, stage="draft")
        self._run(count=2, stage="draft", start=3)
        self.assertEqual(Video.objects.count(), 4)

    def test_every_stage_is_buildable(self):
        for index, stage in enumerate(STAGES, start=1):
            with self.subTest(stage=stage):
                self._run(stage=stage, parts=2, words=80, start=index * 100)
        self.assertEqual(Video.objects.count(), len(STAGES))

    def test_the_failed_stage_is_retryable(self):
        self._run(stage="failed", start=50)

        video = Video.objects.get()
        self.assertEqual(video.status, "failed")
        self.assertTrue(video.error_message)
        self.assertEqual(video.steps.get().status, StepStatus.FAILED)

    def test_purge_removes_only_the_lorem_videos(self):
        run_dev()  # the hand-written demo fixtures
        demo = Video.objects.count()
        self._run(count=2, stage="draft", start=200)
        self.assertEqual(Video.objects.count(), demo + 2)

        call_command("seed_test_video", account=self.account.slug,
                     purge=True, stdout=StringIO())

        self.assertEqual(Video.objects.count(), demo)
        self.assertFalse(Video.objects.filter(premise__startswith="[lorem]").exists())

    def test_an_unknown_account_is_refused(self):
        with self.assertRaises(CommandError):
            call_command("seed_test_video", account="nope", stdout=StringIO())

    def test_an_unknown_template_is_refused(self):
        with self.assertRaises(CommandError):
            self._run(template="Does Not Exist")


@override_settings(DEBUG=True)
class SeededMediaTests(TestCase):
    """The one case that writes files: paths on a model are useless if the file is
    missing, since the detail page renders thumbnails, an audio player and a video."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # ignore_cleanup_errors so a stray Windows file lock cannot fail teardown and
        # cascade into every test that runs after this class.
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls._override = override_settings(MEDIA_ROOT=Path(cls._tmp.name))
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        cls._tmp.cleanup()
        super().tearDownClass()

    def setUp(self):
        out = StringIO()
        # ffmpeg renders are skipped: too slow for a test, and the MP4 path is not
        # what this is checking.
        call_command("seed_development", stdout=out, no_video_files=True,
                     audio_seconds=1)

    def _exists(self, relative):
        return (Path(self._tmp.name) / relative).is_file()

    def test_every_referenced_image_exists(self):
        images = ChapterImage.objects.exclude(image_path="")
        self.assertTrue(images.exists())
        for image in images:
            with self.subTest(path=image.image_path):
                self.assertTrue(self._exists(image.image_path))

    def test_every_referenced_audio_file_exists(self):
        chapters = Chapter.objects.exclude(narration_audio_path="")
        self.assertTrue(chapters.exists())
        for chapter in chapters:
            with self.subTest(path=chapter.narration_audio_path):
                self.assertTrue(self._exists(chapter.narration_audio_path))

        for video in Video.objects.exclude(narration_audio_path=""):
            with self.subTest(path=video.narration_audio_path):
                self.assertTrue(self._exists(video.narration_audio_path))

    def test_part_offsets_are_contiguous_and_sum_to_the_duration(self):
        for video in Video.objects.exclude(narration_audio_path=""):
            chapters = list(video.chapters.order_by("chapter_number"))
            with self.subTest(video=str(video)):
                self.assertAlmostEqual(chapters[0].audio_start_seconds, 0.0, places=3)
                for earlier, later in zip(chapters, chapters[1:]):
                    self.assertAlmostEqual(
                        earlier.audio_end_seconds, later.audio_start_seconds, places=3
                    )
                self.assertAlmostEqual(
                    chapters[-1].audio_end_seconds, video.duration_seconds, places=3
                )

    def test_no_media_records_no_paths_but_keeps_the_prompts(self):
        """A path to a file that was never written is a broken thumbnail, so
        --no-media must leave the paths blank rather than point at nothing."""
        call_command("seed_development", stdout=StringIO(), fresh=True, no_media=True)

        self.assertFalse(ChapterImage.objects.exclude(image_path="").exists())
        self.assertFalse(Chapter.objects.exclude(narration_audio_path="").exists())
        self.assertFalse(Video.objects.exclude(narration_audio_path="").exists())
        self.assertFalse(Video.objects.exclude(final_video_path="").exists())
        # The rows survive, so the generated prompts are still inspectable.
        self.assertTrue(ChapterImage.objects.exclude(image_prompt="").exists())

    def test_with_media_the_completed_fixture_has_a_narrated_track(self):
        """The stage the no-media runs cannot reach."""
        completed = Video.objects.get(title="Forty Years, One Chair")

        self.assertTrue(completed.narration_audio_path)
        self.assertGreater(completed.duration_seconds, 0)
        # ffmpeg renders are off in this class, so the video stops just short of
        # 'completed' — with renders on it goes all the way.
        self.assertEqual(completed.status, "narration")
