"""
Make Celery app available so Django's `app.autodiscover_tasks()` works
when other modules do `from config.celery import app`.
"""
from .celery import app as celery_app

__all__ = ("celery_app",)
