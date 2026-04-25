"""
Local development settings.
"""
from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

CORS_ALLOW_ALL_ORIGINS = True

# Slightly relaxed DB settings for local dev
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
