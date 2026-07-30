"""Access control: active-account resolution, permission checks, decorators.

Every authorization decision in the project funnels through here. Views declare
what they need with ``@requires_perm(Perm.X)``; templates read the ``can`` dict the
context processor builds. Nothing else should inspect memberships or roles.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from . import permissions as perms
from .permissions import ALL_CODENAMES, Perm  # noqa: F401  (re-exported for views)
from .repositories import AccountRequestRepository, MembershipRepository

SESSION_ACCOUNT_KEY = "active_account_id"


class AccessContext:
    """The caller's active account and what they may do in it."""

    __slots__ = ("account", "membership", "codenames", "is_system_admin")

    def __init__(self, account=None, membership=None, codenames=frozenset(),
                 is_system_admin=False):
        self.account = account
        self.membership = membership
        self.codenames = codenames
        self.is_system_admin = is_system_admin

    def has(self, codename):
        return codename in self.codenames

    def has_any(self, *codenames):
        return any(c in self.codenames for c in codenames)


EMPTY_CONTEXT = AccessContext()


def resolve_context(request):
    """Work out the active account and permission set for this request.

    The account comes from the session when the user has a live membership there.
    Otherwise it falls back to their first membership, so a normal user never has
    to pick an account. A system admin gets the full catalog in whatever account
    they are looking at, and may enter an account without a membership.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return EMPTY_CONTEXT

    is_admin = bool(user.is_system_admin)
    session_account_id = request.session.get(SESSION_ACCOUNT_KEY)

    membership = None
    account = None

    if session_account_id:
        membership = MembershipRepository.get_active(user, session_account_id)
        if membership is not None:
            account = membership.account

    if account is None and is_admin and session_account_id:
        # System admins can enter any account, membership or not.
        from .repositories import AccountRepository

        account = AccountRepository.get_or_none(session_account_id)

    if account is None:
        membership = MembershipRepository.for_user(user).first()
        if membership is not None:
            account = membership.account
            # Remember the fallback so later requests skip this lookup.
            request.session[SESSION_ACCOUNT_KEY] = account.pk

    if is_admin:
        codenames = ALL_CODENAMES
    elif membership is not None:
        codenames = membership.role.codenames
    else:
        codenames = frozenset()

    return AccessContext(
        account=account,
        membership=membership,
        codenames=codenames,
        is_system_admin=is_admin,
    )


def context_for(request):
    """The request's ``AccessContext``, resolving it if the middleware has not."""
    ctx = getattr(request, "access", None)
    if ctx is None:
        ctx = resolve_context(request)
        request.access = ctx
    return ctx


def has_perm(request, codename):
    return context_for(request).has(codename)


def active_account(request):
    return context_for(request).account


class AccountMiddleware:
    """Attach ``request.access``, ``request.account`` and ``request.membership``.

    Resolution is cheap for anonymous requests and never blocks one: a missing
    account is a value of ``None``, not an error. Enforcing that an account exists
    is ``@account_required``'s job, so unscoped pages (login, the account request
    form, the console) still get a populated nav.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.access = resolve_context(request)
        request.account = request.access.account
        request.membership = request.access.membership
        return self.get_response(request)


# Which sidebar entry a view belongs under. Keyed by URL namespace, then by the
# url_name for namespaces that cover more than one section. Computed here rather
# than in the template because Django templates cannot test a string prefix.
_NAV_BY_NAMESPACE = {
    "videos": "videos",
    "templates": "templates",
    "console": "console",
}
_NAV_BY_URL_NAME = {
    "user_list": "users",
    "user_create": "users",
    "user_edit": "users",
    "user_remove": "users",
    "role_list": "roles",
    "role_create": "roles",
    "role_edit": "roles",
    "role_delete": "roles",
    "settings": "settings",
    "my_profile": "profile",
}


def nav_section(request):
    """The sidebar entry to mark active, or None."""
    match = getattr(request, "resolver_match", None)
    if match is None:
        return None
    section = _NAV_BY_NAMESPACE.get(match.namespace)
    if section is not None:
        return section
    return _NAV_BY_URL_NAME.get(match.url_name)


def access_context(request):
    """Template context processor: ``account``, ``can``, and the active nav entry."""
    ctx = context_for(request)
    user = getattr(request, "user", None)

    memberships = []
    if user is not None and user.is_authenticated:
        memberships = list(MembershipRepository.for_user(user))

    return {
        "account": ctx.account,
        "membership": ctx.membership,
        "account_memberships": memberships,
        "is_system_admin": ctx.is_system_admin,
        "nav": nav_section(request),
        # Badge on the Console link. Only queried for the people who can act on it.
        "pending_request_count": (
            AccountRequestRepository.pending_count() if ctx.is_system_admin else 0
        ),
        # Underscored keys: Django templates cannot resolve a dotted dict key.
        "can": {
            perms.as_template_key(codename): codename in ctx.codenames
            for codename in perms.ALL_CODENAMES
        },
    }


# ---- Decorators ----


def account_required(view):
    """Require a login and a resolved active account."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if context_for(request).account is None:
            return redirect(reverse("accounts:no_account"))
        return view(request, *args, **kwargs)

    return wrapper


def requires_perm(*codenames):
    """Require a login, an active account, and every listed permission."""

    def decorator(view):
        @wraps(view)
        @account_required
        def wrapper(request, *args, **kwargs):
            ctx = context_for(request)
            missing = [c for c in codenames if not ctx.has(c)]
            if missing:
                raise PermissionDenied(
                    "You do not have permission to do this "
                    f"({', '.join(perms.LABELS.get(c, c) for c in missing)})."
                )
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def system_admin_required(view):
    """Restrict to app-level system admins. Not account-scoped."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_system_admin:
            raise PermissionDenied("System administrators only.")
        return view(request, *args, **kwargs)

    return wrapper
