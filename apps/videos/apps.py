from django.apps import AppConfig


class VideosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.videos"
    label = "videos"

    def ready(self):
        # Importing the service modules registers their pipeline executors.
        from .services import script_service  # noqa: F401
        from .services import split_service  # noqa: F401
        from .services import image_service  # noqa: F401
        from .services import narration_service  # noqa: F401
        from .services import render_service  # noqa: F401
