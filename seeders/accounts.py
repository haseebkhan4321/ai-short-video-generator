"""Seeds users, accounts, custom roles and memberships."""
from apps.accounts import permissions as perms
from apps.accounts.models import Account
from apps.accounts.repositories import (
    AccountRepository,
    MembershipRepository,
    RoleRepository,
    UserRepository,
)
from apps.accounts.services import AccountService

from .base import Seeder


class UserSeeder(Seeder):
    """Creates users. Never touches an existing one's password."""

    name = "Users"

    def run(self, users=(), password=None, **options):
        created = {}
        for spec in users:
            user = UserRepository.get_by_email(spec["email"])
            if user is not None:
                self.existed(spec["email"])
            else:
                user = UserRepository.create(
                    email=spec["email"],
                    password=spec.get("password") or password,
                    full_name=spec.get("full_name", ""),
                    is_active=True,
                    is_staff=spec.get("is_staff", False),
                    is_superuser=spec.get("is_superuser", False),
                    is_system_admin=spec.get("is_system_admin", False),
                )
                flags = " ".join(
                    label
                    for label, on in (
                        ("system-admin", spec.get("is_system_admin")),
                        ("staff", spec.get("is_staff")),
                    )
                    if on
                )
                self.created(f"{spec['email']}{' [' + flags + ']' if flags else ''}")
            created[spec["email"]] = user
        return created


class AccountSeeder(Seeder):
    """Creates an account with its owner, extra roles and members.

    Account creation goes through ``AccountService.create_for_owner`` so the default
    roles are cloned and the owner membership is built exactly as they would be for a
    real signup — a fixture that skipped that would not resemble production.
    """

    name = "Accounts"

    def run(self, accounts=(), password=None, **options):
        built = {}
        for spec in accounts:
            account = self._account(spec, password)
            self._extra_roles(account, spec.get("extra_roles", ()))
            self._members(account, spec.get("members", ()), password)
            built[spec["name"]] = account
        return built

    def _account(self, spec, password):
        # Look up by name, not slug: Account.unique_slug appends a suffix when the
        # slug is taken, so a slug-based check would create a second account on the
        # next run.
        existing = AccountRepository.all().filter(name=spec["name"]).first()
        if existing is not None:
            self.existed(f"account {spec['name']}")
            return existing

        owner_spec = spec["owner"]
        owner = UserRepository.get_by_email(owner_spec["email"])
        if owner is None:
            owner = UserRepository.create(
                email=owner_spec["email"],
                password=password,
                full_name=owner_spec.get("full_name", ""),
                is_active=True,
            )
            self.created(f"user {owner_spec['email']}")

        account = AccountService.create_for_owner(owner, spec["name"])
        self.created(
            f"account {account.name} (slug {account.slug}, owner {owner.email})"
        )
        return account

    def _extra_roles(self, account, role_specs):
        for spec in role_specs:
            if RoleRepository.get_by_name(account, spec["name"]) is not None:
                self.existed(f"role {spec['name']} in {account.name}")
                continue
            RoleRepository.create(
                account=account,
                name=spec["name"],
                description=spec.get("description", ""),
                permissions=perms.clean(spec["permissions"]),
            )
            self.created(f"role {spec['name']} in {account.name}")

    def _members(self, account, member_specs, password):
        for spec in member_specs:
            user = UserRepository.get_by_email(spec["email"])
            if user is None:
                user = UserRepository.create(
                    email=spec["email"],
                    password=password,
                    full_name=spec.get("full_name", ""),
                    is_active=True,
                )
                self.created(f"user {spec['email']}")

            if MembershipRepository.get(user, account) is not None:
                self.existed(f"{spec['email']} in {account.name}")
                continue

            role = RoleRepository.get_by_name(account, spec["role"])
            if role is None:
                self.fail(
                    f"No role '{spec['role']}' in {account.name}. Seed the default "
                    "roles first."
                )
            MembershipRepository.create(user=user, account=account, role=role)
            self.created(f"{spec['email']} as {role.name} in {account.name}")


class FirstAdminSeeder(Seeder):
    """The production entry point: one system administrator and their account.

    After a fresh migrate nothing is reachable, so this is the only way in. It
    refuses to invent credentials and never resets an existing user's password.
    """

    name = "First system administrator"

    def run(self, email=None, password=None, full_name="", account_name=None, **options):
        if not email:
            self.fail("--email is required to create the first administrator.")

        user = UserRepository.get_by_email(email)
        if user is None:
            if not password:
                self.fail("A password is required for a new administrator.")
            user = UserRepository.create(
                email=email,
                password=password,
                full_name=full_name,
                is_active=True,
                is_staff=True,
                is_superuser=True,
                is_system_admin=True,
            )
            self.created(f"{email} (system admin, Django staff)")
        else:
            changes = {}
            if not user.is_system_admin:
                changes["is_system_admin"] = True
            if not user.is_active:
                changes["is_active"] = True
            if changes:
                UserRepository.update(user, **changes)
                self.updated(f"{email} promoted to system admin")
            else:
                self.existed(f"{email} (already a system admin)")
            self.note("Password left untouched for an existing user.")

        account = None
        if account_name:
            account = self._account_for(user, account_name)
        else:
            existing = MembershipRepository.for_user(user).first()
            if existing is not None:
                account = existing.account
            else:
                self.skipped("no account (pass --account to create one)")

        return user, account

    def _account_for(self, user, account_name):
        existing = AccountRepository.all().filter(name=account_name).first()
        if existing is not None:
            self.existed(f"account {account_name} (slug {existing.slug})")
            return existing

        held = MembershipRepository.for_user(user).first()
        if held is not None:
            self.skipped(
                f"account {account_name} — {user.email} already belongs to "
                f"'{held.account.name}'"
            )
            return held.account

        account = AccountService.create_for_owner(user, account_name)
        self.created(f"account {account.name} (slug {account.slug}), owner is Owner")
        return account


def slug_preview(name):
    """The slug an account with this name would get, for help text."""
    return Account.unique_slug(name)
