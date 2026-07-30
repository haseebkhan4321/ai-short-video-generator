from django.urls import path

from . import console_views as views

app_name = "console"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    path("requests/", views.request_list, name="requests"),
    path("requests/<int:request_id>/review/", views.request_review, name="request_review"),

    path("users/", views.user_list, name="users"),
    path("users/<int:user_id>/", views.user_detail, name="user_detail"),

    path("accounts/", views.account_list, name="accounts"),
    path("accounts/<int:account_id>/toggle/", views.account_toggle, name="account_toggle"),
    path("accounts/<int:account_id>/enter/", views.account_enter, name="account_enter"),

    path("default-roles/", views.default_role_list, name="default_roles"),
    path(
        "default-roles/<int:role_id>/edit/",
        views.default_role_edit,
        name="default_role_edit",
    ),
]
