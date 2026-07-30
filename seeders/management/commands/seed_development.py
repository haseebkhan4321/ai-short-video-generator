"""Seed a full development fixture: accounts, roles, users, templates and videos.

Creates a video at every pipeline stage with real placeholder assets, so the whole
UI can be exercised without a single paid API call. Idempotent; ``--fresh`` removes
its own previous output first.

    python manage.py seed_development
    python manage.py seed_development --fresh
    python manage.py seed_development --no-media        # rows only, no files
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from seeders.development import DevelopmentSeeder


class Command(BaseCommand):
    help = "Seed demo accounts, users, roles, templates and videos for development."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            help="Password for every seeded user. Defaults to the well-known dev one.",
        )
        parser.add_argument(
            "--fresh",
            action="store_true",
            help="Delete this seeder's previous output (its accounts and @dev.local "
            "users) before seeding.",
        )
        parser.add_argument(
            "--no-media",
            action="store_true",
            help="Skip writing placeholder images and audio. Faster, but thumbnails "
            "and players will be empty.",
        )
        parser.add_argument(
            "--no-video-files",
            action="store_true",
            help="Write images and audio but skip the ffmpeg renders.",
        )
        parser.add_argument(
            "--audio-seconds",
            type=int,
            default=8,
            help="Length of each placeholder narration clip (default 8).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is off. This seeder creates users with a "
            "well-known password, so it refuses by default.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        seeder = DevelopmentSeeder(self)
        seeder(
            password=options["password"],
            force=options["force"],
            fresh=options["fresh"],
            with_media=not options["no_media"],
            with_video_files=not options["no_video_files"],
            audio_seconds=options["audio_seconds"],
        )
        self.stdout.write(self.style.SUCCESS("\nDevelopment seed complete."))
