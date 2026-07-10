from django.urls import path

from . import views

app_name = "profiles"

urlpatterns = [
    path("", views.profile_list, name="list"),
    path("new/", views.profile_create, name="create"),
    path("<int:profile_id>/", views.profile_detail, name="detail"),
    path("<int:profile_id>/edit/", views.profile_edit, name="edit"),
    path("<int:profile_id>/delete/", views.profile_delete, name="delete"),
]
