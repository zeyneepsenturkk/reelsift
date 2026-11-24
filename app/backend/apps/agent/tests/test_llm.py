from types import SimpleNamespace

import anthropic
import httpx2
from django.conf import settings
from django.test import SimpleTestCase

from apps.agent.schemas import AltQueryOutput
from apps.agent.services import llm as llm_module
from apps.agent.services.llm import AnthropicLLM, LLMError, UsageTally, usage_tally


def reply(stop_reason="end_turn", parsed=None, input_tokens=10, output_tokens=5):
    return SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=parsed,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class FakeMessages:
    def __init__(self, result=None, error=None, pieces=()):
        self.result = result
        self.error = error
        self.pieces = pieces
        self.kwargs = None

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result

    def stream(self, **kwargs):
        self.kwargs = kwargs
        return FakeStream(self)


class FakeStream:
    def __init__(self, messages: FakeMessages):
        self.messages = messages

    async def __aenter__(self):
        if self.messages.error:
            raise self.messages.error
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def generate():
            for piece in self.messages.pieces:
                yield piece

        return generate()

    async def get_final_message(self):
        return self.messages.result


def make_llm(messages) -> AnthropicLLM:
    return AnthropicLLM(client=SimpleNamespace(messages=messages), model="claude-haiku-5-5")


def request_error():
    return httpx2.Request("POST", "https://api.anthropic.test/v1/messages")


class StructuredCallTests(SimpleTestCase):
    async def call(self, messages):
        return await make_llm(messages).structured(
            step="parse",
            system="sistem",
            user="kullanıcı",
            output=AltQueryOutput,
            effort="low",
            max_tokens=4000,
        )

    async def test_request_uses_model_effort_and_structured_output_only(self):
        parsed = AltQueryOutput(en_query="a", hyde="b")
        messages = FakeMessages(reply(parsed=parsed))

        result = await self.call(messages)

        self.assertIs(result, parsed)
        kwargs = messages.kwargs
        self.assertEqual(kwargs["model"], "claude-haiku-5-5")
        self.assertEqual(kwargs["output_config"], {"effort": "low"})
        self.assertIs(kwargs["output_format"], AltQueryOutput)
        self.assertEqual(kwargs["max_tokens"], 4000)
        for forbidden in ("temperature", "top_p", "top_k", "thinking", "tool_choice"):
            self.assertNotIn(forbidden, kwargs)
        self.assertEqual(kwargs["messages"], [{"role": "user", "content": "kullanıcı"}])

    async def test_max_tokens_and_refusal_are_errors_with_plain_messages(self):
        for stop, message in (
            ("max_tokens", llm_module.MSG_TRUNCATED),
            ("refusal", llm_module.MSG_REFUSED),
        ):
            with self.subTest(stop=stop):
                with self.assertRaises(LLMError) as ctx:
                    await self.call(FakeMessages(reply(stop_reason=stop)))
                self.assertEqual(ctx.exception.message, message)
                self.assertEqual(ctx.exception.code, "model_error")
                # Yalnız ret ayrı işaret taşır (graf `skip_refused` kararını bundan verir).
                self.assertEqual(
                    isinstance(ctx.exception, llm_module.LLMRefused), stop == "refusal"
                )

    async def test_missing_parsed_output_is_an_error(self):
        with self.assertRaises(LLMError):
            await self.call(FakeMessages(reply(parsed=None)))

    async def test_unparseable_output_is_a_plain_error(self):
        with self.assertRaises(LLMError) as ctx:
            await self.call(FakeMessages(error=ValueError("1 validation error ... secret")))

        self.assertEqual(ctx.exception.message, llm_module.MSG_BAD_OUTPUT)
        self.assertNotIn("secret", ctx.exception.message)

    async def test_api_errors_become_plain_messages_without_raw_text(self):
        request = request_error()
        errors = [
            (
                llm_module.MSG_UNAVAILABLE,
                anthropic.APIConnectionError(
                    message="connection refused sk-ant-secret", request=request
                ),
            ),
            (
                llm_module.MSG_BUSY,
                anthropic.RateLimitError(
                    "rate limited sk-ant-secret",
                    response=httpx2.Response(429, request=request),
                    body=None,
                ),
            ),
            (
                llm_module.MSG_CONFIG,
                anthropic.AuthenticationError(
                    "invalid x-api-key sk-ant-secret",
                    response=httpx2.Response(401, request=request),
                    body=None,
                ),
            ),
            (
                llm_module.MSG_UNAVAILABLE,
                anthropic.InternalServerError(
                    "boom sk-ant-secret", response=httpx2.Response(500, request=request), body=None
                ),
            ),
        ]
        for expected, error in errors:
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(LLMError) as ctx:
                    await self.call(FakeMessages(error=error))
                self.assertEqual(ctx.exception.message, expected)
                self.assertNotIn("sk-ant", ctx.exception.message)

    async def test_usage_is_tallied_per_turn_without_text(self):
        tally = UsageTally()
        token = usage_tally.set(tally)
        try:
            await self.call(FakeMessages(reply(parsed=AltQueryOutput(en_query="a", hyde="b"))))
        finally:
            usage_tally.reset(token)

        self.assertEqual((tally.input_tokens, tally.output_tokens, tally.calls), (10, 5, 1))
        self.assertIn("parse", tally.by_step)

    def test_default_model_comes_from_settings(self):
        self.assertEqual(AnthropicLLM(client=object()).model, settings.ANTHROPIC_MODEL)


class StreamTextTests(SimpleTestCase):
    async def collect(self, messages):
        llm = make_llm(messages)
        return [
            piece
            async for piece in llm.stream_text(
                step="respond", system="s", user="u", effort="low", max_tokens=4000
            )
        ]

    async def test_yields_text_deltas_and_sends_effort(self):
        messages = FakeMessages(reply(), pieces=["Mer", "haba"])

        pieces = await self.collect(messages)

        self.assertEqual(pieces, ["Mer", "haba"])
        self.assertEqual(messages.kwargs["output_config"], {"effort": "low"})
        for forbidden in ("temperature", "thinking", "tool_choice"):
            self.assertNotIn(forbidden, messages.kwargs)

    async def test_truncated_stream_is_an_error_after_the_text(self):
        with self.assertRaises(LLMError) as ctx:
            await self.collect(FakeMessages(reply(stop_reason="max_tokens"), pieces=["a"]))

        self.assertEqual(ctx.exception.message, llm_module.MSG_TRUNCATED)

    async def test_connection_error_is_plain(self):
        error = anthropic.APIConnectionError(message="x", request=request_error())

        with self.assertRaises(LLMError) as ctx:
            await self.collect(FakeMessages(error=error))

        self.assertEqual(ctx.exception.message, llm_module.MSG_UNAVAILABLE)
