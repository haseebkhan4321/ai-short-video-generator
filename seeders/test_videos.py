"""Throwaway videos filled with lorem ipsum, at any stage and any size.

The development fixtures are hand-written and deliberately small — one video per
pipeline stage, a few hundred words each. This is the other thing you want: a video
of an arbitrary shape, to see how the UI actually behaves. A real 90-minute script
is ~13,500 words across ~14 parts, and a parts list that long looks nothing like a
three-part fixture.

It reuses ``VideoSeeder``, so a generated video gets the same steps, costs, API call
logs and placeholder assets as the demo ones. Only the text differs.

    python manage.py seed_test_video --account midnight-studio
    python manage.py seed_test_video --account midnight-studio --parts 14 --words 950
"""
from apps.templates.repositories import TemplateRepository

from . import lorem
from .base import Seeder
from .videos import VideoSeeder

STAGES = ["draft", "scripted", "split", "imaged", "narrated", "completed", "failed"]

# The premise carries the marker and the index: VideoSeeder matches an existing
# video by premise, so this is what makes re-running idempotent and makes the test
# videos easy to find (or delete) later.
MARKER = "[lorem]"

FAILED_ERROR = (
    "openai.APIError: lorem ipsum dolor sit amet — placeholder failure on a "
    "generated test video."
)


class TestVideoSeeder(Seeder):
    name = "Lorem ipsum test videos"

    def run(self, account=None, template=None, count=1, stage="split", parts=4,
            words=300, start=1, audio_seconds=8, with_media=True,
            with_video_files=True, actor=None, **options):
        if account is None:
            self.fail("An account is required.")
        if stage not in STAGES:
            self.fail(f"Unknown stage '{stage}'. One of: {', '.join(STAGES)}")

        templates = list(TemplateRepository.for_account(account))
        if not templates:
            self.fail(
                f"'{account.name}' has no templates. Run "
                f"seed_templates --account {account.slug} first."
            )
        if template is not None:
            chosen = TemplateRepository.get_by_name(account, template)
            if chosen is None:
                names = ", ".join(t.name for t in templates)
                self.fail(f"No template '{template}' in this account. Have: {names}")
            templates = [chosen]

        fixtures = [
            self._fixture(n, stage, parts, words, templates)
            for n in range(start, start + count)
        ]

        videos = VideoSeeder(self.command)
        built = videos(
            # Each fixture carries its own template object, so a batch can spread
            # across every template in the account.
            templates={"": None},
            actor=actor or account.owner,
            audio_seconds=audio_seconds,
            with_media=with_media,
            with_video_files=with_video_files,
            fixtures=fixtures,
            text_source=self._lorem_text,
        )
        self.result += videos.result
        return [v for v in built.values() if v is not None]

    # ---- Fixture generation ----

    def _fixture(self, n, stage, parts, words, templates):
        seed = n * 7919  # any stable multiplier; keeps consecutive videos distinct
        spec = {
            "key": f"lorem-{n}",
            "stage": stage,
            # Carried on the spec, not derived from the batch position: --start 9 and
            # --start 1 both build a one-item batch, so position would give them
            # identical text.
            "seed": seed,
            # Round-robin across the account's templates so a batch is not all
            # attributed to one content identity.
            "template_obj": templates[(n - 1) % len(templates)],
            "template": "",
            "premise": f"{MARKER} {n} — {lorem.sentence(seed)}",
            "target_minutes": max(5, round(parts * words / 150)),
            "chapters": parts,
            "words_per_part": words,
        }
        if stage not in ("draft", "failed"):
            spec["title"] = f"{MARKER} {lorem.title(seed, 4)}"
            spec["description"] = lorem.paragraph(seed + 1, 34)
            spec["hashtags"] = lorem.hashtags(seed + 2, 5)
        if stage == "failed":
            spec["error"] = FAILED_ERROR
        return spec

    def _lorem_text(self, index, count, spec):
        """Bodies and titles for one video's parts.

        ``opening=True`` on the very first paragraph so the script starts with the
        recognisable "Lorem ipsum dolor sit amet…" rather than mid-babble.
        """
        words = spec.get("words_per_part", 300)
        base = spec["seed"]
        bodies, titles = [], []
        for n in range(count):
            seed = base + n * 131
            bodies.append(
                "\n\n".join(lorem.paragraphs(seed, words, opening=(n == 0)))
            )
            titles.append(f"{n + 1}. {lorem.title(seed + 5, 3)}")
        return bodies, titles
