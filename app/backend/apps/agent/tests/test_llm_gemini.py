import asyncio
import os
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from google.genai import errors, types

from apps.agent.schemas import AltQueryOutput
from apps.agent.services import llm as llm_module
from apps.agent.services import llm_gemini
from apps.agent.services.llm import LLMError, LLMRefused, UsageTally, usage_tally
from apps.agent.services.llm_gemini import GeminiLLM, ModelRotation, RateLimiter

VALID = '{"en_query": "a", "hyde": "b"}'
MODEL = "gemini-test-model"
TRANSIENT_WAITS = [5, 15, 30, 60, 60, 60, 60, 60, 60, 60]  # 500 / 503 / 504: 10 yeniden deneme


class FakeClock:
    """Gerçek bekleme yok: uyku saati ileri sarar."""

    def __init__(self):
        self.now = 1000.0
        self.waits: list[float] = []
        self.gate_waits: list[float] = []
        self._sleepers: list[list[float]] = []

    def __call__(self) -> float:
        return self.now

    async def _sleep(self, seconds: float) -> None:
        # Eşzamanlı uyuyanlardan hedefi en erken olan uyanır; saat o ana ilerler.
        token = [self.now + seconds]
        self._sleepers.append(token)
        try:
            while min(self._sleepers, key=lambda item: item[0]) is not token:
                await asyncio.sleep(0)
            self.now = max(self.now, token[0])
            await asyncio.sleep(0)
        finally:
            self._sleepers.remove(token)

    async def backoff(self, seconds: float) -> None:
        self.waits.append(seconds)
        await self._sleep(seconds)

    async def gate(self, seconds: float) -> None:
        self.gate_waits.append(seconds)
        await self._sleep(seconds)


def response(
    text=VALID,
    finish=types.FinishReason.STOP,
    prompt=10,
    out=5,
    thoughts=None,
) -> types.GenerateContentResponse:
    content = types.Content(role="model", parts=[types.Part(text=text)]) if text else None
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=content, finish_reason=finish)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt,
            candidates_token_count=out,
            thoughts_token_count=thoughts,
        ),
    )


def blocked_response(reason=types.BlockedReason.SAFETY) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[],
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=reason),
    )


def candidateless_response() -> types.GenerateContentResponse:
    """HTTP 200 ama aday yok ve engel nedeni yok."""
    return types.GenerateContentResponse(
        candidates=[],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=9),
    )


def api_error(code: int, status: str, details=None, message="hata sk-secret-anahtar"):
    body = {"error": {"code": code, "message": message, "status": status}}
    if details is not None:
        body["error"]["details"] = details
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, body)


def quota_error(quota_id=None, retry_delay=None):
    details = []
    if retry_delay is not None:
        details.append(
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay}
        )
    if quota_id is not None:
        details.append(
            {
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaMetric": "x", "quotaId": quota_id}],
            }
        )
    return api_error(429, "RESOURCE_EXHAUSTED", details)


class FakeModels:
    def __init__(self, outcomes, clock=None):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []
        self.starts: list[float] = []
        self.clock = clock

    def _next(self, kwargs):
        self.calls.append(kwargs)
        if self.clock is not None:
            self.starts.append(self.clock())
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def generate_content(self, **kwargs):
        return self._next(kwargs)

    async def generate_content_stream(self, **kwargs):
        chunks = self._next(kwargs)

        async def generate():
            for chunk in chunks:
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk

        return generate()


class FakeClient:
    def __init__(self, models: FakeModels):
        self.aio = mock.Mock(models=models)


FALLBACK = "gemini-yedek-model"


def make_llm(outcomes, rpm=8, clock=None, fallbacks=()):
    clock = clock or FakeClock()
    models = FakeModels(outcomes, clock)
    llm = GeminiLLM(
        client=FakeClient(models),
        model=MODEL,
        limiter=RateLimiter(rpm, clock=clock, sleep=clock.gate),
        sleep=clock.backoff,
        rotation=ModelRotation(MODEL, fallbacks, clock=clock),
    )
    return llm, models, clock


async def structured(llm, output=AltQueryOutput, user="kullanıcı metni"):
    return await llm.structured(
        step="parse", system="sistem", user=user, output=output, effort="low", max_tokens=4000
    )


