import os
from dataclasses import replace
from unittest import mock

from asgiref.sync import sync_to_async
from django.conf import settings
from django.test import TestCase, override_settings

from apps.agent.models import LLMSettings
from apps.agent.services import llm as llm_module
from apps.agent.services import llm_config
from apps.agent.services.llm_gemini import GeminiLLM
from apps.agent.services.llm_ollama import OllamaLLM
from apps.chats.tests.base import make_user
from apps.core.exceptions import ServiceError

ANTHROPIC_KEY = "sk-ant-sahte-test-anahtari-0001abcd"
GEMINI_KEY = "sahte-gemini-anahtari-0002wxyz"
ENV_ANTHROPIC_KEY = "sk-ant-ortam-sahte-anahtar-9999env1"


class ConfigTestCase(TestCase):
    """Ortamdaki gerçek anahtarlar karışmasın: anahtar ortamı boşaltılır, önbellek temizlenir."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        llm_config.invalidate()
        self.addCleanup(llm_config.invalidate)
        self.user = make_user("editor")

    def save(self, **kwargs):
        kwargs.setdefault("provider", "anthropic")
        return llm_config.save_settings(self.user, **kwargs)


class EncryptionTests(ConfigTestCase):
    def test_round_trip_and_ciphertext_differs_from_plain_text(self):
        token = llm_config.encrypt_secret(ANTHROPIC_KEY)

        self.assertNotIn(ANTHROPIC_KEY, token)
        self.assertEqual(llm_config.decrypt_secret(token), ANTHROPIC_KEY)

    def test_empty_stays_empty(self):
        self.assertEqual(llm_config.encrypt_secret(""), "")
        self.assertEqual(llm_config.decrypt_secret(""), "")

    def test_garbage_is_not_registered_instead_of_raising(self):
        self.assertEqual(llm_config.decrypt_secret("bu-bir-sifreli-deger-degil"), "")

    def test_value_encrypted_under_another_secret_key_is_not_registered(self):
        token = llm_config.encrypt_secret(ANTHROPIC_KEY)

        with override_settings(SECRET_KEY="baska-bir-gizli-anahtar"):
            self.assertEqual(llm_config.decrypt_secret(token), "")

    def test_database_row_holds_no_plain_text_key(self):
        self.save(anthropic_api_key=ANTHROPIC_KEY)

        row = LLMSettings.objects.get(pk=1)
        self.assertNotIn(ANTHROPIC_KEY, row.anthropic_api_key)
        self.assertTrue(row.anthropic_api_key)

    def test_unreadable_saved_key_counts_as_not_configured(self):
        self.save(anthropic_api_key=ANTHROPIC_KEY)
        llm_config.invalidate()

        with override_settings(SECRET_KEY="baska-bir-gizli-anahtar"):
            config = llm_config.get_effective()

        self.assertEqual(config.anthropic_key, "")
        self.assertFalse(llm_config.serialize(config)["anthropic"]["configured"])


class EffectiveConfigTests(ConfigTestCase):
    @override_settings(LLM_PROVIDER="gemini")
    def test_without_a_saved_row_the_environment_decides(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": GEMINI_KEY}):
            config = llm_config.get_effective()

        self.assertEqual(config.provider, "gemini")
        self.assertEqual(config.source, "env")
        self.assertEqual(config.gemini_key, GEMINI_KEY)
        self.assertEqual(config.ollama_base_url, settings.OLLAMA_BASE_URL)

    @override_settings(LLM_PROVIDER="gemini")
    def test_saved_row_overrides_the_environment(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ENV_ANTHROPIC_KEY}):
            self.save(provider="anthropic", anthropic_api_key=ANTHROPIC_KEY)
            config = llm_config.get_effective()

        self.assertEqual(config.provider, "anthropic")
        self.assertEqual(config.source, "saved")
        self.assertEqual(config.anthropic_key, ANTHROPIC_KEY)

    def test_blank_saved_key_falls_back_to_the_environment_key(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ENV_ANTHROPIC_KEY}):
            self.save(provider="anthropic")
            config = llm_config.get_effective()

        self.assertEqual(config.source, "saved")
        self.assertEqual(config.anthropic_key, ENV_ANTHROPIC_KEY)

    def test_saved_ollama_address_and_model_override_the_environment(self):
        self.save(provider="ollama", ollama_base_url="http://yerel:11434/", ollama_model="model-x")

        config = llm_config.get_effective()

        self.assertEqual(config.ollama_base_url, "http://yerel:11434")
        self.assertEqual(config.ollama_model, "model-x")

    def test_keys_never_show_in_repr_or_str(self):
        self.save(anthropic_api_key=ANTHROPIC_KEY, gemini_api_key=GEMINI_KEY)
        config = llm_config.get_effective()
        row = LLMSettings.objects.get(pk=1)

        for text in (repr(config), str(config), repr(row), str(row)):
            self.assertNotIn(ANTHROPIC_KEY, text)
            self.assertNotIn(GEMINI_KEY, text)

    def test_serialized_view_has_only_a_hint_of_the_key(self):
        self.save(anthropic_api_key=ANTHROPIC_KEY)

        view = llm_config.serialize(llm_config.get_effective())

        self.assertEqual(view["anthropic"]["key_hint"], "…abcd")
        self.assertTrue(view["anthropic"]["configured"])
        self.assertNotIn(ANTHROPIC_KEY, repr(view))

    def test_value_is_cached_between_calls(self):
        llm_config.get_effective()

        with self.assertNumQueries(0):
            llm_config.get_effective()


class KeyValidationTests(ConfigTestCase):
    def test_keys_without_the_known_prefix_are_accepted(self):
        for provider, field in (("anthropic", "anthropic_api_key"), ("gemini", "gemini_api_key")):
            with self.subTest(provider=provider):
                self.save(provider=provider, **{field: "kopyalanan-anahtar-0123456789"})

                self.assertEqual(llm_config.get_effective().provider, provider)

    def test_gemini_key_shapes_are_accepted(self):
        for key in ("AIza" + "x" * 35, "AQ." + "a1b2c3" * 8):
            with self.subTest(key=key[:4]):
                self.save(provider="gemini", gemini_api_key=key)

                self.assertEqual(llm_config.get_effective().gemini_key, key)

    def test_surrounding_whitespace_and_quotes_are_trimmed(self):
        self.save(gemini_api_key=f'  "{GEMINI_KEY}"\n', provider="gemini")

        self.assertEqual(llm_config.get_effective().gemini_key, GEMINI_KEY)

    def test_obviously_broken_keys_are_rejected(self):
        broken = (
            "kisa",
            "x" * 301,
            "icinde bosluk olan anahtar-1234",
            "türkçe-karakter-anahtar-123",
        )
        for key in broken:
            with self.subTest(key=key[:12]):
                with self.assertRaises(ServiceError) as caught:
                    self.save(provider="gemini", gemini_api_key=key)

                self.assertEqual(caught.exception.code, "invalid_key")
                self.assertNotIn(key, caught.exception.message)

    def test_ollama_address_must_be_http_or_https(self):
        for url in ("ftp://yerel:11434", "yerel:11434", "http://", "http://kullanici:sifre@yerel"):
            with self.subTest(url=url):
                with self.assertRaises(ServiceError) as caught:
                    self.save(provider="ollama", ollama_base_url=url)

                self.assertEqual(caught.exception.code, "invalid_url")

    def test_provider_without_any_key_is_missing_key_and_nothing_is_saved(self):
        with self.assertRaises(ServiceError) as caught:
            self.save(provider="gemini")

        self.assertEqual(caught.exception.code, "missing_key")
        self.assertEqual(caught.exception.status_code, 400)
        self.assertFalse(LLMSettings.objects.exists())

    def test_environment_key_satisfies_the_key_requirement(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": GEMINI_KEY}):
            config = self.save(provider="gemini")

        self.assertEqual(config.provider, "gemini")

    def test_blank_key_keeps_the_saved_one(self):
        self.save(provider="gemini", gemini_api_key=GEMINI_KEY)

        self.save(provider="gemini", gemini_api_key="")
        self.save(provider="ollama")
        config = self.save(provider="gemini")

        self.assertEqual(config.gemini_key, GEMINI_KEY)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(ServiceError) as caught:
            self.save(provider="openai")

        self.assertEqual(caught.exception.code, "validation_error")


class AgentOptionTests(ConfigTestCase):
    def test_four_values_follow_the_effective_provider_at_run_time(self):
        expected = {
            "anthropic": (settings.AGENT["write_chunk"], False, 6, 120),
            "gemini": (1, True, 6, 120),
            "ollama": (settings.AGENT["write_chunk"], False, 1, 300),
        }
        for provider, (chunk, skip, concurrent, timeout) in expected.items():
            with self.subTest(provider=provider):
                self.save(
                    provider=provider,
                    anthropic_api_key=ANTHROPIC_KEY,
                    gemini_api_key=GEMINI_KEY,
                )

                self.assertEqual(llm_config.agent_option("write_chunk"), chunk)
                self.assertIs(llm_config.agent_option("skip_refused"), skip)
                self.assertEqual(llm_config.agent_option("max_concurrent_calls"), concurrent)
                self.assertEqual(llm_config.agent_option("request_timeout_s"), timeout)

    @override_settings(LLM_PROVIDER="gemini")
    def test_environment_provider_applies_without_a_saved_row(self):
        self.assertEqual(llm_config.agent_option("write_chunk"), 1)

    def test_other_agent_values_are_untouched(self):
        self.save(provider="ollama")

        self.assertEqual(llm_config.agent_option("judge_chunk"), settings.AGENT["judge_chunk"])


class BuildLlmFollowsTheSettingTests(ConfigTestCase):
    def test_switching_provider_builds_the_new_class(self):
        self.save(provider="anthropic", anthropic_api_key=ANTHROPIC_KEY)
        self.assertIsInstance(llm_module.build_llm(), llm_module.AnthropicLLM)

        self.save(provider="gemini", gemini_api_key=GEMINI_KEY)
        self.assertIsInstance(llm_module.build_llm(), GeminiLLM)

        self.save(provider="ollama", ollama_base_url="http://yerel:11434", ollama_model="m")
        built = llm_module.build_llm()
        self.assertIsInstance(built, OllamaLLM)
        self.assertEqual((built.base_url, built.model), ("http://yerel:11434", "m"))

    def test_saved_keys_reach_the_clients(self):
        self.save(provider="gemini", gemini_api_key=GEMINI_KEY, anthropic_api_key=ANTHROPIC_KEY)

        gemini = llm_module.build_llm()
        anthropic = llm_module.build_llm(replace(llm_config.get_effective(), provider="anthropic"))

        self.assertEqual(gemini._api_key, GEMINI_KEY)
        self.assertEqual(anthropic.client.api_key, ANTHROPIC_KEY)


class SettingsLLMTests(ConfigTestCase):
    async def test_a_changed_setting_builds_a_new_client_on_the_next_call(self):
        llm = llm_module.SettingsLLM()
        await sync_to_async(self.save)(provider="anthropic", anthropic_api_key=ANTHROPIC_KEY)

        first = await llm._current()
        same = await llm._current()
        await sync_to_async(self.save)(provider="gemini", gemini_api_key=GEMINI_KEY)
        second = await llm._current()

        self.assertIsInstance(first, llm_module.AnthropicLLM)
        self.assertIs(first, same)
        self.assertIsInstance(second, GeminiLLM)

    async def test_agent_option_in_the_event_loop_uses_the_last_known_setting(self):
        await sync_to_async(self.save)(provider="gemini", gemini_api_key=GEMINI_KEY)

        self.assertEqual(llm_config.agent_option("write_chunk"), 1)
