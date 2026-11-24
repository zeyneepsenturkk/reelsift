"""Etkin dil modeline çok kısa gerçek bir çağrı yapıp ayarın çalıştığını gösterir.

Sonuç kullanıcıya anlaşılır Türkçe bir mesajdır; ham sağlayıcı cevabı ve anahtar dönmez."""

import asyncio
import logging
import time

from asgiref.sync import async_to_sync

from apps.agent.services import llm_config
from apps.agent.services.llm import LLMError, build_llm

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 90
MSG_NO_KEY = "{name} için API anahtarı kayıtlı değil. Anahtarı girip kaydet."
MSG_TIMEOUT = "Dil modeli zamanında cevap vermedi. Biraz sonra tekrar dene."
MSG_FAILED = "Bağlantı denenemedi. Ayarları kontrol edip tekrar dene."


async def _ping(llm) -> None:
    async for _ in llm.stream_text(
        step="settings_test",
        system="Tek kelimeyle cevap ver.",
        user="Yalnızca 'tamam' yaz.",
        effort="low",
        max_tokens=16,
    ):
        pass


def probe() -> dict:
    config = llm_config.get_effective()
    if config.provider != "ollama" and not config.key_for(config.provider):
        name = llm_config.PROVIDER_NAMES[config.provider]
        return {"ok": False, "message": MSG_NO_KEY.format(name=name)}

    started = time.monotonic()
    try:
        llm = build_llm(config)
        async_to_sync(asyncio.wait_for)(_ping(llm), PROBE_TIMEOUT_S)
    except LLMError as exc:
        return {"ok": False, "message": exc.message}
    except TimeoutError:
        return {"ok": False, "message": MSG_TIMEOUT}
    except Exception as exc:
        # Sağlayıcı hatası ham metniyle dönmesin (anahtar içerebilir); yalnız tür loglanır.
        logger.error("Dil modeli bağlantı denemesi başarısız: %s", type(exc).__name__)
        return {"ok": False, "message": MSG_FAILED}
    return {"ok": True, "seconds": round(time.monotonic() - started, 1)}
