import threading
import time
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.search.services import neural, warmup
from apps.search.tests.base import fake_models, make_film, override_search, search_settings


class WarmSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_film("Q1", word="dream")
        make_film("Q2", word="ocean")

    def test_warm_search_loads_everything_and_runs_a_dummy_search(self):
        with (
            search_settings(),
            fake_models() as scorer,
            mock.patch.object(neural, "get_embedder") as embedder,
            mock.patch.object(neural, "get_reranker") as reranker,
        ):
            timings = warmup.warm_search()
        self.assertEqual(list(timings), ["index", "embed_model", "rerank_model", "dummy_search"])
        embedder.assert_called_once()
        reranker.assert_called_once()
        scorer.assert_called()  # kukla arama yeniden sıralamaya kadar gitti
        self.assertTrue(all(seconds >= 0 for seconds in timings.values()))

    def test_warm_search_command_prints_step_times(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        with (
            search_settings(),
            fake_models(),
            mock.patch.object(neural, "get_embedder"),
            mock.patch.object(neural, "get_reranker"),
        ):
            call_command("warm_search", stdout=out)
        for step in ("index", "embed_model", "rerank_model", "dummy_search"):
            self.assertIn(f"{step}:", out.getvalue())


class BackgroundWarmupTests(SimpleTestCase):
    def test_does_nothing_when_warmup_is_off(self):
        with (
            override_search(warmup=False),
            mock.patch.object(warmup, "start_background_warmup") as start,
        ):
            self.assertIsNone(warmup.maybe_start_warmup())
        start.assert_not_called()

    def test_enabled_runs_in_a_separate_thread_and_logs_ready(self):
        with (
            override_search(warmup=True),
            mock.patch.object(warmup, "warm_search", return_value={}) as warm,
            self.assertLogs("apps.search.services.warmup", level="INFO") as logs,
        ):
            thread = warmup.maybe_start_warmup()
            thread.join(5)
        self.assertNotEqual(thread.ident, threading.get_ident())
        warm.assert_called_once()
        self.assertTrue(any("Arama hazır" in line for line in logs.output))

    def test_failure_is_logged_and_does_not_raise(self):
        with (
            mock.patch.object(warmup, "warm_search", side_effect=RuntimeError("disk yok")),
            self.assertLogs("apps.search.services.warmup", level="ERROR") as logs,
        ):
            warmup.start_background_warmup().join(5)
        self.assertIn("başarısız", logs.output[0])

    def test_search_during_warmup_waits_on_the_load_lock_instead_of_loading_twice(self):
        loads = []

        def slow_load():
            loads.append(1)
            time.sleep(0.2)
            return object()

        with (
            mock.patch.object(neural, "_load_embedder", side_effect=slow_load),
            mock.patch.object(neural, "_embedder", None),
        ):
            warm_thread = threading.Thread(target=neural.get_embedder)
            request_thread = threading.Thread(target=neural.get_embedder)
            warm_thread.start()
            time.sleep(0.05)  # istek, ısındırma yüklerken gelir
            request_thread.start()
            warm_thread.join()
            request_thread.join()
        self.assertEqual(len(loads), 1)
