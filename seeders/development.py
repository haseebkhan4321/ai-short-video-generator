"""The development seeder: everything, so the whole UI can be exercised at once.

Runs the production seed first (roles + a system admin), then adds demo data: two
accounts, a user per role including one custom role, every starter template, and a
video at each pipeline stage with real placeholder assets on disk.

Guards, because this writes well-known passwords:

- refuses to run when ``DEBUG`` is off unless ``--force`` is passed
- everything it creates is identifiable (``@dev.local`` users, two named accounts),
  so ``--fresh`` can remove exactly its own output and nothing else
"""
from django.conf import settings

from apps.accounts.repositories import (
    AccountRepository,
    MembershipRepository,
    RoleRepository,
    UserRepository,
)
from apps.templates.repositories import TemplateRepository

from .accounts import AccountSeeder, UserSeeder
from .base import Seeder
from .data import (
    DEMO_ACCOUNTS,
    DEV_EMAIL_DOMAIN,
    DEV_PASSWORD,
    DEV_SYSTEM_ADMIN,
)
from .roles import RoleSeeder
from .templates import TemplateSeeder
from .videos import VideoSeeder


class DevelopmentSeeder(Seeder):
    name = "Development seed"

    def run(self, password=None, force=False, fresh=False, with_media=True,
            with_video_files=True, audio_seconds=8, **options):
        if not settings.DEBUG and not force:
            self.fail(
                "DEBUG is off. This seeder creates users with a well-known password, "
                "so it refuses to run against a non-debug install. Pass --force if "
                "you are certain."
            )
        if not settings.DEBUG:
            self.warn("DEBUG is off and --force was passed. Creating demo users anyway.")

        password = password or DEV_PASSWORD

        if fresh:
            self._wipe()

        roles = RoleSeeder(self.command)
        roles(refresh=True)
        self.result += roles.result

        users = UserSeeder(self.command)
        admin_map = users(
            users=[
                {
                    **DEV_SYSTEM_ADMIN,
                    "is_system_admin": True,
                    "is_staff": True,
                    "is_superuser": True,
                }
            ],
            password=password,
        )
        self.result += users.result
        admin = admin_map[DEV_SYSTEM_ADMIN["email"]]

        accounts = AccountSeeder(self.command)
        built = accounts(accounts=DEMO_ACCOUNTS, password=password)
        self.result += accounts.result

        for spec in DEMO_ACCOUNTS:
            account = built[spec["name"]]

            templates = TemplateSeeder(self.command)
            template_map = templates(account=account, only=spec["templates"])
            self.result += templates.result

            if not spec.get("with_videos"):
                continue

            videos = VideoSeeder(self.command)
            videos(
                templates=template_map,
                # Attributed to the account owner, not the system admin — that is who
                # would really have clicked approve.
                actor=account.owner,
                audio_seconds=audio_seconds,
                with_media=with_media,
                with_video_files=with_video_files,
            )
            self.result += videos.result

        self._summary(password)
        return built

    # ---- Teardown ----

    def _wipe(self):
        """Delete only what this seeder creates.

        Cascades do the work: dropping an account takes its templates, and a template
        takes its videos, chapters, images, steps and API logs with it. Media files on
        disk are left alone — they are cheap, and a seeder that deleted directories
        under media/ could take a real render with it.
        """
        self.section("Removing previous development seed")

        for spec in DEMO_ACCOUNTS:
            account = AccountRepository.get_by_name(spec["name"])
            if account is None:
                continue
            templates = TemplateRepository.for_account(account).count()
            # Memberships and roles first: Membership.role is PROTECT, so a role
            # cannot go while anyone still holds it.
            MembershipRepository.for_account(account).delete()
            RoleRepository.delete_for_account(account)
            TemplateRepository.for_account(account).delete()
            name = account.name
            AccountRepository.delete(account)
            self.updated(f"dropped account {name} ({templates} template(s) and content)")

        for user in list(UserRepository.with_email_domain(DEV_EMAIL_DOMAIN)):
            MembershipRepository.all_for_user(user).delete()
            email = user.email
            UserRepository.delete(user)
            self.updated(f"dropped user {email}")

    # ---- Output ----

    def _summary(self, password):
        self.section("Sign in with")

        # Grouped by user rather than by account, so someone who belongs to two
        # accounts is shown once with both roles — that is the account switcher.
        roles = {DEV_SYSTEM_ADMIN["email"]: ["system admin (every account, /console/)"]}
        for spec in DEMO_ACCOUNTS:
            roles.setdefault(spec["owner"]["email"], []).append(
                f"Owner of {spec['name']}"
            )
            for member in spec["members"]:
                roles.setdefault(member["email"], []).append(
                    f"{member['role']} in {spec['name']}"
                )

        width = max(len(email) for email in roles)
        for email, notes in roles.items():
            self._write(f"  {email:<{width}}  {', '.join(notes)}")

        self._write(f"\n  password for all of them: {password}")
        self.note("Change it, or keep this install off any shared network.")
        self._write("")
        self.note(
            "The 'narrated' video has no render yet on purpose — open it to watch the "
            "part and final renders run for real."
        )
