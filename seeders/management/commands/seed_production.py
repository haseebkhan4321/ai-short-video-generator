"""Seed a live install: the default roles, and the first system administrator.

No demo data. Idempotent — safe to re-run.

    python manage.py seed_production --email you@example.com --account "My Studio"
    python manage.py seed_production --roles-only
"""
from getpass import getpass

from django.core.management.base import BaseCommand
from django.db import transaction

from seeders.production import ProductionSeeder
from seeders.roles import RoleSeeder


class Command(BaseCommand):
    help = "Seed the minimum a production install needs: default roles + first admin."

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Email for the first system administrator.")
        parser.add_argument(
            "--password",
            help="Their password. Prompted for if omitted. Ignored for an existing user.",
        )
        parser.add_argument("--name", default="", help="Their full name.")
        parser.add_argument(
            "--account", help="Name of the account to create and make them Owner of."
        )
        parser.add_argument(
            "--with-templates",
            action="store_true",
            help="Also add the starter content templates to that account.",
        )
        parser.add_argument(
            "--roles-only",
            action="store_true",
            help="Only seed the default roles. Creates no user.",
        )
        parser.add_argument(
            "--refresh-roles",
            action="store_true",
            help="Re-apply the permission catalog to the default roles, discarding "
            "any edits made at /console/default-roles/.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["roles_only"]:
            seeder = RoleSeeder(self)
            seeder(refresh=options["refresh_roles"])
            self.stdout.write(self.style.SUCCESS("\nDefault roles seeded."))
            return

        password = options["password"]
        if options["email"] and password is None:
            # Prompted rather than defaulted: a seeder that invents a production
            # password is a seeder that ships a known credential.
            password = getpass(f"Password for {options['email']} (blank if existing): ")

        seeder = ProductionSeeder(self)
        user, account = seeder(
            email=options["email"],
            password=password,
            full_name=options["name"],
            account_name=options["account"],
            with_templates=options["with_templates"],
            refresh_roles=options["refresh_roles"],
        )

        if user is None:
            return

        self.stdout.write(self.style.SUCCESS(f"\nDone. Sign in at /accounts/login/ as {user.email}."))
        if account is not None:
            self.stdout.write(
                "Add starter templates later with:\n"
                f"  python manage.py seed_templates --account {account.slug}"
            )