class StructuredTests(SimpleTestCase):
    async def test_success_sends_schema_thinking_and_token_limit(self):
        llm, models, _ = make_llm([response()])

        result = await structured(llm)

        self.assertEqual(result, AltQueryOutput(en_query="a", hyde="b"))
        kwargs = models.calls[0]
        self.assertEqual(kwargs["model"], MODEL)
        self.assertEqual(kwargs["contents"], "kullanıcı metni")
        config = kwargs["config"]
        self.assertEqual(config.system_instruction, "sistem")
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertEqual(config.response_json_schema, AltQueryOutput.model_json_schema())
        self.assertEqual(config.thinking_config.thinking_level, types.ThinkingLevel.MINIMAL)
        self.assertEqual(config.max_output_tokens, 4000 + llm_gemini.THINKING_TOKEN_PAD)

    async def test_bad_json_is_retried_once_then_succeeds(self):
        llm, models, _ = make_llm([response(text="{bozuk"), response()])

        with self.assertLogs("apps.agent.services.llm_gemini", level="WARNING") as logs:
            result = await structured(llm)

        self.assertEqual(result.en_query, "a")
        self.assertEqual(len(models.calls), 2)
        self.assertIn("step=parse", logs.output[0])
        self.assertNotIn("bozuk", logs.output[0])

    async def test_two_bad_outputs_give_bad_output_message(self):
        for texts in (["{bozuk", "{bozuk"], ['{"en_query": 1, "hyde": "b"}', '{"x": 1}']):
            with self.subTest(texts=texts):
                llm, models, _ = make_llm([response(text=t) for t in texts])
                with self.assertRaises(LLMError) as ctx:
                    await structured(llm)
                self.assertEqual(ctx.exception.message, llm_module.MSG_BAD_OUTPUT)
                self.assertEqual(len(models.calls), 2)

    async def test_token_limit_is_truncated_and_not_retried(self):
        llm, models, _ = make_llm([response(text='{"en', finish=types.FinishReason.MAX_TOKENS)])

        with self.assertRaises(LLMError) as ctx:
            await structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_TRUNCATED)
        self.assertEqual(len(models.calls), 1)

    async def test_blocked_safety_and_empty_answers_are_refused(self):
        cases = {
            "prompt engeli": blocked_response(),
            "güvenlik": response(text=None, finish=types.FinishReason.SAFETY),
            "tekrar": response(text=None, finish=types.FinishReason.RECITATION),
            "boş": response(text=None),
        }
        for name, reply in cases.items():
            with self.subTest(name=name):
                llm, models, _ = make_llm([reply])
                with self.assertRaises(LLMError) as ctx:
                    await structured(llm)
                self.assertEqual(ctx.exception.message, llm_module.MSG_REFUSED)
                self.assertEqual(len(models.calls), 1)

    async def test_usage_is_logged_and_tallied_without_text(self):
        llm, _, _ = make_llm([response(prompt=120, out=30, thoughts=7)])
        tally = UsageTally()
        token = usage_tally.set(tally)
        try:
            with self.assertLogs("apps.agent.services.llm_gemini", level="INFO") as logs:
                await structured(llm, user="çok gizli istem metni")
        finally:
            usage_tally.reset(token)

        line = logs.output[0]
        self.assertIn(f"llm step=parse model={MODEL} in=120 out=37 stop=STOP", line)
        self.assertNotIn("gizli", line)
        self.assertNotIn('"en_query"', line)
        self.assertEqual((tally.input_tokens, tally.output_tokens, tally.calls), (120, 37, 1))
        self.assertIn("parse", tally.by_step)

    async def test_missing_usage_counts_as_zero(self):
        reply = response()
        reply.usage_metadata = None
        llm, _, _ = make_llm([reply])
        tally = UsageTally()
        token = usage_tally.set(tally)
        try:
            await structured(llm)
        finally:
            usage_tally.reset(token)

        self.assertEqual((tally.input_tokens, tally.output_tokens), (0, 0))

    def test_default_model_comes_from_settings(self):
        self.assertEqual(GeminiLLM(client=object()).model, settings.GEMINI_MODEL)


