"""Data-access layer for accounts. The only place these ORM queries live."""
from .models import Account, AccountRequest, Membership, RequestStatus, Role, User


class UserRepository:
    @staticmethod
    def all():
        return User.objects.all()

    @staticmethod
    def get_or_none(user_id):
        return User.objects.filter(pk=user_id).first()

    @staticmethod
    def get_by_email(email):
        return User.objects.filter(email__iexact=email).first()

    @staticmethod
    def create(email, password, **fields):
        return User.objects.create_user(email=email, password=password, **fields)

    @staticmethod
    def update(user, **fields):
        for key, value in fields.items():
            setattr(user, key, value)
        user.save()
        return user

    @staticmethod
    def set_password(user, raw_password):
        user.set_password(raw_password)
        user.save(update_fields=["password"])
        return user

    @staticmethod
    def delete(user):
        user.delete()

    @staticmethod
    def system_admins():
        return User.objects.filter(is_system_admin=True, is_active=True)


class AccountRepository:
    @staticmethod
    def all():
        return Account.objects.select_related("owner")

    @staticmethod
    def get_or_none(account_id):
        return Account.objects.filter(pk=account_id).first()

    @staticmethod
    def get_by_slug(slug):
        return Account.objects.filter(slug=slug).first()

    @staticmethod
    def create(**fields):
        return Account.objects.create(**fields)

    @staticmethod
    def update(account, **fields):
        for key, value in fields.items():
            setattr(account, key, value)
        account.save()
        return account

    @staticmethod
    def delete(account):
        account.delete()


class RoleRepository:
    @staticmethod
    def for_account(account):
        return Role.objects.filter(account=account)

    @staticmethod
    def system_defaults():
        return Role.objects.filter(account__isnull=True)

    @staticmethod
    def get_or_none(role_id):
        return Role.objects.filter(pk=role_id).first()

    @staticmethod
    def get_in_account(role_id, account):
        return Role.objects.filter(pk=role_id, account=account).first()

    @staticmethod
    def get_by_name(account, name):
        return Role.objects.filter(account=account, name=name).first()

    @staticmethod
    def create(**fields):
        return Role.objects.create(**fields)

    @staticmethod
    def update(role, **fields):
        for key, value in fields.items():
            setattr(role, key, value)
        role.save()
        return role

    @staticmethod
    def delete(role):
        role.delete()

    @staticmethod
    def is_in_use(role):
        return role.memberships.exists()


class MembershipRepository:
    @staticmethod
    def for_account(account):
        return Membership.objects.filter(account=account).select_related(
            "user", "role", "invited_by"
        )

    @staticmethod
    def for_user(user):
        return (
            Membership.objects.filter(user=user, is_active=True, account__is_active=True)
            .select_related("account", "role")
            .order_by("account__name")
        )

    @staticmethod
    def get(user, account):
        return (
            Membership.objects.filter(user=user, account=account)
            .select_related("account", "role")
            .first()
        )

    @staticmethod
    def get_active(user, account):
        return (
            Membership.objects.filter(
                user=user, account=account, is_active=True, account__is_active=True
            )
            .select_related("account", "role")
            .first()
        )

    @staticmethod
    def get_in_account(membership_id, account):
        return (
            Membership.objects.filter(pk=membership_id, account=account)
            .select_related("user", "role")
            .first()
        )

    @staticmethod
    def create(**fields):
        return Membership.objects.create(**fields)

    @staticmethod
    def update(membership, **fields):
        for key, value in fields.items():
            setattr(membership, key, value)
        membership.save()
        return membership

    @staticmethod
    def delete(membership):
        membership.delete()


class AccountRequestRepository:
    @staticmethod
    def all():
        return AccountRequest.objects.select_related("user", "reviewed_by", "account")

    @staticmethod
    def pending():
        return AccountRequestRepository.all().filter(status=RequestStatus.PENDING)

    @staticmethod
    def pending_count():
        return AccountRequest.objects.filter(status=RequestStatus.PENDING).count()

    @staticmethod
    def get_or_none(request_id):
        return AccountRequestRepository.all().filter(pk=request_id).first()

    @staticmethod
    def has_pending_for_email(email):
        return AccountRequest.objects.filter(
            email__iexact=email, status=RequestStatus.PENDING
        ).exists()

    @staticmethod
    def create(**fields):
        return AccountRequest.objects.create(**fields)

    @staticmethod
    def save(account_request):
        account_request.save()
        return account_request
