from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    # Public
    path("", views.home, name="home"),
    path("accounts/login/", views.AccountLoginView.as_view(), name="login"),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
    path("accounts/request/", views.account_request, name="request"),
    path("accounts/request/received/", views.request_received, name="request_received"),
    path("accounts/none/", views.no_account, name="no_account"),
    # Development only: 404s unless DEV_LOGIN_ENABLED (which is itself `and DEBUG`).
    path("accounts/dev-login/<int:user_id>/", views.dev_login, name="dev_login"),

    # The signed-in user
    path("accounts/me/", views.my_profile, name="my_profile"),
    path("accounts/switch/<int:account_id>/", views.switch_account, name="switch"),

    # Account administration: users
    path("accounts/users/", views.user_list, name="user_list"),
    path("accounts/users/new/", views.user_create, name="user_create"),
    path("accounts/users/<int:membership_id>/edit/", views.user_edit, name="user_edit"),
    path(
        "accounts/users/<int:membership_id>/remove/",
        views.user_remove,
        name="user_remove",
    ),

    # Account administration: roles
    path("accounts/roles/", views.role_list, name="role_list"),
    path("accounts/roles/new/", views.role_create, name="role_create"),
    path("accounts/roles/<int:role_id>/edit/", views.role_edit, name="role_edit"),
    path("accounts/roles/<int:role_id>/delete/", views.role_delete, name="role_delete"),

    # Account settings
    path("accounts/settings/", views.account_settings, name="settings"),
]
