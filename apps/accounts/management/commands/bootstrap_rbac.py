"""Seed the default roles and create the first system administrator.

After a fresh migrate there is no way into the app: every page needs a login and
every account is created by an administrator. This command is that way in.

Idempotent — safe to re-run.

    python manage.py bootstrap_rbac --email you@example.com --account "My Studio"
"""
from getpass import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.repositories import MembershipRepository, UserRepository
from apps.accounts.services import AccountService, RoleService


class Command(BaseCommand):
    help = "Seed default roles and create the first system administrator + account."

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Email for the system administrator.")
        parser.add_argument("--password", help="Password (prompted if omitted).")
        parser.add_argument("--name", default="", help="Their full name.")
        parser.add_argument(
            "--account",
            help="Name of the account to create for them. Skipped if omitted.",
        )
        parser.add_argument(
            "--roles-only",
            action="store_true",
            help="Only seed the default roles; do not create a user.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        created_roles = RoleService.seed_system_defaults()
        if created_roles:
            names = ", ".join(r.name for r in created_roles)
            self.stdout.write(self.style.SUCCESS(f"Seeded default roles: {names}"))
        else:
            self.stdout.write("Default roles already present.")

        if options["roles_only"]:
            return

        email = options["email"]
        if not email:
            raise CommandError(
                "--email is required (or pass --roles-only to just seed the roles)."
            )

        user = UserRepository.get_by_email(email)
        if user is None:
            password = options["password"] or getpass("Password: ")
            if not password:
                raise CommandError("A password is required.")
            user = UserRepository.create(
                email=email,
                password=password,
                full_name=options["name"],
                is_active=True,
                is_staff=True,
                is_superuser=True,
                is_system_admin=True,
            )
            self.stdout.write(self.style.SUCCESS(f"Created system administrator {email}"))
        else:
            updates = {}
            if not user.is_system_admin:
                updates["is_system_admin"] = True
            if not user.is_active:
                updates["is_active"] = True
            if updates:
                UserRepository.update(user, **updates)
                self.stdout.write(self.style.WARNING(f"Promoted {email} to system admin"))
            else:
                self.stdout.write(f"{email} already a system administrator.")

        account_name = options["account"]
        if not account_name:
            self.stdout.write("No --account given; skipping account creation.")
            return

        existing = MembershipRepository.for_user(user).first()
        if existing is not None:
            self.stdout.write(
                f"{email} already owns/belongs to '{existing.account.name}' "
                f"(slug {existing.account.slug}); skipping account creation."
            )
            account = existing.account
        else:
            account = AccountService.create_for_owner(user, account_name)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created account '{account.name}' (slug {account.slug}) "
                    f"with {email} as Owner"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Sign in at /accounts/login/ as {email}.\n"
                f"Seed starter templates with:\n"
                f"  python manage.py seed_templates --account {account.slug}"
            )
        )
