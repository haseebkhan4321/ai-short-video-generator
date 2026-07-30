"""Add the starter content templates to one account.

The targeted tool, separate from the two environment seeders: use it when an account
already exists and just needs the starter set.

    python manage.py seed_templates --account my-studio
"""
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.repositories import AccountRepository
from seeders.templates import TemplateSeeder


class Command(BaseCommand):
    help = "Seed the starter content templates into an existing account."

    def add_arguments(self, parser):
        parser.add_argument(
            "--account", required=True, help="Slug of the target account."
        )
        parser.add_argument(
            "--only",
            nargs="+",
            help="Seed only these template names instead of all of them.",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Overwrite existing templates (matched by name) instead of skipping.",
        )

    def handle(self, *args, **options):
        account = AccountRepository.get_by_slug(options["account"])
        if account is None:
            raise CommandError(
                f"No account with slug '{options['account']}'. Run seed_production "
                "first, or check the slug at /accounts/settings/."
            )

        seeder = TemplateSeeder(self)
        seeder(account=account, only=options["only"], update=options["update"])
        self.stdout.write(self.style.SUCCESS(f"\nDone for '{account.name}'."))
