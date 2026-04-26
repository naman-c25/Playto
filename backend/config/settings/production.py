"""
Production settings — security-hardened.
"""
from decouple import config as env
from .base import *  # noqa: F401, F403

DEBUG = False

ALLOWED_HOSTS = env("ALLOWED_HOSTS", default="").split(",")

# HTTPS enforcement
# Railway (and most PaaS) terminate SSL at their proxy and forward HTTP internally.
# This header tells Django the original request was HTTPS, so redirects work correctly.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", default=True, cast=bool)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# CORS — only allow the deployed frontend origin.
# If CORS_ALLOWED_ORIGINS is not set, fall back to allow all (safe for a demo;
# tighten by setting the env var to the actual frontend URL in production).
_cors = env("CORS_ALLOWED_ORIGINS", default="")
if _cors.strip():
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors.split(",") if o.strip()]
else:
    CORS_ALLOW_ALL_ORIGINS = True

DATABASES["default"]["CONN_MAX_AGE"] = 60  # noqa: F405
