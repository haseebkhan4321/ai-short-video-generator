from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm

from .models import Account, AccountRequest, Membership, Role, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Django's UserAdmin, adjusted for an email login with no username field."""

    change_password_form = AdminPasswordChangeForm
    ordering = ("email",)
    list_display = (
        "email", "full_name", "is_active", "is_system_admin", "is_staff", "date_joined"
    )
    list_filter = ("is_active", "is_system_admin", "is_staff", "is_superuser")
    search_fields = ("email", "full_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal", {"fields": ("full_name", "first_name", "last_name")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_system_admin",
                    "must_change_password",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "password1", "password2",
                           "is_active", "is_system_admin"),
            },
        ),
    )


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    raw_id_fields = ("user", "role", "invited_by")


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "owner__email")
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("owner",)
    inlines = [MembershipInline]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "account", "is_system_default", "permission_count")
    list_filter = ("is_system_default", "account")
    search_fields = ("name",)
    raw_id_fields = ("account",)

    @admin.display(description="Permissions")
    def permission_count(self, obj):
        return len(obj.codenames)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "account", "role", "is_active", "created_at")
    list_filter = ("is_active", "account", "role")
    search_fields = ("user__email", "account__name")
    raw_id_fields = ("user", "account", "role", "invited_by")


@admin.register(AccountRequest)
class AccountRequestAdmin(admin.ModelAdmin):
    list_display = ("email", "account_name", "status", "created_at", "reviewed_by")
    list_filter = ("status",)
    search_fields = ("email", "account_name")
    raw_id_fields = ("user", "account", "reviewed_by")
    # Reviewing belongs in /console/, where approval also creates the account and
    # its roles. Flipping status here would activate nothing.
    readonly_fields = ("status", "user", "account", "reviewed_by", "reviewed_at",
                       "created_at")
