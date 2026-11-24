"""Gemini (Google AI Studio) dil modeli sınırı: `AnthropicLLM` ile aynı dış arayüz.

Ücretsiz kota dakikalık ve günlük sınırlıdır; "yavaş olsun ama kota hatası çıkmasın" diye:
- süreç genelinde hız sınırlayıcı (iki çağrının başlangıcı en az 60 / GEMINI_RPM sn arayla),
- 429'da sunucunun verdiği süre kadar (en çok 90 sn; yoksa 20/40/80 sn) bekleyip en çok 3 yeniden
  deneme; 500/503/504'te 5/15/30/60... sn arayla en çok 10 yeniden deneme,
- birincil model 503'lerle tükenirse ya da günlük kotası dolarsa `GEMINI_FALLBACK_MODELS`'taki
  sıradaki modele geçilir (10 dakika kalıcı),
- SDK'nın kendi yeniden denemesi kapalı (çifte deneme kotayı yakar).
Anahtar yalnız ortamdan (GEMINI_API_KEY) okunur; metinler ve anahtar loglanmaz.
"""

import asyncio
import logging
import os
import re
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

import httpx2
from django.conf import settings
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from apps.agent.services.llm import (
    MSG_BAD_OUTPUT,
    MSG_CONFIG,
    MSG_QUOTA,
    MSG_QUOTA_DAY,
    MSG_QUOTA_MINUTE,
    MSG_TRUNCATED,
    MSG_UNAVAILABLE,
    LLMError,
    LLMRefused,
    T,
    usage_tally,
)

logger = logging.getLogger(__name__)

# 429'da sunucu süre vermezse beklenecek saniyeler (en çok 3 yeniden deneme).
RATE_LIMIT_BACKOFF_S = (20, 40, 80)
# 500 / 503 / 504 gibi geçici hatalarda (en çok 10 yeniden deneme; yavaşlık kabul).
TRANSIENT_BACKOFF_S = (5, 15, 30, 60, 60, 60, 60, 60, 60, 60)
TRANSIENT_CODES = (500, 503, 504)
# Sunucunun "şu kadar sonra dene" süresi bundan uzunsa kırpılır.
MAX_RETRY_DELAY_S = 90
# Aday dönmeyen ve engel nedeni de olmayan cevapta aynı çağrının en çok yeniden deneme sayısı.
EMPTY_ANSWER_RETRIES = 2
# Yedek modele geçiş bu kadar saniye kalır; sonra birincil model yeniden denenir.
FALLBACK_HOLD_S = 600
# Düşünme tokenları çıktı sınırından yer; kesilmesin diye sınıra eklenen pay.
THINKING_TOKEN_PAD = 1024

# Düşünme hız ve kota için en düşük düzeyde; adımın `effort` değeri bu yüzden kullanılmaz.
THINKING_LEVEL = types.ThinkingLevel.MINIMAL

# Engel / güvenlik nedeniyle cevap üretilmemiş bitiş nedenleri.
REFUSAL_REASONS = frozenset(
    {
        types.FinishReason.SAFETY,
        types.FinishReason.RECITATION,
        types.FinishReason.LANGUAGE,
        types.FinishReason.OTHER,
        types.FinishReason.BLOCKLIST,
        types.FinishReason.PROHIBITED_CONTENT,
        types.FinishReason.SPII,
        types.FinishReason.MODEL_ARMOR,
    }
)

_RETRY_DELAY = re.compile(r"^(\d+(?:\.\d+)?)s$")


