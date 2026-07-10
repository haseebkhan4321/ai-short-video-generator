from django.urls import path

from . import views

app_name = "videos"

urlpatterns = [
    path("", views.video_list, name="list"),
    path("new/", views.video_create, name="create"),
    path("<int:video_id>/", views.video_detail, name="detail"),
    path("<int:video_id>/delete/", views.video_delete, name="delete"),
    path("<int:video_id>/batch-approve/", views.step_batch_approve, name="batch_approve"),
    path("<int:video_id>/steps/<int:step_id>/approve/", views.step_approve, name="step_approve"),
    path("<int:video_id>/steps/<int:step_id>/reject/", views.step_reject, name="step_reject"),
    path("<int:video_id>/steps/<int:step_id>/regenerate/", views.step_regenerate, name="step_regenerate"),
]
