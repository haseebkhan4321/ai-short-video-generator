"""Imports the Celery app on startup.

`@shared_task` binds to whichever Celery app exists when the module is imported, so
the app has to be created before any app's tasks.py is loaded. Importing it here is
the documented way to guarantee that under both manage.py and the worker.
"""
from .celery import app as celery_app

__all__ = ("celery_app",)
