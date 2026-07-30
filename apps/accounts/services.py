"""Business logic for accounts, roles, memberships and account requests.

Views call these; these call the repositories. All the invariants that keep RBAC
honest live here — privilege escalation, the last administrator, the account owner
— so they hold no matter which view is the caller.
"""
from django.db import transaction

from . import permissions as perms
from .models import Account, RequestStatus
from .permissions import DEFAULT_ROLES, OWNER_ROLE, Perm
from .repositories import (
    AccountRepository,
    AccountRequestRepository,
    MembershipRepository,
    RoleRepository,
    UserRepository,
)


class AccessError(Exception):
    """A request that a permission check allowed but an invariant forbids."""


class RoleService:
    @staticmethod
    def list_for_account(account):
        return RoleRepository.for_account(account)

    @staticmethod
    def get(role_id, account):
        return RoleRepository.get_in_account(role_id, account)

    @staticmethod
    def seed_system_defaults():
        """Create or refresh the ``account=None`` template roles. Idempotent."""
        created = []
        for spec in DEFAULT_ROLES:
            role = RoleRepository.get_by_name(None, spec["name"])
            if role is None:
                role = RoleRepository.create(
                    account=None,
                    name=spec["name"],
                    description=spec["description"],
                    permissions=perms.clean(spec["permissions"]),
                    is_system_default=True,
                )
                created.append(role)
        return created

    @staticmethod
    def clone_defaults_into(account):
        """Give a new account its starting roles, copied from the system defaults."""
        defaults = list(RoleRepository.system_defaults())
        if not defaults:
            RoleService.seed_system_defaults()
            defaults = list(RoleRepository.system_defaults())

        roles = {}
        for template in defaults:
            roles[template.name] = RoleRepository.create(
                account=account,
                name=template.name,
                description=template.description,
                permissions=perms.clean(template.permissions),
                is_system_default=False,
            )
        return roles

    @staticmethod
    def create(account, name, description, codenames, granted_by_codenames):
        RoleService._assert_no_escalation(codenames, granted_by_codenames)
        if RoleRepository.get_by_name(account, name):
            raise AccessError(f"A role called '{name}' already exists in this account.")
        return RoleRepository.create(
            account=account,
            name=name,
            description=description,
            permissions=perms.clean(codenames),
        )

    @staticmethod
    def update(role, name, description, codenames, granted_by_codenames, actor):
        RoleService._assert_no_escalation(codenames, granted_by_codenames)
        clash = RoleRepository.get_by_name(role.account, name)
        if clash is not None and clash.pk != role.pk:
            raise AccessError(f"A role called '{name}' already exists in this account.")

        cleaned = perms.clean(codenames)
        # Do not let someone lock every administrator out of the account. System
        # default roles (account=None) have no memberships, so they are exempt.
        if (
            role.account_id is not None
            and Perm.ACCOUNT_MANAGE_USERS in role.codenames
            and Perm.ACCOUNT_MANAGE_USERS not in cleaned
        ):
            RoleService._assert_not_last_admin_role(role, actor)

        return RoleRepository.update(
            role,
            name=name,
            description=description,
            permissions=cleaned,
        )

    @staticmethod
    def delete(role):
        if RoleRepository.is_in_use(role):
            raise AccessError(
                "This role is still assigned to someone. Move them to another role first."
            )
        RoleRepository.delete(role)

    @staticmethod
    def _assert_no_escalation(codenames, granted_by_codenames):
        """Nobody may grant a permission they do not hold themselves."""
        extra = set(perms.clean(codenames)) - set(granted_by_codenames)
        if extra:
            labels = ", ".join(sorted(perms.LABELS.get(c, c) for c in extra))
            raise AccessError(
                f"You cannot grant permissions you do not hold yourself: {labels}."
            )

    @staticmethod
    def _assert_not_last_admin_role(role, actor):
        """Refuse to remove user management from the only role that still has it."""
        account = role.account
        others = [
            m
            for m in MembershipRepository.for_account(account).filter(is_active=True)
            if m.role_id != role.pk and Perm.ACCOUNT_MANAGE_USERS in m.role.codenames
        ]
        if not others:
            raise AccessError(
                "This is the only role that can manage users. Give another role that "
                "permission first, or you will lock everyone out of this account."
            )


