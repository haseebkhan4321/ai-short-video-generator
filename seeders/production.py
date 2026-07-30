"""The production seeder: the minimum a live install needs to work.

Deliberately boring. It creates no demo content, invents no credentials, and never
resets an existing user's password. Two things only:

1. The system default roles, without which a new account has no roles at all.
2. The first system administrator and their account — after a fresh migrate nothing
   is reachable anonymously and accounts are created by an administrator, so this is
   the only way in.

Starter templates are real content rather than demo data, so they are available
behind ``--with-templates`` but off by default: what a live account should contain is
the operator's decision.
"""
from .accounts import FirstAdminSeeder
from .base import Seeder
from .roles import RoleSeeder
from .templates import TemplateSeeder


class ProductionSeeder(Seeder):
    name = "Production seed"

    def run(self, email=None, password=None, full_name="", account_name=None,
            with_templates=False, refresh_roles=False, **options):
        roles = RoleSeeder(self.command)
        roles(refresh=refresh_roles)
        self.result += roles.result

        if not email:
            self.section("First system administrator")
            self.skipped("no --email given, so no administrator was created")
            self.note(
                "Roles are seeded. Re-run with --email and --account to create the "
                "first administrator."
            )
            return None, None

        admin = FirstAdminSeeder(self.command)
        user, account = admin(
            email=email,
            password=password,
            full_name=full_name,
            account_name=account_name,
        )
        self.result += admin.result

        if with_templates and account is not None:
            templates = TemplateSeeder(self.command)
            templates(account=account)
            self.result += templates.result

        return user, account