class RateLimitRetryTests(SimpleTestCase):
    async def test_429_waits_for_the_delay_the_server_gives(self):
        llm, models, clock = make_llm([quota_error(retry_delay="34.5s"), response()])

        await structured(llm)

        self.assertEqual(clock.waits, [34.5])
        self.assertEqual(len(models.calls), 2)

    async def test_429_delay_from_the_server_is_capped_at_90_seconds(self):
        llm, _, clock = make_llm([quota_error(retry_delay="300s"), response()])

        await structured(llm)

        self.assertEqual(clock.waits, [90])

    async def test_429_without_delay_backs_off_20_40_80_then_gives_up(self):
        llm, models, clock = make_llm([quota_error() for _ in range(4)])

        with self.assertRaises(LLMError) as ctx:
            await structured(llm)

        self.assertEqual(clock.waits, [20, 40, 80])
        self.assertEqual(len(models.calls), 4)
        self.assertEqual(ctx.exception.message, llm_module.MSG_QUOTA)

    async def test_429_recovers_on_a_later_try(self):
        llm, models, clock = make_llm([quota_error(), quota_error(), response()])

        result = await structured(llm)

        self.assertEqual(result.hyde, "b")
        self.assertEqual(clock.waits, [20, 40])
        self.assertEqual(len(models.calls), 3)

    async def test_minute_quota_exhausted_gives_minute_message(self):
        quota_id = "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
        llm, models, clock = make_llm([quota_error(quota_id) for _ in range(4)])

        with self.assertRaises(LLMError) as ctx:
            await structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_QUOTA_MINUTE)
        self.assertEqual(clock.waits, [20, 40, 80])

    async def test_daily_quota_is_not_retried(self):
        quota_id = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        llm, models, clock = make_llm([quota_error(quota_id, retry_delay="30s")])

        with self.assertRaises(LLMError) as ctx:
            await structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_QUOTA_DAY)
        self.assertEqual(len(models.calls), 1)
        self.assertEqual(clock.waits, [])

    async def test_transient_server_errors_retry_ten_times_with_growing_waits_and_stop(self):
        llm, models, clock = make_llm([api_error(503, "UNAVAILABLE") for _ in range(11)])

        with self.assertRaises(LLMError) as ctx:
            await structured(llm)

        self.assertEqual(clock.waits, TRANSIENT_WAITS)
        self.assertEqual(len(models.calls), 11)
        self.assertEqual(ctx.exception.message, llm_module.MSG_UNAVAILABLE)

    async def test_transient_server_error_recovers_on_the_last_retry(self):
        outcomes = [api_error(503, "UNAVAILABLE") for _ in range(10)] + [response()]
        llm, models, clock = make_llm(outcomes)

        result = await structured(llm)

        self.assertEqual(result.hyde, "b")
        self.assertEqual(clock.waits, TRANSIENT_WAITS)
        self.assertEqual(len(models.calls), 11)

    async def test_500_is_retried_like_503(self):
        llm, models, clock = make_llm([api_error(500, "INTERNAL"), response()])

        await structured(llm)

        self.assertEqual(clock.waits, [5])
        self.assertEqual(len(models.calls), 2)

    async def test_504_then_success(self):
        llm, _, clock = make_llm([api_error(504, "DEADLINE_EXCEEDED"), response()])

        await structured(llm)

        self.assertEqual(clock.waits, [5])

    async def test_auth_errors_are_config_errors_and_not_retried(self):
        errors_ = [
            api_error(401, "UNAUTHENTICATED"),
            api_error(403, "PERMISSION_DENIED"),
            api_error(
                400,
                "INVALID_ARGUMENT",
                [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "API_KEY_INVALID",
                    }
                ],
            ),
        ]
        for error in errors_:
            with self.subTest(code=error.code):
                llm, models, clock = make_llm([error])
                with self.assertRaises(LLMError) as ctx:
                    await structured(llm)
                self.assertEqual(ctx.exception.message, llm_module.MSG_CONFIG)
                self.assertNotIn("sk-secret", ctx.exception.message)
                self.assertEqual(len(models.calls), 1)
                self.assertEqual(clock.waits, [])

    async def test_other_errors_are_plain_unavailable_messages(self):
        for error in (api_error(400, "INVALID_ARGUMENT"), api_error(404, "NOT_FOUND")):
            with self.subTest(code=error.code):
                llm, models, _ = make_llm([error])
                with self.assertRaises(LLMError) as ctx:
                    await structured(llm)
                self.assertEqual(ctx.exception.message, llm_module.MSG_UNAVAILABLE)
                self.assertNotIn("sk-secret", ctx.exception.message)
                self.assertEqual(len(models.calls), 1)

    async def test_waiting_is_outside_the_request_timeout(self):
        # Bekleme istemci zaman aşımına girmez: zaman aşımı yalnız tek isteğin HTTP ayarıdır.
        built = {}

        def fake_client(**kwargs):
            built.update(kwargs)
            return FakeClient(FakeModels([response()]))

        llm = GeminiLLM(model=MODEL, limiter=RateLimiter(8, clock=FakeClock()))
        with (
            mock.patch.dict(os.environ, {"GEMINI_API_KEY": "sahte-test-anahtari"}),
            mock.patch.object(llm_gemini.genai, "Client", fake_client),
        ):
            await structured(llm)

        options = built["http_options"]
        self.assertEqual(options.timeout, settings.AGENT["request_timeout_s"] * 1000)
        self.assertEqual(options.retry_options.attempts, 1)
        self.assertEqual(built["api_key"], "sahte-test-anahtari")

    async def test_missing_key_fails_on_first_call_not_at_startup(self):
        llm = GeminiLLM(model=MODEL, limiter=RateLimiter(8, clock=FakeClock()))
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMError) as ctx:
                await structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_CONFIG)


