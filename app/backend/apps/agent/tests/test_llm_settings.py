import os
import runpy
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

LLM_ENV = ("LLM_PROVIDER", "GEMINI_MODEL", "GEMINI_RPM", "GEMINI_FALLBACK_MODELS")


def load_base(**env) -> dict:
    """Ayar dosyasını verilen ortamla yeniden çalıştırır (django.conf.settings etkilenmez)."""
    clean = {key: value for key, value in os.environ.items() if key not in LLM_ENV}
    clean.update(env)
    with mock.patch.dict(os.environ, clean, clear=True):
        return runpy.run_path(str(Path(settings.BASE_DIR) / "config/settings/base.py"))


def agent_value(ns: dict, key: str, provider: str):
    """Ayar tablosundan sağlayıcıya göre AGENT değeri (çalışma anındaki seçimle aynı kural)."""
    return ns["AGENT_PROVIDER_OVERRIDES"].get(provider, {}).get(key, ns["AGENT"][key])


class LlmSettingsTests(SimpleTestCase):
    def test_defaults_keep_claude_and_safe_gemini_values(self):
        ns = load_base()

        self.assertEqual(ns["LLM_PROVIDER"], "anthropic")
        self.assertEqual(ns["GEMINI_MODEL"], "gemini-3.5-flash-lite")
        self.assertEqual(ns["GEMINI_RPM"], 8)

    def test_empty_values_fall_back_to_defaults(self):
        ns = load_base(LLM_PROVIDER="", GEMINI_MODEL="", GEMINI_RPM="")

        self.assertEqual(ns["LLM_PROVIDER"], "anthropic")
        self.assertEqual(ns["GEMINI_MODEL"], "gemini-3.5-flash-lite")
        self.assertEqual(ns["GEMINI_RPM"], 8)

    def test_values_come_from_the_environment(self):
        ns = load_base(LLM_PROVIDER="gemini", GEMINI_MODEL="gemini-x", GEMINI_RPM="4")

        self.assertEqual(ns["LLM_PROVIDER"], "gemini")
        self.assertEqual(ns["GEMINI_MODEL"], "gemini-x")
        self.assertEqual(ns["GEMINI_RPM"], 4)

    def test_unknown_provider_fails_at_startup_and_lists_the_valid_ones(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load_base(LLM_PROVIDER="openai")

        self.assertIn("anthropic", str(ctx.exception))
        self.assertIn("gemini", str(ctx.exception))

    def test_rpm_below_one_or_not_a_number_fails_at_startup(self):
        for value in ("0", "-3", "sekiz"):
            with self.subTest(value=value):
                with self.assertRaises(ImproperlyConfigured):
                    load_base(GEMINI_RPM=value)

    def test_fallback_models_default_to_empty(self):
        for value in (None, "", " , ,"):
            with self.subTest(value=value):
                ns = load_base() if value is None else load_base(GEMINI_FALLBACK_MODELS=value)

                self.assertEqual(ns["GEMINI_FALLBACK_MODELS"], [])

    def test_fallback_models_come_from_a_comma_separated_list(self):
        ns = load_base(GEMINI_FALLBACK_MODELS=" gemini-a , gemini-b,,")

        self.assertEqual(ns["GEMINI_FALLBACK_MODELS"], ["gemini-a", "gemini-b"])

    def test_gemini_writes_one_film_per_call_and_claude_keeps_four(self):
        # Gemini'nin PROHIBITED_CONTENT engeli iki filmin metni bir aradayken çıkabiliyor;
        # tek filmlik gerekçe çağrısı bunu önler. Claude yolu değişmez.
        ns = load_base()
        self.assertEqual(ns["AGENT"]["write_chunk"], 4)
        self.assertEqual(agent_value(ns, "write_chunk", "anthropic"), 4)
        self.assertEqual(agent_value(ns, "write_chunk", "gemini"), 1)
        # Ortamdaki varsayılan sağlayıcı AGENT'i değiştirmez: seçim çalışma anında yapılır.
        self.assertEqual(load_base(LLM_PROVIDER="gemini")["AGENT"]["write_chunk"], 4)

    def test_skip_refused_is_on_only_for_gemini(self):
        # Reddedilen film / aday kümesi yalnız Gemini'de atlanır; Claude yolu değişmez.
        ns = load_base()
        self.assertIs(ns["AGENT"]["skip_refused"], False)
        self.assertIs(agent_value(ns, "skip_refused", "anthropic"), False)
        self.assertIs(agent_value(ns, "skip_refused", "gemini"), True)

    def test_api_key_never_enters_settings(self):
        ns = load_base(GEMINI_API_KEY="sahte-test-anahtari")

        self.assertNotIn("sahte-test-anahtari", repr({k: v for k, v in ns.items() if k.isupper()}))
