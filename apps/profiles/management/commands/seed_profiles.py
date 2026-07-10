"""Seed a set of starter profiles for long-form narrated story videos.

Idempotent: existing profiles (matched by name) are left untouched unless
--update is passed. Run with:  python manage.py seed_profiles
"""
from django.core.management.base import BaseCommand

from apps.profiles.repositories import ProfileRepository
from apps.profiles.services import ProfileService

SEED_PROFILES = [
    {
        "name": "Midnight Horror Narrations",
        "niche": "horror",
        "description": "Long-form atmospheric horror stories for late-night listening.",
        "style_prompt": (
            "You write slow-burn, atmospheric horror narration for a faceless "
            "long-form YouTube channel. Second-person and third-person mix, dread "
            "that builds gradually, vivid sensory detail, minimal gore, a strong "
            "hook in the first minute and a disturbing twist near the end. Written "
            "to be read aloud calmly by a single narrator."
        ),
        "narrator_voice": "",
        "language": "en",
    },
    {
        "name": "Sleep & Bedtime Stories",
        "niche": "bedtime",
        "description": "Calm, gentle stories designed to help listeners fall asleep.",
        "style_prompt": (
            "You write soothing, slow-paced bedtime stories for adults. Soft, "
            "meandering narration with warm imagery, no conflict spikes or jump "
            "scares, gentle repetition, and a peaceful, drifting tone. Written to "
            "be read aloud slowly and quietly."
        ),
        "narrator_voice": "",
        "language": "en",
    },
    {
        "name": "Untold History",
        "niche": "history",
        "description": "Deep-dive historical narratives and forgotten events.",
        "style_prompt": (
            "You write engaging, well-structured long-form history narration. "
            "Clear chronological storytelling, vivid scene-setting, memorable "
            "characters, accurate framing, and smooth transitions between eras. "
            "Authoritative but accessible, written to be narrated as a documentary."
        ),
        "narrator_voice": "",
        "language": "en",
    },
    {
        "name": "Deep Space Sci-Fi",
        "niche": "sci-fi",
        "description": "Original long-form science fiction stories set in deep space.",
        "style_prompt": (
            "You write cinematic long-form science fiction narration. Grand scale, "
            "cosmic wonder and tension, believable technology, isolated protagonists, "
            "and a slow reveal of the central mystery. Immersive third-person, "
            "written to be narrated over ambient space visuals."
        ),
        "narrator_voice": "",
        "language": "en",
    },
    {
        "name": "Mind & Motivation",
        "niche": "motivation",
        "description": "Reflective, motivational long-form stories and life lessons.",
        "style_prompt": (
            "You write reflective, uplifting long-form narration built around a "
            "central life lesson. Story-driven rather than preachy, grounded in "
            "relatable human moments, with a clear takeaway and a calm, sincere "
            "tone. Written to be narrated warmly and steadily."
        ),
        "narrator_voice": "",
        "language": "en",
    },
    {
        "name": "Case Files: Fiction",
        "niche": "mystery",
        "description": "Fictional detective and mystery narratives, feature length.",
        "style_prompt": (
            "You write long-form fictional mystery and detective stories. A compelling "
            "case introduced early, escalating clues, red herrings, a methodical "
            "investigator, and a satisfying reveal. Tense, measured pacing written "
            "to be narrated as a serialized case file."
        ),
        "narrator_voice": "",
        "language": "en",
    },
]


class Command(BaseCommand):
    help = "Seed starter content profiles for long-form narrated story videos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update existing profiles (matched by name) instead of skipping them.",
        )

    def handle(self, *args, **options):
        update = options["update"]
        created, updated, skipped = 0, 0, 0

        for data in SEED_PROFILES:
            existing = ProfileRepository.get_by_name(data["name"])
            if existing is None:
                ProfileService.create_profile(data)
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  + created  {data['name']}"))
            elif update:
                ProfileService.update_profile(existing, data)
                updated += 1
                self.stdout.write(self.style.WARNING(f"  ~ updated  {data['name']}"))
            else:
                skipped += 1
                self.stdout.write(f"  = skipped  {data['name']} (already exists)")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. created={created} updated={updated} skipped={skipped}"
            )
        )
