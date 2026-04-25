"""
Production settings — security-hardened.
"""
from decouple import config as env
from .base import *  # noqa: F401, F403

DEBUG = False

ALLOWED_HOSTS = env("ALLOWED_HOSTS", default="").split(",")

# HTTPS enforcement
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", default=True, cast=bool)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# CORS — only allow the deployed frontend origin
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS", default="").split(",")

DATABASES["default"]["CONN_MAX_AGE"] = 60  # noqa: F405
