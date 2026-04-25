"""
Celery application instance.

Import this from anywhere using: from config.celery import app
Django's auto-discover finds tasks in all INSTALLED_APPS.
"""
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("playto_payout")

# Pull Celery config from Django settings, namespaced under CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py in every installed Django app
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