class AccountService:
    @staticmethod
    def list_all():
        return AccountRepository.all()

    @staticmethod
    def get(account_id):
        return AccountRepository.get_or_none(account_id)

    @staticmethod
    @transaction.atomic
    def create_for_owner(owner, name):
        """Create an account, clone the default roles into it, make ``owner`` Owner."""
        account = AccountRepository.create(
            name=name,
            slug=Account.unique_slug(name),
            owner=owner,
        )
        roles = RoleService.clone_defaults_into(account)
        MembershipRepository.create(
            user=owner,
            account=account,
            role=roles[OWNER_ROLE],
        )
        return account

    @staticmethod
    def rename(account, name):
        return AccountRepository.update(account, name=name)

    @staticmethod
    def set_active(account, is_active):
        return AccountRepository.update(account, is_active=is_active)

    @staticmethod
    def switchable_for(user):
        """Accounts the user may switch into."""
        if user.is_system_admin:
            return AccountRepository.all().filter(is_active=True)
        return [m.account for m in MembershipRepository.for_user(user)]

    @staticmethod
    def can_switch_to(user, account_id):
        if user.is_system_admin:
            account = AccountRepository.get_or_none(account_id)
            return account is not None and account.is_active
        return MembershipRepository.get_active(user, account_id) is not None


class MembershipService:
    @staticmethod
    def list_for_account(account):
        return MembershipRepository.for_account(account)

    @staticmethod
    def get(membership_id, account):
        return MembershipRepository.get_in_account(membership_id, account)

    @staticmethod
    @transaction.atomic
    def add_user(account, email, full_name, password, role, invited_by,
                 granted_by_codenames):
        """Add a user to ``account``. Created active — no system-admin approval.

        If the email already belongs to a user, they gain a membership rather than
        a duplicate account.
        """
        RoleService._assert_no_escalation(role.codenames, granted_by_codenames)

        user = UserRepository.get_by_email(email)
        if user is None:
            if not password:
                raise AccessError("A password is required for a new user.")
            user = UserRepository.create(
                email=email,
                password=password,
                full_name=full_name,
                is_active=True,
                must_change_password=True,
            )
        elif MembershipRepository.get(user, account) is not None:
            raise AccessError(f"{email} is already in this account.")

        return MembershipRepository.create(
            user=user,
            account=account,
            role=role,
            invited_by=invited_by,
        )

    @staticmethod
    def change_role(membership, role, actor, granted_by_codenames):
        RoleService._assert_no_escalation(role.codenames, granted_by_codenames)
        if membership.is_owner and Perm.ACCOUNT_MANAGE_USERS not in role.codenames:
            raise AccessError(
                "The account owner must keep a role that can manage users."
            )
        MembershipService._assert_not_last_admin(membership, actor, role)
        return MembershipRepository.update(membership, role=role)

    @staticmethod
    def set_active(membership, is_active, actor):
        if membership.is_owner and not is_active:
            raise AccessError("The account owner cannot be deactivated.")
        if not is_active:
            MembershipService._assert_not_last_admin(membership, actor, None)
        return MembershipRepository.update(membership, is_active=is_active)

    @staticmethod
    def remove(membership, actor):
        if membership.is_owner:
            raise AccessError("The account owner cannot be removed from the account.")
        MembershipService._assert_not_last_admin(membership, actor, None)
        MembershipRepository.delete(membership)

    @staticmethod
    def _assert_not_last_admin(membership, actor, new_role):
        """Keep at least one active user who can manage users in the account."""
        if Perm.ACCOUNT_MANAGE_USERS not in membership.role.codenames:
            return  # They were never an administrator; nothing to protect.
        if new_role is not None and Perm.ACCOUNT_MANAGE_USERS in new_role.codenames:
            return  # Still an administrator afterwards.

        remaining = [
            m
            for m in MembershipRepository.for_account(membership.account).filter(
                is_active=True
            )
            if m.pk != membership.pk and Perm.ACCOUNT_MANAGE_USERS in m.role.codenames
        ]
        if not remaining:
            raise AccessError(
                "This is the last user who can manage this account. Give someone "
                "else that permission first."
            )


