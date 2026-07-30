"""Small helpers shared by the test modules. Plain functions, no extra dependency."""
from apps.accounts.models import User
from apps.accounts.permissions import PRODUCER_ROLE, VIEWER_ROLE, Perm
from apps.accounts.repositories import MembershipRepository, RoleRepository
from apps.accounts.services import AccountService, RoleService
from apps.templates.services import TemplateService
from apps.videos.services.pipeline import PipelineService

PASSWORD = "correct-horse-battery-9"


def make_user(email, **fields):
    fields.setdefault("is_active", True)
    return User.objects.create_user(email=email, password=PASSWORD, **fields)


def make_system_admin(email="admin@example.com"):
    return make_user(email, is_system_admin=True)


def make_account(owner, name="Test Studio"):
    """An account with the default roles cloned in and ``owner`` as Owner."""
    RoleService.seed_system_defaults()
    return AccountService.create_for_owner(owner, name)


def add_member(account, user, role_name=VIEWER_ROLE):
    role = RoleRepository.get_by_name(account, role_name)
    return MembershipRepository.create(user=user, account=account, role=role)


def make_role(account, name, codenames):
    return RoleRepository.create(
        account=account, name=name, permissions=list(codenames)
    )


def make_template(account, name="Horror"):
    return TemplateService.create_template(
        account, {"name": name, "style_prompt": "spooky"}
    )


def make_video(template, actor=None, premise="a haunted house", minutes=30):
    """A video plus its initial pending (paid) script step."""
    return PipelineService.create_video(
        template=template, premise=premise, target_minutes=minutes, actor=actor
    )


__all__ = [
    "PASSWORD",
    "PRODUCER_ROLE",
    "VIEWER_ROLE",
    "Perm",
    "add_member",
    "make_account",
    "make_role",
    "make_system_admin",
    "make_template",
    "make_user",
    "make_video",
]
