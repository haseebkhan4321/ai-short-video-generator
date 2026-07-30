"""Public pages, the signed-in user's own profile, and account administration."""
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from .access import SESSION_ACCOUNT_KEY, Perm, context_for, requires_perm
from .forms import (
    AccountRequestForm,
    AccountSettingsForm,
    ChangePasswordForm,
    EmailAuthenticationForm,
    MembershipCreateForm,
    MembershipEditForm,
    RoleForm,
    UserProfileForm,
)
from .repositories import UserRepository
from .services import (
    AccessError,
    AccountRequestService,
    AccountService,
    MembershipService,
    RoleService,
)


# ---- Public ----


class AccountLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True


def home(request):
    """Public landing page. Signed-in users go straight to their videos."""
    if request.user.is_authenticated:
        return redirect(reverse("videos:list"))
    return render(request, "accounts/home.html")


def account_request(request):
    """Self-service request. Creates an inactive user awaiting approval."""
    if request.user.is_authenticated:
        return redirect(reverse("videos:list"))

    if request.method == "POST":
        form = AccountRequestForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                AccountRequestService.submit(
                    email=data["email"],
                    full_name=data["full_name"],
                    account_name=data["account_name"],
                    password=data["password"],
                    message=data["message"],
                )
                return redirect(reverse("accounts:request_received"))
            except AccessError as exc:
                messages.error(request, str(exc))
    else:
        form = AccountRequestForm()
    return render(request, "accounts/request.html", {"form": form})


def request_received(request):
    return render(request, "accounts/request_received.html")


@login_required
def no_account(request):
    """Signed in but with no active membership anywhere — a dead end by design."""
    if context_for(request).account is not None:
        return redirect(reverse("videos:list"))
    return render(request, "accounts/no_account.html")


# ---- The signed-in user's own profile and account switching ----


@login_required
def my_profile(request):
    """Own name, password, and the accounts this user can switch between."""
    profile_form = UserProfileForm(initial={"full_name": request.user.full_name})
    password_form = ChangePasswordForm(user=request.user)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "profile":
            profile_form = UserProfileForm(request.POST)
            if profile_form.is_valid():
                UserRepository.update(
                    request.user, full_name=profile_form.cleaned_data["full_name"]
                )
                messages.success(request, "Profile updated.")
                return redirect(reverse("accounts:my_profile"))
        elif action == "password":
            password_form = ChangePasswordForm(request.POST, user=request.user)
            if password_form.is_valid():
                UserRepository.set_password(
                    request.user, password_form.cleaned_data["password"]
                )
                UserRepository.update(request.user, must_change_password=False)
                # Keep the current session signed in after the hash changes.
                update_session_auth_hash(request, request.user)
                messages.success(request, "Password changed.")
                return redirect(reverse("accounts:my_profile"))

    return render(
        request,
        "accounts/my_profile.html",
        {"profile_form": profile_form, "password_form": password_form},
    )


@login_required
def switch_account(request, account_id):
    """Set the active account for this session. POST only — it changes state."""
    if request.method != "POST":
        return redirect(reverse("accounts:my_profile"))
    if not AccountService.can_switch_to(request.user, account_id):
        raise Http404("Account not found")
    request.session[SESSION_ACCOUNT_KEY] = int(account_id)
    account = AccountService.get(account_id)
    messages.success(request, f"Switched to {account.name}.")
    return redirect(request.POST.get("next") or reverse("videos:list"))


# ---- Account administration: users ----


@requires_perm(Perm.ACCOUNT_MANAGE_USERS)
def user_list(request):
    return render(
        request,
        "accounts/user_list.html",
        {"memberships": MembershipService.list_for_account(request.account)},
    )


@requires_perm(Perm.ACCOUNT_MANAGE_USERS)
def user_create(request):
    roles = RoleService.list_for_account(request.account)
    grantable = context_for(request).codenames

    if request.method == "POST":
        form = MembershipCreateForm(request.POST, roles=roles)
        if form.is_valid():
            data = form.cleaned_data
            try:
                membership = MembershipService.add_user(
                    account=request.account,
                    email=data["email"],
                    full_name=data["full_name"],
                    password=data["password"],
                    role=data["role"],
                    invited_by=request.user,
                    granted_by_codenames=grantable,
                )
                messages.success(
                    request, f"{membership.user.email} added as {membership.role.name}."
                )
                return redirect(reverse("accounts:user_list"))
            except AccessError as exc:
                messages.error(request, str(exc))
    else:
        form = MembershipCreateForm(roles=roles)
    return render(
        request, "accounts/user_form.html", {"form": form, "title": "Add a user"}
    )


def _get_membership_or_404(request, membership_id):
    membership = MembershipService.get(membership_id, request.account)
    if membership is None:
        raise Http404("User not found in this account")
    return membership