async def collect_stream(llm):
    return [
        piece
        async for piece in llm.stream_text(
            step="respond", system="s", user="u", effort="low", max_tokens=4000
        )
    ]


class EmptyAnswerTests(SimpleTestCase):
    async def test_blocked_prompt_is_refused_logged_and_not_retried(self):
        llm, models, _ = make_llm([blocked_response(types.BlockedReason.PROHIBITED_CONTENT)])

        with self.assertLogs("apps.agent.services.llm_gemini", level="INFO") as logs:
            with self.assertRaises(LLMError) as ctx:
                await structured(llm, user="çok gizli istem metni")

        self.assertEqual(ctx.exception.message, llm_module.MSG_REFUSED)
        self.assertEqual(len(models.calls), 1)
        text = "\n".join(logs.output)
        self.assertIn("block_reason=PROHIBITED_CONTENT", text)
        self.assertNotIn("gizli", text)

    async def test_every_refusal_carries_the_refused_marker_and_its_reason(self):
        cases = {
            "PROHIBITED_CONTENT": blocked_response(types.BlockedReason.PROHIBITED_CONTENT),
            "SAFETY": response(text=None, finish=types.FinishReason.SAFETY),
            "EMPTY": response(text=None),
        }
        for reason, reply in cases.items():
            with self.subTest(reason=reason):
                llm, _, _ = make_llm([reply])
                with self.assertRaises(LLMRefused) as ctx:
                    await structured(llm)
                self.assertEqual(ctx.exception.reason, reason)
                self.assertEqual(ctx.exception.message, llm_module.MSG_REFUSED)
        llm, _, _ = make_llm([[blocked_response(types.BlockedReason.PROHIBITED_CONTENT)]])
        with self.assertRaises(LLMRefused) as ctx:
            await collect_stream(llm)
        self.assertEqual(ctx.exception.reason, "PROHIBITED_CONTENT")

    async def test_non_refusal_errors_are_not_marked_as_refused(self):
        for reply in (
            response(text=None, finish=types.FinishReason.MAX_TOKENS),
            api_error(403, "PERMISSION_DENIED"),
            response(text="{bozuk"),
        ):
            with self.subTest(reply=type(reply).__name__):
                llm, _, _ = make_llm([reply, response(text="{bozuk")])
                with self.assertRaises(LLMError) as ctx:
                    await structured(llm)
                self.assertNotIsInstance(ctx.exception, LLMRefused)

    async def test_finish_reason_of_a_refused_answer_is_logged(self):
        llm, _, _ = make_llm([response(text=None, finish=types.FinishReason.PROHIBITED_CONTENT)])

        with self.assertLogs("apps.agent.services.llm_gemini", level="INFO") as logs:
            with self.assertRaises(LLMError):
                await structured(llm)

        self.assertIn("stop=PROHIBITED_CONTENT", "\n".join(logs.output))

    async def test_candidateless_answer_without_a_block_is_retried_then_succeeds(self):
        llm, models, _ = make_llm([candidateless_response(), candidateless_response(), response()])

        with self.assertLogs("apps.agent.services.llm_gemini", level="WARNING") as logs:
            result = await structured(llm)

        self.assertEqual(result.hyde, "b")
        self.assertEqual(len(models.calls), 3)
        self.assertIn("engel yok", "\n".join(logs.output))

    async def test_candidateless_answer_gives_up_after_two_retries(self):
        llm, models, _ = make_llm([candidateless_response() for _ in range(3)])

        with self.assertRaises(LLMError) as ctx:
            await structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_REFUSED)
        self.assertEqual(len(models.calls), 3)

    async def test_empty_answer_retries_go_through_the_rate_limiter(self):
        llm, models, _ = make_llm([candidateless_response(), response()], rpm=8)

        await structured(llm)

        self.assertGreaterEqual(models.starts[1] - models.starts[0], 7.5 - 1e-9)

    async def test_stream_blocked_prompt_is_refused_without_retry(self):
        llm, models, _ = make_llm([[blocked_response(types.BlockedReason.PROHIBITED_CONTENT)]])

        with self.assertLogs("apps.agent.services.llm_gemini", level="INFO") as logs:
            with self.assertRaises(LLMError) as ctx:
                await collect_stream(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_REFUSED)
        self.assertEqual(len(models.calls), 1)
        self.assertIn("block_reason=PROHIBITED_CONTENT", "\n".join(logs.output))

    async def test_stream_candidateless_answer_without_a_block_is_retried(self):
        llm, models, _ = make_llm([[candidateless_response()], stream_chunks("a", "b")])

        self.assertEqual(await collect_stream(llm), ["a", "b"])
        self.assertEqual(len(models.calls), 2)


