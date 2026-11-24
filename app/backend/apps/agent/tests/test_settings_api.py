import json
import logging
import os
from unittest import mock

from django.test import Client, TestCase, override_settings

from apps.agent.models import LLMSettings
from apps.agent.services import llm_config, llm_probe
from apps.agent.services.llm import MSG_UNAVAILABLE, LLMError
from apps.chats.tests.base import make_user

URL = "/api/settings/llm"
TEST_URL = "/api/settings/llm/test"
ANTHROPIC_KEY = "sk-ant-sahte-test-anahtari-0001abcd"
GEMINI_KEY = "sahte-gemini-anahtari-0002wxyz"


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class SettingsApiTestCase(TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        llm_config.invalidate()
        self.addCleanup(llm_config.invalidate)
        self.client = Client(enforce_csrf_checks=True)
        self.user = make_user("editor")
        self.logs = ListHandler()
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(self.logs)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.setLevel, previous_level)
        self.addCleanup(root.removeHandler, self.logs)

    def csrf(self) -> dict:
        self.client.get("/api/auth/me")
        return {"HTTP_X_CSRFTOKEN": self.client.cookies["csrftoken"].value}

    def login(self):
        self.client.force_login(self.user)

    def put(self, body: dict, headers: dict | None = None):
        headers = self.csrf() if headers is None else headers
        return self.client.put(
            URL, data=json.dumps(body), content_type="application/json", **headers
        )

    def post_test(self):
        return self.client.post(TEST_URL, content_type="application/json", **self.csrf())

    def assert_error(self, response, status: int, code: str):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.json()["code"], code)
        self.assertIsInstance(response.json()["detail"], str)

    def assert_key_never_leaked(self, response, *keys):
        text = response.content.decode() + "\n".join(self.logs.lines)
        for key in keys:
            self.assertNotIn(key, text)


class AuthenticationTests(SettingsApiTestCase):
    def test_anonymous_requests_get_401(self):
        self.assert_error(self.client.get(URL), 401, "not_authenticated")
        self.assert_error(self.put({"provider": "ollama"}), 401, "not_authenticated")
        self.assert_error(self.post_test(), 401, "not_authenticated")

    def test_writing_without_a_csrf_token_is_forbidden(self):
        self.login()

        response = self.client.put(
            URL, data=json.dumps({"provider": "ollama"}), content_type="application/json"
        )

        self.assert_error(response, 403, "forbidden")
        self.assertFalse(LLMSettings.objects.exists())


class GetSettingsTests(SettingsApiTestCase):
    def test_environment_defaults_have_the_agreed_shape(self):
        self.login()

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"provider", "source", "anthropic", "gemini", "ollama"})
        self.assertEqual(body["source"], "env")
        self.assertEqual(body["anthropic"]["configured"], False)
        self.assertIsNone(body["anthropic"]["key_hint"])
        self.assertEqual(set(body["anthropic"]), {"configured", "key_hint", "model"})
        self.assertEqual(set(body["ollama"]), {"base_url", "model"})

    def test_environment_key_shows_only_a_hint(self):
        self.login()

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": GEMINI_KEY}):
            response = self.client.get(URL)

        self.assertTrue(response.json()["gemini"]["configured"])
        self.assertEqual(response.json()["gemini"]["key_hint"], "…wxyz")
        self.assert_key_never_leaked(response, GEMINI_KEY)


