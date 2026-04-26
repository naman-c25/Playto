"""
Production settings — security-hardened.
"""
from decouple import config as env
from .base import *  # noqa: F401, F403

DEBUG = False

_allowed = env("ALLOWED_HOSTS", default="")
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(",") if h.strip()] or ["*"]
# Railway sends internal healthcheck requests with Host: healthcheck.railway.app
# and routes traffic from *.up.railway.app domains. Always permit both.
for _host in ("healthcheck.railway.app", ".railway.app", ".up.railway.app"):
    if _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)

# Railway terminates SSL at the edge and forwards plain HTTP internally.
# SECURE_PROXY_SSL_HEADER lets Django know the original request was HTTPS.
# SECURE_SSL_REDIRECT must be False — Railway's healthcheck hits the container
# directly over HTTP and would get a redirect loop otherwise.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", default=False, cast=bool)
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

# Custom headers the frontend sends — must be allowed at the preflight stage,
# otherwise the browser blocks the request before it reaches Django.
from corsheaders.defaults import default_headers
CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-merchant-id",
    "idempotency-key",
]

DATABASES["default"]["CONN_MAX_AGE"] = 60  # noqa: F405
