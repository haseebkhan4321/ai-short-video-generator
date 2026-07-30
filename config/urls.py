"""Root URL configuration."""
import re

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from .media_serve import ranged_serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(pattern_name="videos:list", permanent=False)),
    path("profiles/", include("apps.profiles.urls")),
    path("videos/", include("apps.videos.urls")),
]

if settings.DEBUG:
    # Media goes through ranged_serve so audio/video seeking works (Range headers).
    urlpatterns += [
        re_path(
            r"^%s(?P<path>.*)$" % re.escape(settings.MEDIA_URL.lstrip("/")),
            ranged_serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
