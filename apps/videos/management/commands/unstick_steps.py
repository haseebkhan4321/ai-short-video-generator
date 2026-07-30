"""Recover steps abandoned by a worker that died mid-task.

Why this is needed: Celery is configured with ``acks_late = False``, so a task is
acknowledged on delivery and never redelivered. That is deliberate — redelivering a
paid step risks a second OpenAI charge for work that may already have completed. The
cost is that a worker killed mid-step leaves it RUNNING forever, because nothing else
will ever touch it.

This turns those into failures, which the existing Retry button can act on. It marks
them FAILED rather than APPROVED on purpose: re-running a paid step automatically is
exactly the double-charge this design avoids, so the decision stays with a person.

    python manage.py unstick_steps --older-than 60
    python manage.py unstick_steps --dry-run
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.videos.models import StepStatus, VideoStatus
from apps.videos.repositories import StepRepository, VideoRepository

MESSAGE = (
    "Abandoned: the worker running this step stopped before it finished. Nothing was "
    "retried automatically because this step may already have been paid for. Review "
    "and retry it if you want it run again."
)


class Command(BaseCommand):
    help = "Fail steps left RUNNING by a worker that died, so they can be retried."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than",
            type=int,
            default=180,
            help="Minutes a step must have been running to count as abandoned "
            "(default 180). A full render legitimately takes hours, so do not set "
            "this low.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be failed without changing anything.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options["older_than"])
        stale = list(StepRepository.stale_running(cutoff))

        if not stale:
            self.stdout.write(
                f"Nothing running since before {cutoff:%Y-%m-%d %H:%M} — nothing stuck."
            )
            return

        verb = "Would fail" if options["dry_run"] else "Failing"
        self.stdout.write(f"{verb} {len(stale)} abandoned step(s):")
        for step in stale:
            age = timezone.now() - step.started_at
            minutes = int(age.total_seconds() // 60)
            self.stdout.write(
                f"  step {step.pk:<5} {step.step_type:<12} video {step.video_id:<5} "
                f"running for {minutes} min"
            )
            if options["dry_run"]:
                continue
            StepRepository.update(
                step,
                status=StepStatus.FAILED,
                error_message=MESSAGE,
                finished_at=timezone.now(),
            )
            VideoRepository.update(
                step.video, status=VideoStatus.FAILED, error_message=MESSAGE
            )

        if options["dry_run"]:
            self.stdout.write("\nDry run — nothing changed.")
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nFailed {len(stale)} step(s). Retry them from each video's page."
                )
            )
