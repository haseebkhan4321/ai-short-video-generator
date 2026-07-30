from django.apps import AppConfig


class SeedersConfig(AppConfig):
    """Holds the seeders and their management commands. No models of its own."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "seeders"
    label = "seeders"