class PutSettingsTests(SettingsApiTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_saving_a_key_returns_the_new_state_and_get_agrees(self):
        response = self.put({"provider": "gemini", "gemini_api_key": GEMINI_KEY})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["provider"], "gemini")
        self.assertEqual(body["source"], "saved")
        self.assertEqual(body["gemini"]["configured"], True)
        self.assertEqual(body["gemini"]["key_hint"], "…wxyz")
        self.assertEqual(self.client.get(URL).json(), body)
        self.assert_key_never_leaked(response, GEMINI_KEY)
        row = LLMSettings.objects.get(pk=1)
        self.assertEqual(row.updated_by, self.user)
        self.assertNotIn(GEMINI_KEY, row.gemini_api_key)

    def test_omitted_or_blank_key_keeps_the_saved_one(self):
        self.put({"provider": "gemini", "gemini_api_key": GEMINI_KEY})

        self.put({"provider": "ollama", "ollama_model": "model-x", "gemini_api_key": ""})
        response = self.put({"provider": "gemini"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["gemini"]["key_hint"], "…wxyz")
        self.assertEqual(response.json()["ollama"]["model"], "model-x")

    def test_provider_without_a_key_is_400_missing_key(self):
        response = self.put({"provider": "anthropic"})

        self.assert_error(response, 400, "missing_key")
        self.assertFalse(LLMSettings.objects.exists())

    def test_key_from_the_environment_is_enough(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ANTHROPIC_KEY}):
            response = self.put({"provider": "anthropic"})

        self.assertEqual(response.status_code, 200)

    def test_keys_that_do_not_match_a_known_shape_are_still_saved(self):
        odd = "baska-bicimde-gecerli-anahtar-12345"

        response = self.put({"provider": "anthropic", "anthropic_api_key": f"  {odd} "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["anthropic"]["key_hint"], "…2345")
        self.assertEqual(llm_config.get_effective().anthropic_key, odd)

    def test_gemini_key_shapes_are_saved(self):
        for key in ("AIza" + "Sy" * 18, "AQ." + "Ab1-_" * 8):
            with self.subTest(key=key[:4]):
                response = self.put({"provider": "gemini", "gemini_api_key": key})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(llm_config.get_effective().gemini_key, key)

    def test_broken_keys_are_400_invalid_key_without_echoing_them(self):
        for key in ("kisa", "bosluk iceren anahtar 1234567890", "y" * 301):
            with self.subTest(key=key[:8]):
                response = self.put({"provider": "gemini", "gemini_api_key": key})

                self.assert_error(response, 400, "invalid_key")
                self.assert_key_never_leaked(response, key)

    def test_ollama_address_must_be_http_or_https(self):
        bad = self.put({"provider": "ollama", "ollama_base_url": "ftp://yerel:11434"})
        good = self.put({"provider": "ollama", "ollama_base_url": "http://yerel:11434/"})

        self.assert_error(bad, 400, "invalid_url")
        self.assertEqual(good.json()["ollama"]["base_url"], "http://yerel:11434")

    def test_unknown_provider_is_a_validation_error(self):
        self.assert_error(self.put({"provider": "openai"}), 422, "validation_error")
        self.assert_error(self.put({}), 422, "validation_error")

    def test_next_request_uses_the_new_setting_without_restart(self):
        self.put({"provider": "ollama", "ollama_model": "model-x"})
        self.assertEqual(llm_config.agent_option("max_concurrent_calls"), 1)

        self.put({"provider": "gemini", "gemini_api_key": GEMINI_KEY})

        self.assertEqual(llm_config.agent_option("write_chunk"), 1)
        self.assertEqual(llm_config.get_effective().provider, "gemini")


class FakeStreamLLM:
    def __init__(self, error: Exception | None = None):
        self.error = error

    async def stream_text(self, **kwargs):
        if self.error:
            raise self.error
        yield "tamam"


class ConnectionTestTests(SettingsApiTestCase):
    def setUp(self):
        super().setUp()
        self.login()
        self.put({"provider": "gemini", "gemini_api_key": GEMINI_KEY})

    def probe_with(self, llm):
        with mock.patch.object(llm_probe, "build_llm", return_value=llm) as build:
            response = self.post_test()
        self.assertEqual(build.call_args.args[0].provider, "gemini")
        return response

    def test_success_returns_ok_and_seconds_only(self):
        response = self.probe_with(FakeStreamLLM())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"ok", "seconds"})
        self.assertIs(body["ok"], True)
        self.assertIsInstance(body["seconds"], float)

    def test_model_error_becomes_a_readable_message(self):
        response = self.probe_with(FakeStreamLLM(LLMError(MSG_UNAVAILABLE)))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": False, "message": MSG_UNAVAILABLE})

    def test_unexpected_error_text_and_key_never_reach_the_client_or_the_logs(self):
        raw = RuntimeError(f"401 hatalı anahtar {GEMINI_KEY} ham sağlayıcı cevabı")

        response = self.probe_with(FakeStreamLLM(raw))

        self.assertEqual(response.json(), {"ok": False, "message": llm_probe.MSG_FAILED})
        self.assert_key_never_leaked(response, GEMINI_KEY, "ham sağlayıcı cevabı")

    def test_missing_key_is_reported_without_calling_the_provider(self):
        LLMSettings.objects.all().delete()
        llm_config.invalidate()
        with (
            mock.patch.object(llm_probe, "build_llm") as build,
            override_settings(LLM_PROVIDER="anthropic"),
        ):
            response = self.post_test()

        build.assert_not_called()
        self.assertIs(response.json()["ok"], False)
        self.assertIn("anahtar", response.json()["message"])
