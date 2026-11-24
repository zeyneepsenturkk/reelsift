"""Gerileme: ölçüm komutları süreç içi istemciyle "testserver" adıyla istek gönderir. Test koşusu bu
adı kendiliğinden izinli sayar, komut olarak çalışırken saymaz; `allow_in_process_host()` bunu
kapatır. Burada "testserver" izinli listeden ÇIKARILARAK komutlar gerçek koşudaki gibi sınanır."""

import json
import tempfile
from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path
from unittest import mock

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.agent import runtime, scenarios
from apps.agent.management.commands import evaluate_agent, run_scenarios
from apps.agent.tests.base import FakeLLM, FakeRetrieval
from apps.agent.tests.eval_base import MeteredLLM, write_tone25
from apps.curation.tests.base import make_story_film


class AllowInProcessHostTests(SimpleTestCase):
    @override_settings(ALLOWED_HOSTS=["localhost"])
    def test_testserver_is_allowed_only_inside_the_context_and_setting_is_restored(self):
        self.assertEqual(settings.ALLOWED_HOSTS, ["localhost"])

        with scenarios.allow_in_process_host():
            self.assertEqual(settings.ALLOWED_HOSTS, ["localhost", "testserver"])

        self.assertEqual(settings.ALLOWED_HOSTS, ["localhost"])

    @override_settings(ALLOWED_HOSTS=["localhost"])
    def test_setting_is_restored_when_the_block_fails(self):
        with self.assertRaises(RuntimeError):
            with scenarios.allow_in_process_host():
                raise RuntimeError("boom")

        self.assertEqual(settings.ALLOWED_HOSTS, ["localhost"])


class CommandsWithoutTestserverHostTests(TransactionTestCase):
    """Komutlar kendi olay döngüsünü açtığı için işlemsiz sınanır (gerçek PostgreSQL kaydedici)."""

    def test_run_scenarios_runs_a_turn_when_testserver_is_not_in_allowed_hosts(self):
        films = [make_story_film(number) for number in range(1, 8)]
        llm = FakeLLM()
        retrieval = FakeRetrieval([film.pk for film in films])
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        out = Path(directory.name) / "senaryolar.json"

        @asynccontextmanager
        async def open_with_fakes():
            async with runtime.open_runtime(llm=llm, retrieval=retrieval):
                yield
            # Komutun olay döngüsündeki iş parçacığı bağlantı açar; test veritabanı silinebilsin.
            await sync_to_async(connections.close_all)()

        with (
            override_settings(ALLOWED_HOSTS=["localhost"]),
            mock.patch.object(run_scenarios, "open_runtime", open_with_fakes),
        ):
            self.assertNotIn("testserver", settings.ALLOWED_HOSTS)
            call_command("run_scenarios", "--only", "1", "--output", str(out), stdout=StringIO())

        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([r["status"] for r in report["scenarios"]], ["ok"])
        self.assertEqual(report["scenarios"][0]["film_count"], 7)  # sayı yok: eldeki film sayısı

    def test_evaluate_agent_runs_a_request_when_testserver_is_not_in_allowed_hosts(self):
        films = [make_story_film(n) for n in range(1, 6)]
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        write_tone25(root)
        retrieval = FakeRetrieval([film.pk for film in films])
        out = root / "sonuc" / "run.json"

        with (
            override_settings(
                ALLOWED_HOSTS=["localhost"],
                SEARCH={**settings.SEARCH, "eval_data_dir": str(root)},
            ),
            mock.patch.object(evaluate_agent, "build_llm", lambda model: MeteredLLM()),
            mock.patch.object(evaluate_agent, "build_retrieval", lambda: retrieval),
        ):
            self.assertNotIn("testserver", settings.ALLOWED_HOSTS)
            call_command(
                "evaluate_agent",
                "--set", "tone25",
                "--sample", "1",
                "--model", "claude-sonnet-5-5",
                "--out", str(out),
                stdout=StringIO(),
                stderr=StringIO(),
            )  # fmt: skip

        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual({r["status"] for r in report["requests"].values()}, {"ok"})