class FallbackModelTests(SimpleTestCase):
    async def test_switches_to_the_fallback_when_the_primary_exhausts_503_retries(self):
        outcomes = [api_error(503, "UNAVAILABLE") for _ in range(11)] + [response()]
        llm, models, clock = make_llm(outcomes, fallbacks=(FALLBACK,))

        with self.assertLogs("apps.agent.services.llm_gemini", level="INFO") as logs:
            result = await structured(llm)

        self.assertEqual(result.hyde, "b")
        self.assertEqual([call["model"] for call in models.calls], [MODEL] * 11 + [FALLBACK])
        self.assertEqual(clock.waits, TRANSIENT_WAITS)
        self.assertIn(f"model={FALLBACK}", "\n".join(logs.output))

    async def test_daily_quota_switches_to_the_fallback_without_waiting(self):
        quota_id = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        llm, models, clock = make_llm([quota_error(quota_id), response()], fallbacks=(FALLBACK,))

        result = await structured(llm)

        self.assertEqual(result.hyde, "b")
        self.assertEqual([call["model"] for call in models.calls], [MODEL, FALLBACK])
        self.assertEqual(clock.waits, [])

    async def test_minute_quota_does_not_switch_models(self):
        quota_id = "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
        outcomes = [quota_error(quota_id) for _ in range(4)]
        llm, models, _ = make_llm(outcomes, fallbacks=(FALLBACK,))

        with self.assertRaises(LLMError) as ctx:
            await structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_QUOTA_MINUTE)
        self.assertEqual({call["model"] for call in models.calls}, {MODEL})

    async def test_switch_lasts_ten_minutes_then_the_primary_is_tried_again(self):
        quota_id = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        outcomes = [quota_error(quota_id), response(), response(), response()]
        llm, models, clock = make_llm(outcomes, fallbacks=(FALLBACK,))

        start = clock.now  # tükenme anı: yedek modele geçiş 600 sn sürer
        await structured(llm)
        clock.now = start + 599
        await structured(llm)
        clock.now = start + 601
        await structured(llm)

        self.assertEqual(
            [call["model"] for call in models.calls], [MODEL, FALLBACK, FALLBACK, MODEL]
        )

    async def test_all_models_exhausted_gives_todays_message(self):
        outcomes = [api_error(503, "UNAVAILABLE") for _ in range(22)]
        llm, models, _ = make_llm(outcomes, fallbacks=(FALLBACK,))

        with self.assertRaises(LLMError) as ctx:
            await structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_UNAVAILABLE)
        self.assertEqual(len(models.calls), 22)

    async def test_all_models_on_daily_quota_gives_the_day_message(self):
        quota_id = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        outcomes = [quota_error(quota_id), quota_error(quota_id)]
        llm, models, _ = make_llm(outcomes, fallbacks=(FALLBACK,))

        with self.assertRaises(LLMError) as ctx:
            await structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_QUOTA_DAY)
        self.assertEqual(len(models.calls), 2)

    async def test_without_fallbacks_nothing_changes(self):
        llm, models, _ = make_llm([api_error(503, "UNAVAILABLE") for _ in range(11)])

        with self.assertRaises(LLMError):
            await structured(llm)

        self.assertEqual({call["model"] for call in models.calls}, {MODEL})

    async def test_auth_error_does_not_switch_models(self):
        llm, models, _ = make_llm([api_error(403, "PERMISSION_DENIED")], fallbacks=(FALLBACK,))

        with self.assertRaises(LLMError) as ctx:
            await structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_CONFIG)
        self.assertEqual(len(models.calls), 1)

    async def test_stream_also_switches_models(self):
        outcomes = [api_error(503, "UNAVAILABLE") for _ in range(11)] + [stream_chunks("a")]
        llm, models, _ = make_llm(outcomes, fallbacks=(FALLBACK,))

        self.assertEqual(await collect_stream(llm), ["a"])
        self.assertEqual(models.calls[-1]["model"], FALLBACK)

    def test_rotation_ignores_duplicates_of_the_primary(self):
        rotation = ModelRotation(MODEL, (MODEL, FALLBACK, FALLBACK))

        self.assertEqual(rotation.chain, [MODEL, FALLBACK])

    def test_default_fallbacks_come_from_settings(self):
        with override_settings(GEMINI_FALLBACK_MODELS=["m-b", "m-c"]):
            llm = GeminiLLM(client=object(), model="m-a", limiter=RateLimiter(8))

        self.assertEqual(llm._rotation.chain, ["m-a", "m-b", "m-c"])


