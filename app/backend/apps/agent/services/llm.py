"""Dil modeli sınırı: resmi Anthropic SDK'sı, değiştirilebilir model, sade hata mesajları.

Kurallar (model Haiku 5.5 <-> Sonnet 5.5 arasında değişebilmeli):
- `temperature`/`top_p`/`top_k` ve `thinking` gönderilmez; derinlik `output_config.effort` ile.
- Yapılı çıktı `messages.parse` ile; elle JSON ayıklama ve prefill yok.
- Cevap blok türüne göre okunur; `max_tokens` ve `refusal` hata sayılır.
- Anahtar yalnız ortamdan okunur; metinler loglanmaz, yalnız kullanım ve süre.
"""

import asyncio
import contextvars
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TypeVar

import anthropic
from django.conf import settings
from pydantic import BaseModel

from apps.core.exceptions import ServiceError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Kullanıcıya giden sade mesajlar; ham API metni istemciye gitmez.
MSG_UNAVAILABLE = "Dil modeline şu an ulaşılamıyor. Biraz sonra tekrar dene."
MSG_BUSY = "Dil modeli şu an yoğun. Biraz sonra tekrar dene."
MSG_CONFIG = "Dil modeli yapılandırılmamış. Yöneticiye haber ver."
MSG_BAD_OUTPUT = "Model cevabı beklenen biçimde gelmedi. İsteği tekrar gönder."
MSG_TRUNCATED = "Model cevabı yarıda kesildi. İsteği biraz sadeleştirip tekrar dene."
MSG_REFUSED = "Model bu isteğe cevap vermedi. İsteği farklı bir şekilde yazmayı dene."
MSG_QUOTA_MINUTE = "Gemini'nin ücretsiz kotası şu an dolu. Bir iki dakika sonra tekrar dene."
MSG_QUOTA_DAY = (
    "Gemini'nin günlük ücretsiz kotası doldu. Kota yarın yenilenir; "
    "o zamana kadar bekle ya da başka bir anahtar kullan."
)
MSG_QUOTA = (
    "Gemini'nin ücretsiz kotası dolu. Birkaç dakika sonra tekrar dene; "
    "bugün çok istek attıysan kota yarın yenilenir."
)


class LLMError(ServiceError):
    def __init__(self, message: str = MSG_UNAVAILABLE):
        super().__init__(message, "model_error", 502)


class LLMRefused(LLMError):
    """Model isteği reddetti / engelledi (yalnız ret; kota, ulaşılamama, bozuk çıktı değil).

    `reason`: engel ya da bitiş nedeninin adı (metin değil). Mesaj ve kod `LLMError` ile aynıdır;
    graf `skip_refused` açıkken bunu ayırt eder."""

    def __init__(self, message: str = MSG_REFUSED, reason: str | None = None):
        super().__init__(message)
        self.reason = reason


@dataclass
class UsageTally:
    """Bir turdaki toplam model kullanımı (run_scenarios maliyet raporu için)."""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    by_step: dict[str, float] = field(default_factory=dict)

    def add(self, step: str, input_tokens: int, output_tokens: int, seconds: float) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.calls += 1
        self.by_step[step] = self.by_step.get(step, 0.0) + seconds


usage_tally: contextvars.ContextVar[UsageTally | None] = contextvars.ContextVar(
    "agent_usage_tally", default=None
)


def _translate(exc: Exception) -> LLMError:
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return LLMError(MSG_CONFIG)
    if isinstance(exc, anthropic.RateLimitError | anthropic.OverloadedError):
        return LLMError(MSG_BUSY)
    return LLMError(MSG_UNAVAILABLE)


class AnthropicLLM:
    def __init__(
        self,
        *,
        client: anthropic.AsyncAnthropic | None = None,
        model: str | None = None,
    ):
        self._client = client
        self.model = model or settings.ANTHROPIC_MODEL
        limit = settings.AGENT["max_concurrent_calls"]
        self._semaphore = asyncio.Semaphore(limit)

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        # Anahtar eksikse uygulama açılışı değil, ilk çağrı hata verir.
        if self._client is None:
            try:
                self._client = anthropic.AsyncAnthropic(
                    timeout=settings.AGENT["request_timeout_s"],
                    max_retries=settings.AGENT["llm_max_retries"],
                )
            except anthropic.AnthropicError as exc:
                logger.error("Anthropic istemcisi kurulamadı: %s", type(exc).__name__)
                raise LLMError(MSG_CONFIG) from exc
        return self._client

    def _log(self, step: str, message, started: float) -> None:
        seconds = time.monotonic() - started
        usage = message.usage
        logger.info(
            "llm step=%s model=%s in=%s out=%s stop=%s seconds=%.1f",
            step,
            self.model,
            usage.input_tokens,
            usage.output_tokens,
            message.stop_reason,
            seconds,
        )
        tally = usage_tally.get()
        if tally is not None:
            tally.add(step, usage.input_tokens, usage.output_tokens, seconds)

    @staticmethod
    def _check_stop(step: str, message) -> None:
        if message.stop_reason == "max_tokens":
            logger.warning("llm step=%s max_tokens sınırına takıldı", step)
            raise LLMError(MSG_TRUNCATED)
        if message.stop_reason == "refusal":
            logger.warning("llm step=%s model reddetti", step)
            raise LLMRefused(reason=message.stop_reason)

    async def structured(
        self,
        *,
        step: str,
        system: str,
        user: str,
        output: type[T],
        effort: str,
        max_tokens: int,
    ) -> T:
        started = time.monotonic()
        async with self._semaphore:
            try:
                message = await self.client.messages.parse(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    output_format=output,
                    output_config={"effort": effort},
                )
            except anthropic.APIError as exc:
                logger.error(
                    "llm step=%s hata=%s status=%s",
                    step,
                    type(exc).__name__,
                    getattr(exc, "status_code", None),
                )
                raise _translate(exc) from exc
            except ValueError as exc:
                # Kesilmiş ya da şemaya uymayan JSON (pydantic doğrulama hatası ValueError'dır).
                logger.error("llm step=%s çıktı ayrıştırılamadı: %s", step, type(exc).__name__)
                raise LLMError(MSG_BAD_OUTPUT) from exc
        self._log(step, message, started)
        self._check_stop(step, message)
        parsed = message.parsed_output
        if parsed is None:
            raise LLMError(MSG_BAD_OUTPUT)
        return parsed

    async def stream_text(
        self, *, step: str, system: str, user: str, effort: str, max_tokens: int
    ) -> AsyncIterator[str]:
        started = time.monotonic()
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort},
            ) as stream:
                async for delta in stream.text_stream:
                    yield delta
                message = await stream.get_final_message()
        except anthropic.APIError as exc:
            logger.error(
                "llm step=%s hata=%s status=%s",
                step,
                type(exc).__name__,
                getattr(exc, "status_code", None),
            )
            raise _translate(exc) from exc
        self._log(step, message, started)
        self._check_stop(step, message)


def build_llm():
    """`LLM_PROVIDER` ayarına göre dil modeli istemcisi; Gemini paketi yalnız seçilince yüklenir."""
    if settings.LLM_PROVIDER == "ollama":
        from apps.agent.services.llm_ollama import OllamaLLM

        return OllamaLLM()
    if settings.LLM_PROVIDER == "gemini":
        from apps.agent.services.llm_gemini import GeminiLLM

        return GeminiLLM()
    return AnthropicLLM()
