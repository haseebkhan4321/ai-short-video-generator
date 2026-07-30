"""Seed a set of starter templates for long-form narrated story videos.

Templates belong to an account, so the target account is required. Idempotent:
existing templates (matched by name within that account) are left untouched unless
--update is passed.

    python manage.py seed_templates --account my-studio
"""
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.repositories import AccountRepository
from apps.templates.repositories import TemplateRepository
from apps.templates.services import TemplateService

SEED_TEMPLATES = [
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
    help = "Seed starter content templates for long-form narrated story videos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--account",
            required=True,
            help="Slug of the account to seed the templates into.",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update existing templates (matched by name) instead of skipping them.",
        )

    def handle(self, *args, **options):
        account = AccountRepository.get_by_slug(options["account"])
        if account is None:
            raise CommandError(
                f"No account with slug '{options['account']}'. "
                "Run bootstrap_rbac first, or check the slug."
            )

        update = options["update"]
        created, updated, skipped = 0, 0, 0

        self.stdout.write(f"Seeding templates into '{account.name}':")
        for data in SEED_TEMPLATES:
            existing = TemplateRepository.get_by_name(account, data["name"])
            if existing is None:
                TemplateService.create_template(account, data)
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  + created  {data['name']}"))
            elif update:
                TemplateService.update_template(existing, data)
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