class RateLimiterTests(SimpleTestCase):
    async def test_concurrent_calls_start_at_least_interval_apart(self):
        llm, models, clock = make_llm([response() for _ in range(5)], rpm=8)

        await asyncio.gather(*(structured(llm) for _ in range(5)))

        gaps = [b - a for a, b in zip(models.starts, models.starts[1:], strict=False)]
        self.assertEqual(len(models.starts), 5)
        self.assertTrue(all(gap >= 60 / 8 - 1e-9 for gap in gaps), gaps)

    async def test_limit_follows_rpm(self):
        llm, models, _ = make_llm([response() for _ in range(3)], rpm=2)

        await asyncio.gather(*(structured(llm) for _ in range(3)))

        gaps = [b - a for a, b in zip(models.starts, models.starts[1:], strict=False)]
        self.assertTrue(all(gap >= 30 - 1e-9 for gap in gaps), gaps)

    async def test_retries_also_count_as_starts(self):
        llm, models, _ = make_llm([quota_error(retry_delay="1s"), response()], rpm=8)

        await structured(llm)

        self.assertGreaterEqual(models.starts[1] - models.starts[0], 7.5 - 1e-9)

    def test_limit_holds_across_event_loops(self):
        clock = FakeClock()
        limiter = RateLimiter(8, clock=clock, sleep=clock.gate)
        starts = []

        async def one():
            await limiter.wait_turn()
            starts.append(clock())

        asyncio.run(one())
        asyncio.run(one())

        self.assertGreaterEqual(starts[1] - starts[0], 7.5 - 1e-9)

    def test_first_call_does_not_wait(self):
        clock = FakeClock()
        limiter = RateLimiter(8, clock=clock, sleep=clock.gate)

        asyncio.run(limiter.wait_turn())

        self.assertEqual(clock.gate_waits, [])

    def test_shared_limiter_is_one_per_process_and_follows_settings(self):
        self.assertIs(llm_gemini.shared_limiter(), llm_gemini.shared_limiter())
        self.assertEqual(llm_gemini.shared_limiter().rpm, settings.GEMINI_RPM)


def stream_chunks(*texts, finish=types.FinishReason.STOP, prompt=11, out=6):
    chunks = [response(text=text, finish=None, prompt=None, out=None) for text in texts]
    chunks[-1] = response(text=texts[-1], finish=finish, prompt=prompt, out=out)
    return chunks


