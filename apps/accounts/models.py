"""Users, accounts, roles and memberships.

An **Account** is a workspace. It owns templates, and therefore transitively owns
videos, chapters, images, steps and API logs. A **Membership** grants one user one
**Role** in one account, and a role is a bag of permission codenames drawn from
``apps.accounts.permissions``. A user with memberships in several accounts switches
between them; the active account scopes every query.
"""
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from . import permissions as perms


class UserManager(BaseUserManager):
    """Email is the login field, so the stock username-based manager won't do."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        extra.setdefault("is_system_admin", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        # A Django superuser is also an app-level system admin.
        extra.setdefault("is_system_admin", True)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("A superuser must have is_staff and is_superuser set.")
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Custom user: email login, no username.

    ``is_system_admin`` is the app-level system administrator — the person who
    approves account requests and runs ``/console/``. It is deliberately separate
    from ``is_staff``/``is_superuser``, which only govern Django's ``/admin/``.
    """

    username = None
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200, blank=True)
    is_system_admin = models.BooleanField(
        default=False,
        help_text="Approves account requests and administers every account.",
    )
    must_change_password = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.full_name or self.email

    @property
    def display_name(self):
        return self.full_name or self.email.split("@")[0]


class Account(models.Model):
    """A workspace. Owns templates, and through them every video and asset."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    owner = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="owned_accounts",
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @staticmethod
    def unique_slug(name):
        """A slug derived from ``name``, suffixed until it is free."""
        base = slugify(name)[:200] or "account"
        slug = base
        counter = 2
        while Account.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug


class Role(models.Model):
    """A named bundle of permission codenames.

    ``account=None`` marks a seeded system default that is cloned into each new
    account. Account-scoped roles are freely editable by whoever holds
    ``account.manage_roles`` there.
    """

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="roles",
        null=True,
        blank=True,
        help_text="Null means a system default role, cloned into new accounts.",
    )
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    permissions = models.JSONField(
        default=list,
        blank=True,
        help_text="Permission codenames from apps.accounts.permissions.",
    )
    is_system_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("account", "name")]

    def __str__(self):
        return self.name

    @property
    def codenames(self):
        """Granted codenames, filtered to the current catalog.

        Permissions are stored as JSON, so a codename can outlive its removal
        from the catalog. Filtering here means a stale entry grants nothing.
        """
        return frozenset(perms.clean(self.permissions))

    @property
    def permission_labels(self):
        return [perms.LABELS[codename] for codename in perms.clean(self.permissions)]

    def has(self, codename):
        return codename in self.codenames


class Membership(models.Model):
    """One user's role in one account."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="memberships"
    )
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.ForeignKey(
        Role, on_delete=models.PROTECT, related_name="memberships"
    )
    is_active = models.BooleanField(default=True)
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invited_memberships",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["account__name", "user__email"]
        unique_together = [("user", "account")]

    def __str__(self):
        return f"{self.user} @ {self.account} ({self.role})"

    @property
    def is_owner(self):
        return self.account.owner_id == self.user_id


class RequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class AccountRequest(models.Model):
    """A visitor asking for an account from the public home page.

    No email backend is configured, so the request form collects the password and
    creates an inactive ``User`` immediately. Approval only activates that user and
    builds their account — there is no password to hand over out of band.
    """

    email = models.EmailField()
    full_name = models.CharField(max_length=200, blank=True)
    account_name = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="account_requests",
        help_text="The inactive user created when the request was submitted.",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} ({self.get_status_display()})"

    @property
    def is_pending(self):
        return self.status == RequestStatus.PENDING

    def mark_reviewed(self, reviewer, status, note=""):
        self.status = status
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.decision_note = note
