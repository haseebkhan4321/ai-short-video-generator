"""The system administrator's console.

Deliberately outside account scope: these views act across every account, so they
are gated on ``is_system_admin`` rather than on a per-account permission.
"""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from .access import SESSION_ACCOUNT_KEY, system_admin_required
from .forms import RoleForm, SetPasswordForm
from .permissions import ALL_CODENAMES
from .repositories import RoleRepository
from .services import (
    AccessError,
    AccountRequestService,
    AccountService,
    RoleService,
    UserAdminService,
)


@system_admin_required
def dashboard(request):
    return render(
        request,
        "accounts/console/dashboard.html",
        {
            "pending_count": AccountRequestService.pending_count(),
            "user_count": UserAdminService.list_all().count(),
            "account_count": AccountService.list_all().count(),
            "pending_requests": AccountRequestService.list_pending()[:5],
        },
    )


# ---- Account requests ----


@system_admin_required
def request_list(request):
    return render(
        request,
        "accounts/console/request_list.html",
        {"requests": AccountRequestService.list_all()},
    )


def _get_request_or_404(request_id):
    account_request = AccountRequestService.get(request_id)
    if account_request is None:
        raise Http404("Request not found")
    return account_request


@system_admin_required
def request_review(request, request_id):
    """Approve or reject one request. Approval activates the user and builds their
    account with the default roles cloned in."""
    account_request = _get_request_or_404(request_id)
    if request.method != "POST":
        return redirect(reverse("console:requests"))

    decision = request.POST.get("decision")
    note = (request.POST.get("note") or "")[:300]
    try:
        if decision == "approve":
            account = AccountRequestService.approve(account_request, request.user, note)
            messages.success(
                request,
                f"Approved {account_request.email}. Account '{account.name}' created "
                "— they can sign in with the password they chose.",
            )
        elif decision == "reject":
            AccountRequestService.reject(account_request, request.user, note)
            messages.success(request, f"Rejected {account_request.email}.")
        else:
            messages.error(request, "Unknown decision.")
    except AccessError as exc:
        messages.error(request, str(exc))
    return redirect(reverse("console:requests"))


# ---- Users ----


@system_admin_required
def user_list(request):
    return render(
        request,
        "accounts/console/user_list.html",
        {"users": UserAdminService.list_all()},
    )


def _get_user_or_404(user_id):
    user = UserAdminService.get(user_id)
    if user is None:
        raise Http404("User not found")
    return user


@system_admin_required
def user_detail(request, user_id):
    user = _get_user_or_404(user_id)
    form = SetPasswordForm()

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "activate":
                UserAdminService.set_active(user, True, request.user)
                messages.success(request, f"{user.email} activated.")
            elif action == "deactivate":
                UserAdminService.set_active(user, False, request.user)
                messages.success(request, f"{user.email} deactivated.")
            elif action == "grant_admin":
                UserAdminService.set_system_admin(user, True, request.user)
                messages.success(request, f"{user.email} is now a system administrator.")
            elif action == "revoke_admin":
                UserAdminService.set_system_admin(user, False, request.user)
                messages.success(request, f"{user.email} is no longer a system administrator.")
            elif action == "password":
                form = SetPasswordForm(request.POST)
                if form.is_valid():
                    UserAdminService.reset_password(user, form.cleaned_data["password"])
                    messages.success(
                        request,
                        f"Password reset for {user.email}. They will be asked to "
                        "change it after signing in.",
                    )
                else:
                    return render(
                        request,
                        "accounts/console/user_detail.html",
                        {"user_obj": user, "form": form},
                    )
            else:
                messages.error(request, "Unknown action.")
            return redirect(reverse("console:user_detail", args=[user.pk]))
        except AccessError as exc:
            messages.error(request, str(exc))
            return redirect(reverse("console:user_detail", args=[user.pk]))

    return render(
        request,
        "accounts/console/user_detail.html",
        {"user_obj": user, "form": form},
    )


# ---- Accounts ----


@system_admin_required
def account_list(request):
    return render(
        request,
        "accounts/console/account_list.html",
        {"accounts": AccountService.list_all()},
    )


@system_admin_required
def account_toggle(request, account_id):
    account = AccountService.get(account_id)
    if account is None:
        raise Http404("Account not found")
    if request.method == "POST":
        AccountService.set_active(account, not account.is_active)
        state = "activated" if account.is_active else "deactivated"
        messages.success(request, f"{account.name} {state}.")
    return redirect(reverse("console:accounts"))


@system_admin_required
def account_enter(request, account_id):
    """Switch into an account to work inside it, membership or not."""
    account = AccountService.get(account_id)
    if account is None:
        raise Http404("Account not found")
    if request.method != "POST":
        return redirect(reverse("console:accounts"))
    request.session[SESSION_ACCOUNT_KEY] = account.pk
    messages.success(request, f"Now working in {account.name}.")
    return redirect(reverse("videos:list"))


# ---- System default roles ----


@system_admin_required
def default_role_list(request):
    return render(
        request,
        "accounts/console/default_role_list.html",
        {"roles": RoleRepository.system_defaults()},
    )


@system_admin_required
def default_role_edit(request, role_id):
    """Edit a seeded default. Existing accounts keep the copy they were given —
    this only changes what future accounts start with."""
    role = RoleRepository.get_or_none(role_id)
    if role is None or role.account_id is not None:
        raise Http404("Default role not found")

    if request.method == "POST":
        form = RoleForm(request.POST, grantable=ALL_CODENAMES)
        if form.is_valid():
            data = form.cleaned_data
            try:
                RoleService.update(
                    role,
                    name=data["name"],
                    description=data["description"],
                    codenames=data["permissions"],
                    granted_by_codenames=ALL_CODENAMES,
                    actor=request.user,
                )
                messages.success(request, "Default role updated.")
                return redirect(reverse("console:default_roles"))
            except AccessError as exc:
                messages.error(request, str(exc))
    else:
        form = RoleForm(
            grantable=ALL_CODENAMES,
            initial={
                "name": role.name,
                "description": role.description,
                "permissions": list(role.codenames),
            },
        )
    return render(
        request,
        "accounts/console/default_role_form.html",
        {"form": form, "role": role},
    )
