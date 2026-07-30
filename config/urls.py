"""Root URL configuration."""
import re

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from .media_serve import guarded_serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("console/", include("apps.accounts.console_urls")),
    path("templates/", include("apps.templates.urls")),
    path("videos/", include("apps.videos.urls")),
    # Media is registered unconditionally, not under DEBUG. It is no longer a static
    # file server: guarded_serve enforces the login and the account check, so
    # handing media to a web server that skips it would expose every account's
    # scripts, images and renders by path.
    # document_root is deliberately not pinned here: guarded_serve reads
    # settings.MEDIA_ROOT per request, so there is one source of truth.
    re_path(
        r"^%s(?P<path>.*)$" % re.escape(settings.MEDIA_URL.lstrip("/")),
        guarded_serve,
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
