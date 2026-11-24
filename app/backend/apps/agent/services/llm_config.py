"""Etkin dil modeli ayarı: arayüzden kaydedilen ayar varsa o, yoksa ortam (.env).

- Kaydedilen API anahtarları veritabanında Fernet ile şifreli durur; şifreleme anahtarı
  `SECRET_KEY`'den türetilir. Çözülemeyen değer (ör. `SECRET_KEY` değişmiş) "kayıtlı değil" sayılır.
- Anahtar hiçbir cevapta, logda, hata mesajında ve `repr`'de görünmez; istemciye yalnız
  "kayıtlı mı" ve son 4 karakter gider.
- Kayıtlı satır kısa süre bellekte tutulur (her model çağrısında veritabanına gidilmez); kaydetme
  anında önbellek yenilenir.
"""

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from asgiref.sync import sync_to_async
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import DatabaseError, transaction

from apps.agent.models import LLMSettings
from apps.core.exceptions import ServiceError

logger = logging.getLogger(__name__)

# Başka bir ortamdan gelen şifreli değer çözülemesin diye anahtar türetmeye bu etiket karışır.
KDF_INFO = b"reelsift.llm-settings.v1"
# Kayıtlı satırın bellekte tutulduğu süre (sn); başka süreçteki kayıt en geç bu sürede görünür.
CACHE_SECONDS = 5.0

# Geçerli bir anahtar reddedilmesin diye yalnız bariz bozukluklar elenir (önek ya da alfabe
# zorunlu değil); gerçek geçerlilik bağlantı denemesiyle anlaşılır.
KEY_MIN_LENGTH = 20
KEY_MAX_LENGTH = 300

PROVIDER_NAMES = {"anthropic": "Claude", "gemini": "Gemini", "ollama": "Yerel model (Ollama)"}


# ---------------------------------------------------------------------------------------------
# Şifreleme