@requires_perm(Perm.ACCOUNT_MANAGE_USERS)
def user_edit(request, membership_id):
    membership = _get_membership_or_404(request, membership_id)
    roles = RoleService.list_for_account(request.account)
    grantable = context_for(request).codenames

    if request.method == "POST":
        form = MembershipEditForm(request.POST, roles=roles)
        if form.is_valid():
            data = form.cleaned_data
            try:
                if data["role"].pk != membership.role_id:
                    MembershipService.change_role(
                        membership, data["role"], request.user, grantable
                    )
                if data["is_active"] != membership.is_active:
                    MembershipService.set_active(
                        membership, data["is_active"], request.user
                    )
                messages.success(request, "Membership updated.")
                return redirect(reverse("accounts:user_list"))
            except AccessError as exc:
                messages.error(request, str(exc))
    else:
        form = MembershipEditForm(
            roles=roles,
            initial={"role": membership.role_id, "is_active": membership.is_active},
        )
    return render(
        request,
        "accounts/user_form.html",
        {
            "form": form,
            "membership": membership,
            "title": f"Edit {membership.user.display_name}",
        },
    )


@requires_perm(Perm.ACCOUNT_MANAGE_USERS)
def user_remove(request, membership_id):
    """Removes the membership, never the user — they may belong to other accounts."""
    membership = _get_membership_or_404(request, membership_id)
    if request.method == "POST":
        try:
            email = membership.user.email
            MembershipService.remove(membership, request.user)
            messages.success(request, f"{email} removed from this account.")
            return redirect(reverse("accounts:user_list"))
        except AccessError as exc:
            messages.error(request, str(exc))
            return redirect(reverse("accounts:user_list"))
    return render(
        request, "accounts/user_confirm_remove.html", {"membership": membership}
    )


# ---- Account administration: roles ----


@requires_perm(Perm.ACCOUNT_MANAGE_ROLES)
def role_list(request):
    return render(
        request,
        "accounts/role_list.html",
        {"roles": RoleService.list_for_account(request.account)},
    )


@requires_perm(Perm.ACCOUNT_MANAGE_ROLES)
def role_create(request):
    grantable = context_for(request).codenames
    if request.method == "POST":
        form = RoleForm(request.POST, grantable=grantable)
        if form.is_valid():
            data = form.cleaned_data
            try:
                role = RoleService.create(
                    account=request.account,
                    name=data["name"],
                    description=data["description"],
                    codenames=data["permissions"],
                    granted_by_codenames=grantable,
                )
                messages.success(request, f"Role '{role.name}' created.")
                return redirect(reverse("accounts:role_list"))
            except AccessError as exc:
                messages.error(request, str(exc))
    else:
        form = RoleForm(grantable=grantable)
    return render(
        request, "accounts/role_form.html", {"form": form, "title": "New role"}
    )


def _get_role_or_404(request, role_id):
    role = RoleService.get(role_id, request.account)
    if role is None:
        raise Http404("Role not found")
    return role


@requires_perm(Perm.ACCOUNT_MANAGE_ROLES)
def role_edit(request, role_id):
    role = _get_role_or_404(request, role_id)
    grantable = context_for(request).codenames

    if request.method == "POST":
        form = RoleForm(request.POST, grantable=grantable)
        if form.is_valid():
            data = form.cleaned_data
            try:
                RoleService.update(
                    role,
                    name=data["name"],
                    description=data["description"],
                    codenames=data["permissions"],
                    granted_by_codenames=grantable,
                    actor=request.user,
                )
                messages.success(request, "Role updated.")
                return redirect(reverse("accounts:role_list"))
            except AccessError as exc:
                messages.error(request, str(exc))
    else:
        form = RoleForm(
            grantable=grantable,
            initial={
                "name": role.name,
                "description": role.description,
                "permissions": list(role.codenames),
            },
        )
    return render(
        request,
        "accounts/role_form.html",
        {"form": form, "role": role, "title": f"Edit {role.name}"},
    )


@requires_perm(Perm.ACCOUNT_MANAGE_ROLES)
def role_delete(request, role_id):
    role = _get_role_or_404(request, role_id)
    if request.method == "POST":
        try:
            name = role.name
            RoleService.delete(role)
            messages.success(request, f"Role '{name}' deleted.")
        except AccessError as exc:
            messages.error(request, str(exc))
        return redirect(reverse("accounts:role_list"))
    return render(request, "accounts/role_confirm_delete.html", {"role": role})


# ---- Account settings ----


@requires_perm(Perm.ACCOUNT_MANAGE_SETTINGS)
def account_settings(request):
    if request.method == "POST":
        form = AccountSettingsForm(request.POST)
        if form.is_valid():
            AccountService.rename(request.account, form.cleaned_data["name"])
            messages.success(request, "Account updated.")
            return redirect(reverse("accounts:settings"))
    else:
        form = AccountSettingsForm(initial={"name": request.account.name})
    return render(request, "accounts/settings.html", {"form": form})
