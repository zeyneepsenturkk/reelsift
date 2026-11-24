import os
from urllib.parse import urlparse

from django.conf import settings

# Anahtar ayar nesnesine girmez: her çağrıda ortamdan okunur ve yalnız istek başlığına konur.
API_KEY_ENV = "VITRIN_API_KEY"


def site_base_url() -> str:
    """Site adresi, sondaki `/` kırpılmış; `http(s)://` ile başlamıyorsa boş (yayın kapalı)."""
    url = (settings.VITRIN_URL or "").strip().rstrip("/")
    valid = url.startswith(("http://", "https://")) and bool(urlparse(url).hostname)
    return url if valid else ""


def site_api_key() -> str:
    return (os.environ.get(API_KEY_ENV) or "").strip()


def publish_enabled() -> bool:
    return bool(site_base_url() and site_api_key())