class StreamTextTests(SimpleTestCase):
    async def collect(self, llm):
        return [
            piece
            async for piece in llm.stream_text(
                step="respond", system="s", user="u", effort="low", max_tokens=4000
            )
        ]

    async def test_pieces_arrive_in_order_and_usage_is_logged(self):
        llm, models, _ = make_llm([stream_chunks("Mer", "ha", "ba")])
        tally = UsageTally()
        token = usage_tally.set(tally)
        try:
            with self.assertLogs("apps.agent.services.llm_gemini", level="INFO") as logs:
                pieces = await self.collect(llm)
        finally:
            usage_tally.reset(token)

        self.assertEqual(pieces, ["Mer", "ha", "ba"])
        config = models.calls[0]["config"]
        self.assertEqual(config.system_instruction, "s")
        self.assertEqual(config.thinking_config.thinking_level, types.ThinkingLevel.MINIMAL)
        self.assertIsNone(config.response_mime_type)
        self.assertEqual(config.max_output_tokens, 4000 + llm_gemini.THINKING_TOKEN_PAD)
        self.assertIn(f"llm step=respond model={MODEL} in=11 out=6 stop=STOP", logs.output[0])
        self.assertNotIn("Mer", logs.output[0])
        self.assertEqual((tally.input_tokens, tally.output_tokens, tally.calls), (11, 6, 1))

    async def test_429_before_first_piece_is_retried(self):
        llm, models, clock = make_llm([quota_error(), stream_chunks("a", "b")])

        pieces = await self.collect(llm)

        self.assertEqual(pieces, ["a", "b"])
        self.assertEqual(clock.waits, [20])
        self.assertEqual(len(models.calls), 2)

    async def test_429_raised_by_the_first_read_is_retried(self):
        llm, models, clock = make_llm([[quota_error()], stream_chunks("a")])

        pieces = await self.collect(llm)

        self.assertEqual(pieces, ["a"])
        self.assertEqual(len(models.calls), 2)

    async def test_truncated_stream_is_an_error_after_the_text(self):
        llm, _, _ = make_llm([stream_chunks("a", finish=types.FinishReason.MAX_TOKENS)])
        pieces = []

        with self.assertRaises(LLMError) as ctx:
            async for piece in llm.stream_text(
                step="respond", system="s", user="u", effort="low", max_tokens=4000
            ):
                pieces.append(piece)

        self.assertEqual(pieces, ["a"])
        self.assertEqual(ctx.exception.message, llm_module.MSG_TRUNCATED)

    async def test_blocked_stream_is_refused(self):
        chunks = [response(text=None, finish=types.FinishReason.SAFETY)]
        llm, _, _ = make_llm([chunks])

        with self.assertRaises(LLMError) as ctx:
            await self.collect(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_REFUSED)

    async def test_auth_error_is_a_config_error(self):
        llm, _, _ = make_llm([api_error(403, "PERMISSION_DENIED")])

        with self.assertRaises(LLMError) as ctx:
            await self.collect(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_CONFIG)

    async def test_429_in_the_middle_of_the_stream_maps_to_the_quota_message(self):
        quota_id = "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
        first = response(text="a", finish=None, prompt=None, out=None)
        llm, _, _ = make_llm([[first, quota_error(quota_id)]])
        pieces = []

        with self.assertRaises(LLMError) as ctx:
            async for piece in llm.stream_text(
                step="respond", system="s", user="u", effort="low", max_tokens=4000
            ):
                pieces.append(piece)

        self.assertEqual(pieces, ["a"])
        self.assertEqual(ctx.exception.message, llm_module.MSG_QUOTA_MINUTE)

    async def test_unknown_429_in_the_middle_of_the_stream_gives_the_general_quota_message(self):
        first = response(text="a", finish=None, prompt=None, out=None)
        llm, _, _ = make_llm([[first, quota_error()]])

        with self.assertRaises(LLMError) as ctx:
            await self.collect(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_QUOTA)

    async def test_server_error_in_the_middle_of_the_stream_is_unavailable(self):
        first = response(text="a", finish=None, prompt=None, out=None)
        llm, _, _ = make_llm([[first, api_error(503, "UNAVAILABLE")]])

        with self.assertRaises(LLMError) as ctx:
            await self.collect(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_UNAVAILABLE)


@override_settings(LLM_PROVIDER="gemini")
class BuildLlmGeminiTests(SimpleTestCase):
    def test_gemini_provider_builds_gemini_llm(self):
        self.assertIsInstance(llm_module.build_llm(), GeminiLLM)


class BuildLlmTests(SimpleTestCase):
    @override_settings(LLM_PROVIDER="anthropic")
    def test_anthropic_provider_builds_anthropic_llm(self):
        self.assertIsInstance(llm_module.build_llm(), llm_module.AnthropicLLM)