def _fernet() -> Fernet:
    secret = settings.SECRET_KEY
    if not secret:
        raise ServiceError(
            "Anahtar şifrelenemedi: sunucu gizli anahtarı tanımlı değil.", "server_error", 500
        )
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=KDF_INFO).derive(
        secret.encode("utf-8")
    )
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    """Çözülemeyen ya da boş değer için boş metin; hata fırlatmaz."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ServiceError, UnicodeError):
        logger.warning("Kayıtlı dil modeli anahtarı çözülemedi; kayıtlı değil sayılıyor.")
        return ""


# ---------------------------------------------------------------------------------------------
# Etkin ayar


@dataclass(frozen=True)
class Saved:
    provider: str
    anthropic_key: str = field(repr=False)
    gemini_key: str = field(repr=False)
    ollama_base_url: str
    ollama_model: str


@dataclass(frozen=True)
class EffectiveConfig:
    provider: str
    source: str  # "env" | "saved"
    anthropic_key: str = field(repr=False)
    anthropic_model: str
    gemini_key: str = field(repr=False)
    gemini_model: str
    ollama_base_url: str
    ollama_model: str

    def key_for(self, provider: str) -> str:
        if provider == "anthropic":
            return self.anthropic_key
        if provider == "gemini":
            return self.gemini_key
        return ""


_cache: tuple[float, Saved | None] | None = None


def invalidate() -> None:
    global _cache
    _cache = None


def _load_saved() -> Saved | None:
    try:
        row = LLMSettings.objects.filter(pk=1).first()
    except DatabaseError:
        # Tablo henüz kurulmamış olabilir (ilk açılış); ortam ayarıyla devam edilir.
        logger.warning("Dil modeli ayarı okunamadı; ortam ayarı kullanılıyor.")
        return None
    if row is None:
        return None
    return Saved(
        provider=row.provider,
        anthropic_key=decrypt_secret(row.anthropic_api_key),
        gemini_key=decrypt_secret(row.gemini_api_key),
        ollama_base_url=row.ollama_base_url,
        ollama_model=row.ollama_model,
    )


def _saved(*, max_age: float | None = CACHE_SECONDS) -> Saved | None:
    """Kayıtlı ayar; `max_age=None` yaşa bakmadan önbellekteki son değeri verir (yoksa okur)."""
    global _cache
    if _cache is not None and (max_age is None or time.monotonic() - _cache[0] < max_age):
        return _cache[1]
    saved = _load_saved()
    _cache = (time.monotonic(), saved)
    return saved


def _env_key(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _compose(saved: Saved | None) -> EffectiveConfig:
    return EffectiveConfig(
        provider=saved.provider if saved else settings.LLM_PROVIDER,
        source="saved" if saved else "env",
        anthropic_key=(saved.anthropic_key if saved else "") or _env_key("ANTHROPIC_API_KEY"),
        anthropic_model=settings.ANTHROPIC_MODEL,
        gemini_key=(saved.gemini_key if saved else "") or _env_key("GEMINI_API_KEY"),
        gemini_model=settings.GEMINI_MODEL,
        ollama_base_url=(saved.ollama_base_url if saved else "") or settings.OLLAMA_BASE_URL,
        ollama_model=(saved.ollama_model if saved else "") or settings.OLLAMA_MODEL,
    )


def get_effective() -> EffectiveConfig:
    """Eşzamanlı bağlamda etkin ayar (gerekirse veritabanını okur)."""
    return _compose(_saved())


async def aget_effective() -> EffectiveConfig:
    """Eşzamansız bağlamda etkin ayar; önbellek tazeyse veritabanına gidilmez."""
    if _cache is not None and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _compose(_cache[1])
    return await sync_to_async(get_effective)()


def _in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def current_provider() -> str:
    """Etkin sağlayıcı. Olay döngüsünde veritabanına gidilmez: son bilinen kayıt (ya da ortam)."""
    if _in_event_loop():
        saved = _cache[1] if _cache is not None else None
        return saved.provider if saved else settings.LLM_PROVIDER
    return get_effective().provider


def agent_option(key: str, provider: str | None = None):
    """`AGENT` değeri; sağlayıcıya özel değer (`AGENT_PROVIDER_OVERRIDES`) varsa o, yoksa ortak."""
    overrides = getattr(settings, "AGENT_PROVIDER_OVERRIDES", {})
    provider_values = overrides.get(provider or current_provider(), {})
    if key in provider_values:
        return provider_values[key]
    return settings.AGENT[key]


def env_api_key(provider: str) -> str:
    return _env_key("GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY")


# ---------------------------------------------------------------------------------------------
# İstemciye giden görünüm


def key_hint(key: str) -> str | None:
    return f"…{key[-4:]}" if key else None


def serialize(config: EffectiveConfig) -> dict:
    return {
        "provider": config.provider,
        "source": config.source,
        "anthropic": {
            "configured": bool(config.anthropic_key),
            "key_hint": key_hint(config.anthropic_key),
            "model": config.anthropic_model,
        },
        "gemini": {
            "configured": bool(config.gemini_key),
            "key_hint": key_hint(config.gemini_key),
            "model": config.gemini_model,
        },
        "ollama": {"base_url": config.ollama_base_url, "model": config.ollama_model},
    }


# ---------------------------------------------------------------------------------------------
# Kaydetme


def _clean(value: str | None) -> str:
    return (value or "").strip().strip("\"'").strip()


def _invalid(message: str, code: str) -> ServiceError:
    return ServiceError(message, code, 400)


def _check_key(provider: str, key: str) -> None:
    printable = key.isascii() and key.isprintable() and not any(ch.isspace() for ch in key)
    if not printable or not KEY_MIN_LENGTH <= len(key) <= KEY_MAX_LENGTH:
        raise _invalid(
            f"{PROVIDER_NAMES[provider]} anahtarı kabul edilmedi; eksik kopyalanmış ya da "
            "içinde boşluk kalmış olabilir.",
            "invalid_key",
        )


def _check_base_url(url: str) -> str:
    parts = urlsplit(url)
    valid = (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and not parts.username
        and not parts.password
        and len(url) <= 200
    )
    if not valid:
        raise _invalid("Ollama adresi http:// ya da https:// ile başlamalı.", "invalid_url")
    return url.rstrip("/")


def save_settings(
    user,
    *,
    provider: str,
    anthropic_api_key: str | None = None,
    gemini_api_key: str | None = None,
    ollama_base_url: str | None = None,
    ollama_model: str | None = None,
) -> EffectiveConfig:
    """Ayarı kaydeder. Boş ya da gönderilmeyen alan "olanı koru" demektir."""
    if provider not in settings.LLM_PROVIDERS:
        raise ServiceError("Geçersiz istek.", "validation_error", 422)
    anthropic_new = _clean(anthropic_api_key)
    gemini_new = _clean(gemini_api_key)
    url_new = _clean(ollama_base_url)
    model_new = _clean(ollama_model)
    if anthropic_new:
        _check_key("anthropic", anthropic_new)
    if gemini_new:
        _check_key("gemini", gemini_new)
    if url_new:
        url_new = _check_base_url(url_new)

    with transaction.atomic():
        row, _ = LLMSettings.objects.select_for_update().get_or_create(
            pk=1, defaults={"provider": provider}
        )
        if anthropic_new:
            row.anthropic_api_key = encrypt_secret(anthropic_new)
        if gemini_new:
            row.gemini_api_key = encrypt_secret(gemini_new)
        if url_new:
            row.ollama_base_url = url_new
        if model_new:
            row.ollama_model = model_new
        row.provider = provider
        row.updated_by = user

        keys = {
            "anthropic": decrypt_secret(row.anthropic_api_key) or env_api_key("anthropic"),
            "gemini": decrypt_secret(row.gemini_api_key) or env_api_key("gemini"),
        }
        if provider in keys and not keys[provider]:
            raise _invalid(
                f"{PROVIDER_NAMES[provider]} için API anahtarı gerekli; önce anahtarı gir.",
                "missing_key",
            )
        row.save()

    invalidate()
    return get_effective()
