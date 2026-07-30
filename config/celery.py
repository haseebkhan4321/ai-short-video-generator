"""The Celery application.

Long steps used to run in daemon threads inside the web process, which meant a
40-minute render died with the server, had no retries and was invisible outside the
page that started it. They are tasks now.

Configuration lives in Django settings under the ``CELERY_`` namespace, so there is
one place to look and ``.env`` can drive it.
"""
import os

from celery import Celery

# Set before the app is created: the worker is started as `celery -A config`, not
# through manage.py, so nothing else has configured Django yet.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("story_studio")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Finds tasks.py in every installed app.
app.autodiscover_tasks()


@app.task(name="config.ping")
def ping():
    """Round-trip check that a worker is alive and consuming. Used by `manage.py
    queue_status`, which is the quickest way to tell a stopped worker from a
    stopped broker."""
    return "pong"
