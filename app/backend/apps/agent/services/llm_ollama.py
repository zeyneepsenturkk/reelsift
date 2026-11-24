"""Yerel Ollama dil modeli sınırı: `AnthropicLLM` ile aynı dış arayüz (`structured`, `stream_text`).

21 Kasım yerel model ölçümünde çalışan çağrı ayarları kullanılır: `/api/chat`, `format` = çıktı
modelinin JSON şeması, `temperature` 0, `num_ctx` ayardan, `num_predict` = `max_tokens`. Yapılı
çıktı pydantic ile doğrulanır. Anahtar yoktur; adres ve model ayardan gelir. Metinler loglanmaz,
yalnız kullanım ve süre.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

import httpx2
from django.conf import settings
from pydantic import ValidationError

from apps.agent.services import llm_config
from apps.agent.services.llm import (
    MSG_BAD_OUTPUT,
    MSG_TRUNCATED,
    MSG_UNAVAILABLE,
    LLMError,
    T,
    usage_tally,
)

logger = logging.getLogger(__name__)

MSG_OLLAMA_DOWN = "Yerel model sunucusuna ulaşılamadı; Ollama çalışıyor mu?"
MSG_OLLAMA_NO_MODEL = (
    "Yerel model bulunamadı. Yöneticiye haber ver (model Ollama'ya indirilmemiş olabilir)."
)
MSG_OLLAMA_TIMEOUT = "Yerel model zamanında cevap vermedi. İsteği biraz sadeleştirip tekrar dene."

SCHEMA_HINT = (
    "\n\nReturn ONLY a JSON object that matches this JSON schema (every field required):\n"
)


def _error_text(response: httpx2.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("error", "")) if isinstance(body, dict) else ""


class OllamaLLM:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        num_ctx: int | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.num_ctx = num_ctx or settings.OLLAMA_NUM_CTX
        self._transport = transport
        # Tek ekran kartı: çağrılar sırayla gider (ayar: max_concurrent_calls).
        self._semaphore = asyncio.Semaphore(
            llm_config.agent_option("max_concurrent_calls", "ollama")
        )

    def _client(self) -> httpx2.AsyncClient:
        # Zaman aşımı tek isteğin süresidir; yerel modelde ilk çağrı yükleme de içerir.
        return httpx2.AsyncClient(
            base_url=self.base_url,
            timeout=httpx2.Timeout(
                llm_config.agent_option("request_timeout_s", "ollama"), connect=10.0
            ),
            transport=self._transport,
        )

    def _body(self, system: str, user: str, max_tokens: int, *, stream: bool, schema=None) -> dict:
        body = {
            "model": self.model,
            "stream": stream,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": max_tokens},
        }
        if schema is not None:
            body["format"] = schema
        return body

    @staticmethod
    def _fail(step: str, exc: Exception) -> LLMError:
        """Taşıma hatasını kullanıcıya anlaşılır `LLMError`'a çevirir (ham metin gitmez)."""
        logger.error("llm step=%s hata=%s", step, type(exc).__name__)
        if isinstance(exc, httpx2.TimeoutException) and not isinstance(exc, httpx2.ConnectTimeout):
            return LLMError(MSG_OLLAMA_TIMEOUT)
        if isinstance(exc, httpx2.ConnectError | httpx2.ConnectTimeout | OSError):
            return LLMError(MSG_OLLAMA_DOWN)
        return LLMError(MSG_UNAVAILABLE)

    @staticmethod
    def _status_error(step: str, status: int, text: str) -> LLMError:
        logger.error("llm step=%s status=%s", step, status)
        if status == 404 and "not found" in text.lower():
            return LLMError(MSG_OLLAMA_NO_MODEL)
        return LLMError(MSG_UNAVAILABLE)

    def _log(self, step: str, data: dict, started: float) -> None:
        seconds = time.monotonic() - started
        input_tokens = data.get("prompt_eval_count") or 0
        output_tokens = data.get("eval_count") or 0
        logger.info(
            "llm step=%s model=%s in=%s out=%s stop=%s seconds=%.1f",
            step,
            self.model,
            input_tokens,
            output_tokens,
            data.get("done_reason"),
            seconds,
        )
        tally = usage_tally.get()
        if tally is not None:
            tally.add(step, input_tokens, output_tokens, seconds)

    @staticmethod
    def _check_stop(step: str, data: dict) -> None:
        if data.get("done_reason") == "length":
            logger.warning("llm step=%s num_predict sınırına takıldı", step)
            raise LLMError(MSG_TRUNCATED)

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
        schema = output.model_json_schema()
        body = self._body(
            system + SCHEMA_HINT + json.dumps(schema, ensure_ascii=False),
            user,
            max_tokens,
            stream=False,
            schema=schema,
        )
        started = time.monotonic()
        async with self._semaphore:
            try:
                async with self._client() as client:
                    response = await client.post("/api/chat", json=body)
            except (httpx2.HTTPError, OSError) as exc:
                raise self._fail(step, exc) from exc
        if response.status_code != 200:
            raise self._status_error(step, response.status_code, _error_text(response))
        try:
            data = response.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            logger.error("llm step=%s cevap okunamadı: %s", step, type(exc).__name__)
            raise LLMError(MSG_BAD_OUTPUT) from exc
        self._log(step, data, started)
        self._check_stop(step, data)
        try:
            return output.model_validate_json(content)
        except ValidationError as exc:
            logger.error("llm step=%s çıktı doğrulanamadı: %s", step, type(exc).__name__)
            raise LLMError(MSG_BAD_OUTPUT) from exc

    async def stream_text(
        self, *, step: str, system: str, user: str, effort: str, max_tokens: int
    ) -> AsyncIterator[str]:
        body = self._body(system, user, max_tokens, stream=True)
        started = time.monotonic()
        final: dict = {}
        async with self._semaphore:
            try:
                async with (
                    self._client() as client,
                    client.stream("POST", "/api/chat", json=body) as response,
                ):
                    if response.status_code != 200:
                        await response.aread()
                        raise self._status_error(step, response.status_code, _error_text(response))
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except ValueError as exc:
                            raise LLMError(MSG_BAD_OUTPUT) from exc
                        if chunk.get("error"):
                            logger.error("llm step=%s akışta sunucu hatası", step)
                            raise LLMError(MSG_UNAVAILABLE)
                        text = (chunk.get("message") or {}).get("content")
                        if text:
                            yield text
                        if chunk.get("done"):
                            final = chunk
                            break
            except (httpx2.HTTPError, OSError) as exc:
                raise self._fail(step, exc) from exc
        self._log(step, final, started)
        self._check_stop(step, final)