class AccountRequestService:
    @staticmethod
    def list_pending():
        return AccountRequestRepository.pending()

    @staticmethod
    def list_all():
        return AccountRequestRepository.all()

    @staticmethod
    def get(request_id):
        return AccountRequestRepository.get_or_none(request_id)

    @staticmethod
    def pending_count():
        return AccountRequestRepository.pending_count()

    @staticmethod
    @transaction.atomic
    def submit(email, full_name, account_name, password, message=""):
        """Record a request from the public form.

        No email backend is configured, so the password is collected up front and
        the user is created inactive. Approval only flips ``is_active``, which means
        there is never a credential to hand over out of band.
        """
        if UserRepository.get_by_email(email) is not None:
            raise AccessError(
                "An account already exists for this email address. Try signing in."
            )
        if AccountRequestRepository.has_pending_for_email(email):
            raise AccessError(
                "A request for this email address is already awaiting review."
            )

        user = UserRepository.create(
            email=email,
            password=password,
            full_name=full_name,
            is_active=False,
        )
        return AccountRequestRepository.create(
            email=email,
            full_name=full_name,
            account_name=account_name,
            message=message,
            user=user,
        )

    @staticmethod
    @transaction.atomic
    def approve(account_request, reviewer, note=""):
        if not account_request.is_pending:
            raise AccessError("This request has already been reviewed.")

        user = account_request.user
        if user is None:
            raise AccessError(
                "The pending user for this request no longer exists. Reject it and "
                "ask them to submit a new one."
            )

        UserRepository.update(user, is_active=True)
        account = AccountService.create_for_owner(user, account_request.account_name)

        account_request.account = account
        account_request.mark_reviewed(reviewer, RequestStatus.APPROVED, note)
        AccountRequestRepository.save(account_request)
        return account

    @staticmethod
    @transaction.atomic
    def reject(account_request, reviewer, note=""):
        if not account_request.is_pending:
            raise AccessError("This request has already been reviewed.")

        # The user was only ever a placeholder for the request; drop it so the
        # email is free if they apply again.
        user = account_request.user
        account_request.mark_reviewed(reviewer, RequestStatus.REJECTED, note)
        account_request.user = None
        AccountRequestRepository.save(account_request)
        if user is not None and not user.memberships.exists():
            UserRepository.delete(user)
        return account_request


class UserAdminService:
    """System-admin-level user operations. Not account-scoped."""

    @staticmethod
    def list_all():
        return UserRepository.all().prefetch_related("memberships__account")

    @staticmethod
    def get(user_id):
        return UserRepository.get_or_none(user_id)

    @staticmethod
    def set_active(user, is_active, actor):
        if user.pk == actor.pk and not is_active:
            raise AccessError("You cannot deactivate your own account.")
        if not is_active:
            UserAdminService._assert_not_last_system_admin(user)
        return UserRepository.update(user, is_active=is_active)

    @staticmethod
    def set_system_admin(user, is_system_admin, actor):
        if user.pk == actor.pk and not is_system_admin:
            raise AccessError("You cannot remove your own system administrator role.")
        if not is_system_admin:
            UserAdminService._assert_not_last_system_admin(user)
        return UserRepository.update(user, is_system_admin=is_system_admin)

    @staticmethod
    def reset_password(user, raw_password):
        UserRepository.set_password(user, raw_password)
        return UserRepository.update(user, must_change_password=True)

    @staticmethod
    def _assert_not_last_system_admin(user):
        if not user.is_system_admin:
            return
        if not UserRepository.system_admins().exclude(pk=user.pk).exists():
            raise AccessError("This is the last system administrator.")
