"""Forms for authentication, account requests, users and roles.

These validate only. Persistence goes through the services, which is where the
RBAC invariants live, so nothing here calls ``.save()`` on a model.
"""
from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from . import permissions as perms
from .models import User


class EmailAuthenticationForm(AuthenticationForm):
    """Django's login form, relabelled for an email username field."""

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "No active account with that email and password. "
        "New requests need a system administrator's approval before you can sign in.",
    }


class PasswordFieldsMixin:
    """Two password fields that must match and pass Django's validators."""

    def _clean_password_pair(self, field1="password1", field2="password2"):
        password1 = self.cleaned_data.get(field1)
        password2 = self.cleaned_data.get(field2)
        if password1 and password2 and password1 != password2:
            self.add_error(field2, "The two passwords do not match.")
            return None
        if password1:
            try:
                password_validation.validate_password(password1)
            except forms.ValidationError as exc:
                self.add_error(field1, exc)
                return None
        return password1


class AccountRequestForm(PasswordFieldsMixin, forms.Form):
    """The public request form on the home page."""

    full_name = forms.CharField(max_length=200, label="Your name")
    email = forms.EmailField(label="Email")
    account_name = forms.CharField(
        max_length=200,
        label="Account name",
        help_text="The workspace your templates and videos will live in, "
        "e.g. your channel or studio name.",
    )
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Anything the administrator should know (optional)",
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account already exists for this email address."
            )
        return email

    def clean(self):
        cleaned = super().clean()
        cleaned["password"] = self._clean_password_pair()
        return cleaned


class UserProfileForm(forms.Form):
    """The signed-in user editing their own name.

    Named ``UserProfileForm`` rather than ``ProfileForm`` because "Profile" used to
    be this project's name for what is now ``Template``.
    """

    full_name = forms.CharField(max_length=200, required=False, label="Your name")


class ChangePasswordForm(PasswordFieldsMixin, forms.Form):
    current_password = forms.CharField(label="Current password", widget=forms.PasswordInput)
    password1 = forms.CharField(label="New password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm new password", widget=forms.PasswordInput)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        current = self.cleaned_data["current_password"]
        if not self.user.check_password(current):
            raise forms.ValidationError("That is not your current password.")
        return current

    def clean(self):
        cleaned = super().clean()
        cleaned["password"] = self._clean_password_pair()
        return cleaned


class SetPasswordForm(PasswordFieldsMixin, forms.Form):
    """An administrator setting someone else's password (no current password)."""

    password1 = forms.CharField(label="New password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm new password", widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()
        cleaned["password"] = self._clean_password_pair()
        return cleaned


class PermissionCheckboxField(forms.MultipleChoiceField):
    """The catalog rendered as checkboxes, grouped for display by the template."""

    widget = forms.CheckboxSelectMultiple

    def __init__(self, **kwargs):
        kwargs.setdefault("choices", perms.choices())
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)


class RoleForm(forms.Form):
    name = forms.CharField(max_length=100, label="Role name")
    description = forms.CharField(max_length=300, required=False)
    permissions = PermissionCheckboxField(label="Permissions")

    def __init__(self, *args, grantable=None, **kwargs):
        """``grantable`` limits the choices to what the editor holds themselves, so
        the UI cannot offer a permission the service would then reject."""
        super().__init__(*args, **kwargs)
        if grantable is not None:
            allowed = set(grantable)
            self.fields["permissions"].choices = [
                (codename, label)
                for codename, label in perms.choices()
                if codename in allowed
            ]

    def permission_groups(self):
        """Groups of ``(codename, label, help, checked)`` for the template."""
        selected = set(self["permissions"].value() or [])
        offered = {codename for codename, _ in self.fields["permissions"].choices}
        groups = []
        for group in perms.PERMISSION_GROUPS:
            rows = [
                {**item, "checked": item["codename"] in selected}
                for item in group["permissions"]
                if item["codename"] in offered
            ]
            if rows:
                groups.append({"name": group["name"], "permissions": rows})
        return groups


class MembershipCreateForm(PasswordFieldsMixin, forms.Form):
    """Add a user to the active account. Active immediately, no approval step."""

    email = forms.EmailField()
    full_name = forms.CharField(max_length=200, required=False)
    role = forms.ModelChoiceField(queryset=None)
    password1 = forms.CharField(
        label="Password", widget=forms.PasswordInput, required=False,
        help_text="Only needed for a brand-new user. Leave blank to add an "
                  "existing user to this account.",
    )
    password2 = forms.CharField(
        label="Confirm password", widget=forms.PasswordInput, required=False
    )

    def __init__(self, *args, roles=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = roles

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email")
        is_new_user = email and not User.objects.filter(email__iexact=email).exists()
        if is_new_user:
            if not cleaned.get("password1"):
                self.add_error("password1", "A password is required for a new user.")
            else:
                cleaned["password"] = self._clean_password_pair()
        else:
            cleaned["password"] = None
        return cleaned


class MembershipEditForm(forms.Form):
    role = forms.ModelChoiceField(queryset=None)
    is_active = forms.BooleanField(required=False, initial=True, label="Active")

    def __init__(self, *args, roles=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = roles


class AccountSettingsForm(forms.Form):
    name = forms.CharField(max_length=200, label="Account name")
