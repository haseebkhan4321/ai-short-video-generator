"""Create throwaway videos filled with lorem ipsum, at any stage and any size.

The development fixtures are small and hand-written. This is for seeing how the UI
behaves at a shape you choose — a 14-part script reads very differently from a
three-part one.

    python manage.py seed_test_video --account midnight-studio
    python manage.py seed_test_video --account midnight-studio --count 3 --stage completed
    python manage.py seed_test_video --account midnight-studio --parts 14 --words 950
    python manage.py seed_test_video --account midnight-studio --purge
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.repositories import AccountRepository
from apps.videos.repositories import VideoRepository
from seeders.test_videos import MARKER, STAGES, TestVideoSeeder


class Command(BaseCommand):
    help = "Create lorem ipsum test videos in an account, at a chosen pipeline stage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--account", required=True, help="Slug of the target account."
        )
        parser.add_argument(
            "--count", type=int, default=1, help="How many videos to create (default 1)."
        )
        parser.add_argument(
            "--stage",
            default="split",
            choices=STAGES,
            help="How far down the pipeline to build them (default split).",
        )
        parser.add_argument(
            "--parts", type=int, default=4, help="Parts per video (default 4)."
        )
        parser.add_argument(
            "--words",
            type=int,
            default=300,
            help="Words per part (default 300). --parts 14 --words 950 is about the "
            "size of a real 90-minute script.",
        )
        parser.add_argument(
            "--template",
            help="Name of one template to use. Default spreads them across all of "
            "the account's templates.",
        )
        parser.add_argument(
            "--start",
            type=int,
            default=1,
            help="First index to number them from (default 1). Re-running with the "
            "same index is a no-op, so raise it to add more.",
        )
        parser.add_argument(
            "--audio-seconds",
            type=int,
            default=8,
            help="Length of each placeholder narration clip (default 8).",
        )
        parser.add_argument(
            "--no-media",
            action="store_true",
            help="Skip placeholder images and audio. Fast, but players and thumbnails "
            "will be empty and 'completed' is unreachable.",
        )
        parser.add_argument(
            "--no-video-files",
            action="store_true",
            help="Write images and audio but skip the ffmpeg renders.",
        )
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Delete every lorem ipsum test video in the account instead of "
            "creating any. Leaves the hand-written demo fixtures alone.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        account = AccountRepository.get_by_slug(options["account"])
        if account is None:
            raise CommandError(
                f"No account with slug '{options['account']}'. The slug is shown at "
                "/accounts/settings/."
            )

        if options["purge"]:
            return self._purge(account)

        seeder = TestVideoSeeder(self)
        videos = seeder(
            account=account,
            template=options["template"],
            count=options["count"],
            stage=options["stage"],
            parts=options["parts"],
            words=options["words"],
            start=options["start"],
            audio_seconds=options["audio_seconds"],
            with_media=not options["no_media"],
            with_video_files=not options["no_video_files"],
        )

        created = seeder.result.created
        if not created:
            self.stdout.write(
                self.style.WARNING(
                    f"\nNothing created — index {options['start']} onwards already "
                    "exists. Raise --start to add more, or --purge to clear them."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"\nCreated {created} test video(s)."))

        for video in videos:
            words = video.total_words or 0
            self.stdout.write(
                f"  /videos/{video.pk}/  {video.status:<10} "
                f"{video.chapters.count()} part(s), {words} words"
            )

    def _purge(self, account):
        # Matched on the premise marker, which is also how the seeder stays
        # idempotent — so this can only ever remove its own output.
        doomed = VideoRepository.for_account(account).filter(
            premise__startswith=MARKER
        )
        count = doomed.count()
        if not count:
            self.stdout.write("No lorem ipsum test videos in this account.")
            return
        for video in doomed:
            self.stdout.write(f"  - #{video.pk} {video}")
        doomed.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDeleted {count} test video(s). Files under media/ are left alone."
            )
        )
