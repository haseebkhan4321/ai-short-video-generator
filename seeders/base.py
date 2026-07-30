"""Shared plumbing for seeders.

A seeder is a small class with a ``run()`` method. Two rules apply to all of them:

1. **Idempotent.** Re-running must not duplicate anything. Every seeder looks a row
   up before creating it and reports ``created`` / ``existed`` per row.
2. **Repositories only.** Seeders go through the repositories like everything else,
   so account scoping and the model's own defaults are never bypassed.

Seeders deliberately do *not* go through the services for the RBAC invariants
(privilege escalation, last-administrator). A seeder is trusted setup code, and a
fixture that has to satisfy "you cannot grant what you do not hold" would need a
fake actor to grant from.
"""
from django.core.management.base import CommandError


class SeedResult:
    """Per-seeder tally, so a run's output is a summary rather than a wall of text."""

    __slots__ = ("created", "existed", "updated", "skipped")

    def __init__(self):
        self.created = 0
        self.existed = 0
        self.updated = 0
        self.skipped = 0

    def __iadd__(self, other):
        self.created += other.created
        self.existed += other.existed
        self.updated += other.updated
        self.skipped += other.skipped
        return self

    @property
    def total(self):
        return self.created + self.existed + self.updated + self.skipped

    def __str__(self):
        bits = []
        for label in ("created", "existed", "updated", "skipped"):
            value = getattr(self, label)
            if value:
                bits.append(f"{label}={value}")
        return ", ".join(bits) or "nothing to do"


class Seeder:
    """Base class. Subclasses set ``name`` and implement ``run``."""

    name = "seeder"

    def __init__(self, command=None, verbose=True):
        # ``command`` is the BaseCommand, used only for styled output. Seeders are
        # runnable without one (from a shell or a test) by leaving it None.
        self.command = command
        self.verbose = verbose
        self.result = SeedResult()

    # ---- Output ----

    def _write(self, text, style=None):
        if not self.verbose or self.command is None:
            return
        if style is not None:
            text = getattr(self.command.style, style)(text)
        self.command.stdout.write(text)

    def section(self, text):
        self._write(f"\n{text}", "MIGRATE_HEADING")

    def created(self, text):
        self.result.created += 1
        self._write(f"  + {text}", "SUCCESS")

    def existed(self, text):
        self.result.existed += 1
        self._write(f"  = {text} (already there)")

    def updated(self, text):
        self.result.updated += 1
        self._write(f"  ~ {text}", "WARNING")

    def skipped(self, text):
        self.result.skipped += 1
        self._write(f"  - {text}")

    def note(self, text):
        self._write(f"    {text}")

    def warn(self, text):
        self._write(f"  ! {text}", "WARNING")

    def fail(self, text):
        raise CommandError(text)

    # ---- Contract ----

    def run(self, **options):
        raise NotImplementedError

    def __call__(self, **options):
        self.section(self.name)
        outcome = self.run(**options)
        self._write(f"    {self.result}")
        return outcome
