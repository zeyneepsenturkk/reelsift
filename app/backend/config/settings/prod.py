import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403  # ayar modülü deseni: base'in tamamı devralınır

REQUIRED_ENV = ("DJANGO_SECRET_KEY", "DJANGO_ALLOWED_HOSTS", "DJANGO_DB_PASSWORD")

missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
if missing:
    raise ImproperlyConfigured(f"Eksik ortam değişkenleri: {', '.join(missing)}")

DEBUG = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
