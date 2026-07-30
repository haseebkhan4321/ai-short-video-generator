"""Is the queue working? Tells a stopped broker apart from a stopped worker.

Those two failures look identical from the app — steps sit APPROVED and nothing
happens — but the fix is different, so it is worth being able to tell them apart in
one command.

    python manage.py queue_status
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.videos.models import StepStatus
from apps.videos.repositories import StepRepository


class Command(BaseCommand):
    help = "Check the broker and workers, and show what the queue is holding."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=float,
            default=5.0,
            help="Seconds to wait for a worker to answer (default 5).",
        )

    def handle(self, *args, **options):
        self.stdout.write(f"Broker: {settings.CELERY_BROKER_URL}")

        broker_ok = self._check_broker()
        workers = self._check_workers(options["timeout"]) if broker_ok else None
        self._show_backlog()

        if not broker_ok:
            self.stdout.write(
                self.style.ERROR(
                    "\nThe broker is unreachable, so nothing can be queued.\n"
                    "  Start it:  redis-server"
                )
            )
            return
        if not workers:
            self.stdout.write(
                self.style.ERROR(
                    "\nThe broker is up but no worker answered, so approved steps will "
                    "queue and sit there.\n"
                    "  Start one:  celery -A config worker -l info --pool=threads "
                    "--concurrency=4"
                )
            )
            return
        self.stdout.write(self.style.SUCCESS("\nBroker and worker are both up."))

    def _check_broker(self):
        from config.celery import app

        try:
            connection = app.connection()
            connection.ensure_connection(max_retries=1, timeout=4)
            connection.release()
            self.stdout.write(self.style.SUCCESS("  broker   reachable"))
            return True
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  broker   unreachable — {exc}"))
            return False

    def _check_workers(self, timeout):
        from config.celery import app

        try:
            replies = app.control.ping(timeout=timeout) or []
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  workers  could not ping — {exc}"))
            return None
        if not replies:
            self.stdout.write(self.style.ERROR("  workers  none answered"))
            return None
        names = ", ".join(sorted(name for reply in replies for name in reply))
        self.stdout.write(self.style.SUCCESS(f"  workers  {len(replies)} — {names}"))
        return replies

    def _show_backlog(self):
        counts = {
            label: StepRepository.by_status(status).count()
            for label, status in (
                ("approved (waiting for a worker)", StepStatus.APPROVED),
                ("running", StepStatus.RUNNING),
                ("pending approval", StepStatus.PENDING_APPROVAL),
                ("failed", StepStatus.FAILED),
            )
        }
        self.stdout.write("\nSteps:")
        for label, count in counts.items():
            style = self.style.WARNING if count and "approved" in label else str
            self.stdout.write(f"  {style(str(count)):>3}  {label}")