class RateLimiter:
    """İki çağrının başlangıcı arasında en az 60 / rpm saniye bırakır.

    Sıra (slot) kısa bir kilit altında eşzamanlı hesaplanıp ayrılır; bekleme kilidin dışında
    yapılır. Böylece olay döngüsüne bağlı bir kilit gerekmez: sınır süreçte tek olduğu için
    farklı döngülerde ve iş parçacıklarında da tutar. Saat ve uyku testte verilir.
    """

    def __init__(
        self,
        rpm: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.rpm = rpm
        self._interval = 60 / rpm
        self._clock = clock
        self._sleep = sleep
        self._guard = threading.Lock()
        self._next_start = 0.0

    async def wait_turn(self) -> None:
        with self._guard:
            now = self._clock()
            start = max(now, self._next_start)
            self._next_start = start + self._interval
        if start > now:
            await self._sleep(start - now)


_shared_limiter: RateLimiter | None = None


def shared_limiter() -> RateLimiter:
    """Süreçteki tek sınırlayıcı; tüm GeminiLLM örnekleri aynı kotayı paylaşır."""
    global _shared_limiter
    if _shared_limiter is None:
        _shared_limiter = RateLimiter(settings.GEMINI_RPM)
    return _shared_limiter


class ModelRotation:
    """Birincil modelden sıradaki yedeğe geçiş durumu (süreçte ortak).

    Bir model tükenince (503 denemeleri ya da günlük kota) `hold` saniye kullanılmaz; süre
    dolunca yeniden denenir. Hepsi dinleniyorsa zincirin tamamı sırayla denenir.
    """

    def __init__(
        self,
        primary: str,
        fallbacks: Sequence[str] = (),
        *,
        clock: Callable[[], float] = time.monotonic,
        hold: float = FALLBACK_HOLD_S,
    ):
        self.chain = [primary, *dict.fromkeys(name for name in fallbacks if name != primary)]
        self._clock = clock
        self._hold = hold
        self._resting_until: dict[str, float] = {}

    def available(self) -> list[str]:
        now = self._clock()
        ready = [name for name in self.chain if self._resting_until.get(name, 0.0) <= now]
        return ready or list(self.chain)

    def rest(self, model: str) -> None:
        self._resting_until[model] = self._clock() + self._hold


_shared_rotations: dict[tuple[str, ...], ModelRotation] = {}


def shared_rotation(primary: str, fallbacks: Sequence[str]) -> ModelRotation:
    """Aynı model zinciri için süreçteki tek geçiş durumu."""
    key = (primary, *fallbacks)
    if key not in _shared_rotations:
        _shared_rotations[key] = ModelRotation(primary, fallbacks)
    return _shared_rotations[key]


class _ModelExhausted(Exception):
    """Bu model için denemeler tükendi; yedek varsa sıradakine geçilir."""

    def __init__(self, error: LLMError):
        super().__init__(error.message)
        self.error = error


def _error_items(exc: errors.APIError) -> list[dict]:
    body = exc.details if isinstance(exc.details, dict) else {}
    error = body.get("error", body)
    items = error.get("details") if isinstance(error, dict) else None
    return [item for item in items or [] if isinstance(item, dict)]


def _quota_info(exc: errors.APIError) -> tuple[float | None, str | None]:
    """429 cevabından ("şu kadar sonra dene" saniyesi, kota kapsamı) çıkarır.

    Kapsam: "day" (günlük), "minute" (dakikalık) ya da None (cevap ayırt ettirmiyor).
    """
    delay = None
    scopes = set()
    for item in _error_items(exc):
        kind = str(item.get("@type", ""))
        if kind.endswith("RetryInfo"):
            match = _RETRY_DELAY.match(str(item.get("retryDelay", "")))
            if match:
                delay = float(match.group(1))
        elif kind.endswith("QuotaFailure"):
            for violation in item.get("violations") or []:
                quota_id = str(violation.get("quotaId", "")).lower()
                if "perday" in quota_id:
                    scopes.add("day")
                elif "perminute" in quota_id:
                    scopes.add("minute")
    scope = "day" if "day" in scopes else ("minute" if "minute" in scopes else None)
    return delay, scope


def _is_key_invalid(exc: errors.APIError) -> bool:
    return exc.code == 400 and "API_KEY_INVALID" in str(exc.details)


def _quota_message(scope: str | None) -> str:
    return {"day": MSG_QUOTA_DAY, "minute": MSG_QUOTA_MINUTE}.get(scope, MSG_QUOTA)


def _finish_name(reason) -> str | None:
    return getattr(reason, "name", reason)


class GeminiLLM:
    def __init__(
        self,
        *,
        client: genai.Client | None = None,
        model: str | None = None,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rotation: ModelRotation | None = None,
    ):
        self._client = client
        self.model = model or settings.GEMINI_MODEL
        self._limiter = limiter or shared_limiter()
        self._sleep = sleep
        self._rotation = rotation or shared_rotation(
            self.model, tuple(settings.GEMINI_FALLBACK_MODELS)
        )

    @property
    def client(self) -> genai.Client:
        # Anahtar eksikse uygulama açılışı değil, ilk çağrı hata verir.
        if self._client is None:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                logger.error("GEMINI_API_KEY tanımlı değil")
                raise LLMError(MSG_CONFIG)
            self._client = genai.Client(
                api_key=api_key,
                # Zaman aşımı tek isteğin HTTP süresidir (ms); hız sınırlayıcı ve 429 beklemesi
                # isteğin dışında kalır. attempts=1: SDK kendi başına yeniden denemesin.
                http_options=types.HttpOptions(
                    timeout=int(settings.AGENT["request_timeout_s"] * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        return self._client

    def _config(self, system: str, max_tokens: int, **extra) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens + THINKING_TOKEN_PAD,
            thinking_config=types.ThinkingConfig(thinking_level=THINKING_LEVEL),
            **extra,
        )

    async def _attempt(self, step: str, call: Callable[[str], Awaitable]):
        """Hız sınırından geçip çağrıyı yapar; 429 ve geçici hatalarda bekleyip yeniden dener.

        Birincil model tükenirse (503 denemeleri, günlük kota) sıradaki yedek modele geçilir.
        (sonuç, çağrının başladığı an, kullanılan model) döner; süre ölçümü beklemeleri saymaz.
        """
        models = self._rotation.available()
        for index, model in enumerate(models):
            try:
                result, started = await self._attempt_model(step, model, call)
            except _ModelExhausted as exhausted:
                self._rotation.rest(model)
                if index == len(models) - 1:
                    raise exhausted.error from exhausted.__cause__
                logger.warning(
                    "llm step=%s model=%s tükendi, yedek modele geçiliyor (model=%s)",
                    step,
                    model,
                    models[index + 1],
                )
                continue
            return result, started, model
        raise LLMError(MSG_UNAVAILABLE)  # ulaşılamaz: zincir boş olamaz

    async def _attempt_model(self, step: str, model: str, call: Callable[[str], Awaitable]):
        rate_retries = 0
        transient_retries = 0
        while True:
            await self._limiter.wait_turn()
            started = time.monotonic()
            try:
                return await call(model), started
            except errors.APIError as exc:
                logger.error(
                    "llm step=%s model=%s hata=%s code=%s",
                    step,
                    model,
                    type(exc).__name__,
                    exc.code,
                )
                if exc.code in (401, 403) or _is_key_invalid(exc):
                    raise LLMError(MSG_CONFIG) from exc
                if exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED":
                    delay, scope = _quota_info(exc)
                    if scope == "day":
                        raise _ModelExhausted(LLMError(MSG_QUOTA_DAY)) from exc
                    if rate_retries >= len(RATE_LIMIT_BACKOFF_S):
                        raise LLMError(_quota_message(scope)) from exc
                    wait = RATE_LIMIT_BACKOFF_S[rate_retries] if delay is None else delay
                    wait = min(wait, MAX_RETRY_DELAY_S)
                    rate_retries += 1
                elif exc.code in TRANSIENT_CODES:
                    if transient_retries >= len(TRANSIENT_BACKOFF_S):
                        raise _ModelExhausted(LLMError(MSG_UNAVAILABLE)) from exc
                    wait = TRANSIENT_BACKOFF_S[transient_retries]
                    transient_retries += 1
                else:
                    raise LLMError(MSG_UNAVAILABLE) from exc
                logger.warning("llm step=%s %.1f sn sonra yeniden denenecek", step, wait)
                await self._sleep(wait)
            except (httpx2.HTTPError, OSError) as exc:
                logger.error("llm step=%s bağlantı hatası=%s", step, type(exc).__name__)
                raise LLMError(MSG_UNAVAILABLE) from exc

    def _log(self, step: str, usage, finish, started: float, model: str) -> None:
        seconds = time.monotonic() - started
        input_tokens = (usage.prompt_token_count if usage else 0) or 0
        # Düşünme tokenları da çıktı olarak ücretlenir ve kotaya yazılır.
        output_tokens = (
            ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0))
            if usage
            else 0
        )
        logger.info(
            "llm step=%s model=%s in=%s out=%s stop=%s seconds=%.1f",
            step,
            model,
            input_tokens,
            output_tokens,
            _finish_name(finish),
            seconds,
        )
        tally = usage_tally.get()
        if tally is not None:
            tally.add(step, input_tokens, output_tokens, seconds)

    @staticmethod
    def _check_finish(step: str, finish) -> None:
        if finish == types.FinishReason.MAX_TOKENS:
            logger.warning("llm step=%s çıktı token sınırına takıldı", step)
            raise LLMError(MSG_TRUNCATED)
        if finish in REFUSAL_REASONS:
            logger.warning("llm step=%s model cevap vermedi stop=%s", step, _finish_name(finish))
            raise LLMRefused(reason=_finish_name(finish))

    @staticmethod
    def _finish_reason(response):
        candidates = response.candidates or []
        return candidates[0].finish_reason if candidates else None

    @staticmethod
    def _block_reason(response) -> str | None:
        """İstemin engellenme nedeni (yoksa None); yalnız tür adı, metin yok."""
        feedback = response.prompt_feedback
        reason = feedback.block_reason if feedback else None
        if reason is None or reason == types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
            return None
        return _finish_name(reason)

    @staticmethod
    def _stream_error(step: str, exc: errors.APIError) -> LLMError:
        """Akış ortasında gelen hata: kimlik -> yapılandırma, 429 -> kota, diğer -> ulaşılamıyor."""
        logger.error("llm step=%s hata=%s code=%s", step, type(exc).__name__, exc.code)
        if exc.code in (401, 403) or _is_key_invalid(exc):
            return LLMError(MSG_CONFIG)
        if exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED":
            return LLMError(_quota_message(_quota_info(exc)[1]))
        return LLMError(MSG_UNAVAILABLE)

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
        config = self._config(
            system,
            max_tokens,
            response_mime_type="application/json",
            response_json_schema=output.model_json_schema(),
        )
        # Gemini şemadaki uzunluk vb. kısıtları uygulamaz; doğrulamayı pydantic yapar.
        # Bozuk cevapta aynı çağrı bir kez daha denenir.
        bad_outputs = 0
        empty_answers = 0
        while True:
            response, started, model = await self._attempt(
                step,
                lambda model: self.client.aio.models.generate_content(
                    model=model, contents=user, config=config
                ),
            )
            finish = self._finish_reason(response)
            self._log(step, response.usage_metadata, finish, started, model)
            if not response.candidates:
                block = self._block_reason(response)
                if block is not None:
                    logger.warning("llm step=%s istem engellendi block_reason=%s", step, block)
                    raise LLMRefused(reason=block)
                empty_answers += 1
                logger.warning(
                    "llm step=%s aday yok, engel yok deneme=%s/%s",
                    step,
                    empty_answers,
                    EMPTY_ANSWER_RETRIES + 1,
                )
                if empty_answers > EMPTY_ANSWER_RETRIES:
                    raise LLMRefused(reason="EMPTY")
                continue
            self._check_finish(step, finish)
            text = response.text
            if not text:
                logger.warning("llm step=%s boş cevap", step)
                raise LLMRefused(reason="EMPTY")
            try:
                return output.model_validate_json(text)
            except ValidationError as exc:
                bad_outputs += 1
                logger.warning(
                    "llm step=%s çıktı doğrulanamadı deneme=%s hata=%s",
                    step,
                    bad_outputs,
                    type(exc).__name__,
                )
                if bad_outputs >= 2:
                    raise LLMError(MSG_BAD_OUTPUT) from exc

    async def stream_text(
        self, *, step: str, system: str, user: str, effort: str, max_tokens: int
    ) -> AsyncIterator[str]:
        config = self._config(system, max_tokens)

        async def open_stream(model: str):
            # Hata ilk parçada da çıkabilir; yeniden deneme yalnız hiçbir şey akmadan önce olur.
            stream = await self.client.aio.models.generate_content_stream(
                model=model, contents=user, config=config
            )
            iterator = stream.__aiter__()
            return iterator, await anext(iterator, None)

        empty_answers = 0
        while True:
            (iterator, chunk), started, model = await self._attempt(step, open_stream)
            usage = None
            finish = None
            block = None
            had_candidates = False
            yielded = False
            try:
                while chunk is not None:
                    usage = chunk.usage_metadata or usage
                    finish = self._finish_reason(chunk) or finish
                    block = self._block_reason(chunk) or block
                    had_candidates = had_candidates or bool(chunk.candidates)
                    text = chunk.text
                    if text:
                        yielded = True
                        yield text
                    chunk = await anext(iterator, None)
            except errors.APIError as exc:
                raise self._stream_error(step, exc) from exc
            except (httpx2.HTTPError, OSError) as exc:
                logger.error("llm step=%s bağlantı hatası=%s", step, type(exc).__name__)
                raise LLMError(MSG_UNAVAILABLE) from exc
            self._log(step, usage, finish, started, model)
            if block is not None:
                logger.warning("llm step=%s istem engellendi block_reason=%s", step, block)
                raise LLMRefused(reason=block)
            self._check_finish(step, finish)
            if yielded:
                return
            if not had_candidates and empty_answers < EMPTY_ANSWER_RETRIES:
                empty_answers += 1
                logger.warning(
                    "llm step=%s aday yok, engel yok deneme=%s/%s",
                    step,
                    empty_answers,
                    EMPTY_ANSWER_RETRIES + 1,
                )
                continue
            logger.warning("llm step=%s boş cevap", step)
            raise LLMRefused(reason="EMPTY")
