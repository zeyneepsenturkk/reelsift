import asyncio
import json

import httpx2
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from apps.agent.schemas import AltQueryOutput
from apps.agent.services import llm as llm_module
from apps.agent.services.llm import LLMError, UsageTally, usage_tally
from apps.agent.services.llm_ollama import (
    MSG_OLLAMA_DOWN,
    MSG_OLLAMA_NO_MODEL,
    OllamaLLM,
)
from apps.agent.tests.test_llm_settings import load_base

VALID = '{"en_query": "a", "hyde": "b"}'
CALL = {"step": "parse", "system": "SYS", "user": "USER", "effort": "low", "max_tokens": 321}


def make_llm(handler) -> OllamaLLM:
    return OllamaLLM(
        base_url="http://ollama.test",
        model="m-test",
        num_ctx=4096,
        transport=httpx2.MockTransport(handler),
    )


def chat_reply(content: str, **extra) -> dict:
    return {
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 11,
        "eval_count": 7,
        **extra,
    }


async def collect(llm: OllamaLLM) -> list[str]:
    return [part async for part in llm.stream_text(**{k: v for k, v in CALL.items()})]


class StructuredTests(SimpleTestCase):
    def run_structured(self, llm):
        return asyncio.run(llm.structured(output=AltQueryOutput, **CALL))

    def test_success_sends_measured_settings_and_validates(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx2.Response(200, json=chat_reply(VALID))

        tally = UsageTally()
        token = usage_tally.set(tally)
        try:
            result = self.run_structured(make_llm(handler))
        finally:
            usage_tally.reset(token)

        self.assertEqual((result.en_query, result.hyde), ("a", "b"))
        body = seen["body"]
        self.assertEqual(seen["url"], "http://ollama.test/api/chat")
        self.assertEqual(body["model"], "m-test")
        self.assertIs(body["stream"], False)
        self.assertEqual(body["format"], AltQueryOutput.model_json_schema())
        self.assertEqual(body["options"], {"temperature": 0, "num_ctx": 4096, "num_predict": 321})
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertTrue(body["messages"][0]["content"].startswith("SYS"))
        self.assertEqual(body["messages"][1], {"role": "user", "content": "USER"})
        self.assertEqual((tally.calls, tally.input_tokens, tally.output_tokens), (1, 11, 7))

    def test_broken_json_becomes_llm_error(self):
        llm = make_llm(lambda r: httpx2.Response(200, json=chat_reply('{"en_query": "a"')))

        with self.assertRaises(LLMError) as ctx:
            self.run_structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_BAD_OUTPUT)

    def test_schema_mismatch_becomes_llm_error(self):
        llm = make_llm(lambda r: httpx2.Response(200, json=chat_reply('{"en_query": 5}')))

        with self.assertRaises(LLMError) as ctx:
            self.run_structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_BAD_OUTPUT)

    def test_cut_off_output_is_truncated_error(self):
        reply = chat_reply(VALID, done_reason="length")
        llm = make_llm(lambda r: httpx2.Response(200, json=reply))

        with self.assertRaises(LLMError) as ctx:
            self.run_structured(llm)

        self.assertEqual(ctx.exception.message, llm_module.MSG_TRUNCATED)

    def test_connection_error_gives_clear_turkish_message(self):
        def handler(request):
            raise httpx2.ConnectError("refused", request=request)

        with self.assertRaises(LLMError) as ctx:
            self.run_structured(make_llm(handler))

        self.assertEqual(ctx.exception.message, MSG_OLLAMA_DOWN)
        self.assertIn("Ollama", ctx.exception.message)

    def test_missing_model_and_server_error(self):
        missing = make_llm(
            lambda r: httpx2.Response(404, json={"error": "model 'm-test' not found"})
        )
        broken = make_llm(lambda r: httpx2.Response(500, json={"error": "boom"}))

        with self.assertRaises(LLMError) as ctx:
            self.run_structured(missing)
        self.assertEqual(ctx.exception.message, MSG_OLLAMA_NO_MODEL)
        with self.assertRaises(LLMError) as ctx:
            self.run_structured(broken)
        self.assertEqual(ctx.exception.message, llm_module.MSG_UNAVAILABLE)


class StreamTests(SimpleTestCase):
    def test_stream_yields_parts_in_order_and_logs_usage(self):
        lines = [
            {"message": {"content": "Mer"}, "done": False},
            {"message": {"content": "haba"}, "done": False},
            chat_reply(""),
        ]
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            return httpx2.Response(200, content="\n".join(json.dumps(x) for x in lines) + "\n")

        tally = UsageTally()
        token = usage_tally.set(tally)
        try:
            parts = asyncio.run(collect(make_llm(handler)))
        finally:
            usage_tally.reset(token)

        self.assertEqual(parts, ["Mer", "haba"])
        self.assertIs(seen["body"]["stream"], True)
        self.assertNotIn("format", seen["body"])
        self.assertEqual(seen["body"]["options"]["num_predict"], 321)
        self.assertEqual((tally.calls, tally.output_tokens), (1, 7))

    def test_stream_connection_error(self):
        def handler(request):
            raise httpx2.ConnectError("refused", request=request)

        with self.assertRaises(LLMError) as ctx:
            asyncio.run(collect(make_llm(handler)))

        self.assertEqual(ctx.exception.message, MSG_OLLAMA_DOWN)

    def test_stream_cut_off_is_truncated_error(self):
        body = json.dumps(chat_reply("x", done_reason="length")) + "\n"
        llm = make_llm(lambda r: httpx2.Response(200, content=body))

        with self.assertRaises(LLMError) as ctx:
            asyncio.run(collect(llm))

        self.assertEqual(ctx.exception.message, llm_module.MSG_TRUNCATED)


class BuildAndSettingsTests(SimpleTestCase):
    @override_settings(LLM_PROVIDER="ollama")
    def test_build_llm_picks_ollama(self):
        self.assertIsInstance(llm_module.build_llm(), OllamaLLM)

    @override_settings(LLM_PROVIDER="anthropic")
    def test_build_llm_default_stays_anthropic(self):
        self.assertIsInstance(llm_module.build_llm(), llm_module.AnthropicLLM)

    def test_defaults_and_ollama_agent_overrides(self):
        ns = load_base()
        self.assertEqual(ns["OLLAMA_BASE_URL"], "http://host.docker.internal:11434")
        self.assertEqual(ns["OLLAMA_MODEL"], "qwen3:4b-instruct-2507-q4_K_M")
        self.assertEqual(ns["OLLAMA_NUM_CTX"], 12288)
        self.assertEqual(ns["AGENT"]["max_concurrent_calls"], 6)

        ns = load_base(LLM_PROVIDER="ollama", OLLAMA_NUM_CTX="8192")
        self.assertEqual(ns["OLLAMA_NUM_CTX"], 8192)
        self.assertEqual(ns["AGENT"]["max_concurrent_calls"], 1)
        self.assertEqual(ns["AGENT"]["request_timeout_s"], 300)

    def test_invalid_provider_and_ctx_fail_at_startup(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load_base(LLM_PROVIDER="openai")
        self.assertIn("ollama", str(ctx.exception))
        with self.assertRaises(ImproperlyConfigured):
            load_base(OLLAMA_NUM_CTX="abc")
        with self.assertRaises(ImproperlyConfigured):
            load_base(OLLAMA_NUM_CTX="0")
