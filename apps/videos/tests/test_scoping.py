"""One account must never reach another account's rows or files."""
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.repositories import RoleRepository
from apps.accounts.tests.factories import (
    VIEWER_ROLE,
    add_member,
    make_account,
    make_system_admin,
    make_template,
    make_user,
    make_video,
)
from apps.videos.models import StepType


class VideoScopingTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner, "Mine")
        self.template = make_template(self.account, "Mine Horror")
        self.video = make_video(self.template, actor=self.owner)

        self.outsider = make_user("outsider@example.com")
        self.other_account = make_account(self.outsider, "Theirs")
        self.other_template = make_template(self.other_account, "Theirs Horror")
        self.other_video = make_video(self.other_template, actor=self.outsider)

        self.client.force_login(self.owner)

    def test_the_list_shows_only_this_account(self):
        response = self.client.get(reverse("videos:list"))

        ids = {v.pk for v in response.context["videos"]}
        self.assertEqual(ids, {self.video.pk})

    def test_a_foreign_video_detail_is_a_404(self):
        response = self.client.get(
            reverse("videos:detail", args=[self.other_video.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_a_foreign_video_status_endpoint_is_a_404(self):
        response = self.client.get(
            reverse("videos:status", args=[self.other_video.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_a_foreign_video_cannot_be_deleted(self):
        response = self.client.post(
            reverse("videos:delete", args=[self.other_video.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.other_video.refresh_from_db()

    def test_the_template_list_shows_only_this_account(self):
        response = self.client.get(reverse("templates:list"))

        names = {t.name for t in response.context["templates"]}
        self.assertEqual(names, {"Mine Horror"})

    def test_a_foreign_template_detail_is_a_404(self):
        response = self.client.get(
            reverse("templates:detail", args=[self.other_template.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_a_video_cannot_be_created_on_a_foreign_template(self):
        response = self.client.post(
            reverse("videos:create"),
            {
                "template": self.other_template.pk,
                "premise": "sneaky",
                "target_minutes": 30,
            },
        )

        self.assertEqual(response.status_code, 200)  # form redisplayed with an error
        self.assertFalse(self.other_template.videos.filter(premise="sneaky").exists())

    def test_a_system_admin_sees_the_account_they_entered(self):
        admin = make_system_admin()
        self.client.force_login(admin)
        self.client.post(
            reverse("console:account_enter", args=[self.other_account.pk])
        )

        response = self.client.get(reverse("videos:list"))

        ids = {v.pk for v in response.context["videos"]}
        self.assertEqual(ids, {self.other_video.pk})


class StepScopingTests(TestCase):
    """The ``video_id`` in a step URL has to be load-bearing."""

    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner, "Mine")
        self.template = make_template(self.account)
        self.video = make_video(self.template, actor=self.owner)
        self.step = self.video.steps.get(step_type=StepType.SCRIPT)

        self.second_video = make_video(self.template, premise="another story")

        self.outsider = make_user("outsider@example.com")
        self.other_account = make_account(self.outsider, "Theirs")
        self.other_video = make_video(
            make_template(self.other_account), actor=self.outsider
        )
        self.other_step = self.other_video.steps.get(step_type=StepType.SCRIPT)

        self.client.force_login(self.owner)

    def test_a_step_from_another_video_is_a_404(self):
        response = self.client.post(
            reverse("videos:step_approve", args=[self.second_video.pk, self.step.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.step.refresh_from_db()
        self.assertEqual(self.step.status, "pending_approval")

    def test_a_step_from_another_account_is_a_404(self):
        for name in ("step_approve", "step_reject", "step_regenerate"):
            with self.subTest(view=name):
                response = self.client.post(
                    reverse(
                        f"videos:{name}",
                        args=[self.other_video.pk, self.other_step.pk],
                    )
                )
                self.assertEqual(response.status_code, 404)

    def test_pairing_a_local_video_with_a_foreign_step_is_a_404(self):
        response = self.client.post(
            reverse("videos:step_approve", args=[self.video.pk, self.other_step.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.other_step.refresh_from_db()
        self.assertEqual(self.other_step.status, "pending_approval")

    def test_a_foreign_batch_approve_is_a_404(self):
        response = self.client.post(
            reverse("videos:batch_approve", args=[self.other_video.pk]),
            {"step_type": StepType.IMAGES},
        )
        self.assertEqual(response.status_code, 404)


class MediaScopingTests(TestCase):
    """Generated assets live at ``media/videos/<id>/``, so the media handler is an
    access-control surface of its own, not just a static file server."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # ignore_cleanup_errors: a streaming response that some future test forgets
        # to close would otherwise hold a Windows file lock, fail this teardown, and
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
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner, "Mine")
        self.video = make_video(make_template(self.account), actor=self.owner)

        self.outsider = make_user("outsider@example.com")
        self.other_video = make_video(
            make_template(make_account(self.outsider, "Theirs")), actor=self.outsider
        )

        for video in (self.video, self.other_video):
            folder = Path(settings.MEDIA_ROOT) / "videos" / str(video.pk)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "final.mp4").write_bytes(b"not really an mp4")

    def _media_url(self, video):
        return f"/media/videos/{video.pk}/final.mp4"

    def _get_media(self, video, **extra):
        """Fetch a media URL and release the file handle.

        A 200/206 from the media handler is a StreamingHttpResponse whose generator
        holds the file open until it is exhausted or closed; a real WSGI server
        iterates it, the test client does not, and on Windows the leftover handle
        blocks deleting the file.

        Exhausting the generator is what closes it, via the ``with open(...)`` in
        ``_stream``. Calling ``response.close()`` would also work but fires Django's
        ``request_finished`` signal, and that closes the test's database connection
        out from under the surrounding transaction.
        """
        response = self.client.get(self._media_url(video), **extra)
        if response.streaming:
            self.body = b"".join(response.streaming_content)
        return response

    def test_anonymous_media_access_is_redirected_to_login(self):
        response = self._get_media(self.video)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_a_foreign_account_media_file_is_a_404_even_though_it_exists(self):
        self.client.force_login(self.owner)

        response = self._get_media(self.other_video)

        self.assertEqual(response.status_code, 404)

    def test_an_own_media_file_is_served(self):
        self.client.force_login(self.owner)

        response = self._get_media(self.video)

        self.assertEqual(response.status_code, 200)

    def test_a_range_request_on_an_own_file_is_served(self):
        self.client.force_login(self.owner)

        response = self._get_media(self.video, HTTP_RANGE="bytes=0-3")

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 0-3/17")
        self.assertEqual(self.body, b"not ")

    def test_a_served_media_file_can_still_be_deleted(self):
        """Serving a file must not leave a lock behind: deleting a video deletes its
        media, and on Windows an unreleased stream would block that."""
        self.client.force_login(self.owner)
        self._get_media(self.video, HTTP_RANGE="bytes=0-3")

        path = Path(settings.MEDIA_ROOT) / "videos" / str(self.video.pk) / "final.mp4"
        path.unlink()

        self.assertFalse(path.exists())

    def test_a_range_request_on_a_foreign_file_is_a_404(self):
        self.client.force_login(self.owner)

        response = self._get_media(self.other_video, HTTP_RANGE="bytes=0-3")

        self.assertEqual(response.status_code, 404)

    def test_a_viewer_without_video_view_cannot_read_media(self):
        stranger = make_user("stranger@example.com")
        add_member(self.account, stranger, VIEWER_ROLE)
        role = RoleRepository.get_by_name(self.account, VIEWER_ROLE)
        RoleRepository.update(role, permissions=[])
        self.client.force_login(stranger)

        response = self._get_media(self.video)

        self.assertEqual(response.status_code, 404)
