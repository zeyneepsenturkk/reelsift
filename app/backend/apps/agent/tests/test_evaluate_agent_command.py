import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.agent.management.commands import evaluate_agent
from apps.agent.tests.base import FakeRetrieval
from apps.agent.tests.eval_base import MeteredLLM, write_known50, write_konu30, write_tone25
from apps.chats.models import Chat
from apps.curation.models import Collection
from apps.curation.tests.base import make_story_film


def run_command(*args):
    stdout, stderr = StringIO(), StringIO()
    call_command("evaluate_agent", *args, stdout=stdout, stderr=stderr)
    return stdout.getvalue(), stderr.getvalue()


class CommandArgumentTests(SimpleTestCase):
    def test_a_set_is_required_and_must_be_known(self):
        with self.assertRaises(CommandError):
            run_command()
        with self.assertRaises(CommandError):
            run_command("--set", "bilinmeyen")

    def test_numeric_options_are_validated(self):
        for option, value in (("--sample", "0"), ("--concurrency", "0"), ("--budget", "0")):
            with self.assertRaises(CommandError, msg=option):
                run_command("--set", "konu30", option, value)

    @override_settings(ANTHROPIC_MODEL="model-without-known-price")
    def test_explicit_budget_with_unknown_model_price_stops_before_starting(self):
        with mock.patch.object(evaluate_agent.eval_sets, "load_requests") as load:
            with self.assertRaises(CommandError) as ctx:
                run_command("--set", "konu30", "--budget", "1")

        self.assertIn("fiyat bilinmiyor", str(ctx.exception))
        load.assert_not_called()  # veri okunmadan, model çağrılmadan durdu

    def test_unknown_model_does_not_start_without_an_explicit_no_budget(self):
        with mock.patch.object(evaluate_agent.eval_sets, "load_requests") as load:
            with self.assertRaises(CommandError) as ctx:
                run_command("--set", "konu30", "--model", "yeni-model")

        self.assertIn("--no-budget", str(ctx.exception))
        load.assert_not_called()  # sessizce sınırsız para harcanmaz

    def test_unknown_model_with_no_budget_starts_and_warns(self):
        with override_settings(SEARCH={**settings.SEARCH, "eval_data_dir": "/yok"}):
            with self.assertRaises(CommandError) as ctx:
                run_command("--set", "konu30", "--model", "yeni-model", "--no-budget")

        # Fiyat engeli yok: ilerledi ve ancak veri yokluğunda durdu.
        self.assertIn("eval_data_missing", str(ctx.exception))

    def test_budget_and_no_budget_cannot_be_combined(self):
        with self.assertRaises(CommandError) as ctx:
            run_command("--set", "konu30", "--budget", "1", "--no-budget")

        self.assertIn("birlikte", str(ctx.exception))


class CommandRunTests(TransactionTestCase):
    """Komut kendi olay döngüsünü açtığı için işlemsiz sınanır (gerçek PostgreSQL kaydedici)."""

    def test_three_request_run_with_a_fake_model_and_search(self):
        films = [make_story_film(n) for n in range(50)]  # Q0..Q49; arama sırası = film sırası
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        write_known50(root, [film.wikidata_id for film in films])
        write_konu30(root)
        write_tone25(root)
        llm = MeteredLLM()
        retrieval = FakeRetrieval([film.pk for film in films])
        models = []

        def fake_llm(model):
            models.append(model)
            return llm

        out = root / "sonuc" / "run.json"
        configured = settings.ANTHROPIC_MODEL
        with (
            override_settings(SEARCH={**settings.SEARCH, "eval_data_dir": str(root)}),
            mock.patch.object(evaluate_agent, "build_llm", fake_llm),
            mock.patch.object(evaluate_agent, "build_retrieval", lambda: retrieval),
        ):
            stdout, _ = run_command(
                "--set", "known50", "--set", "konu30", "--set", "tone25",
                "--sample", "1", "--model", "claude-sonnet-5-5", "--out", str(out),
            )  # fmt: skip

        self.assertEqual(models, ["claude-sonnet-5-5"])  # yalnız bu koşu için
        self.assertEqual(settings.ANTHROPIC_MODEL, configured)  # ayar değişmedi
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["model"], "claude-sonnet-5-5")
        self.assertEqual(len(report["requests"]), 3)
        self.assertEqual({r["status"] for r in report["requests"].values()}, {"ok"})
        known = next(r for r in report["requests"].values() if r["set"] == "known50")
        target_index = int(known["metrics"]["target"].removeprefix("Q"))
        self.assertEqual(known["metrics"]["hit_draft"], target_index < 5)  # taslak = Q0..Q4
        self.assertEqual(known["metrics"]["first_search_rank"], target_index + 1)
        konu = next(r for r in report["requests"].values() if r["set"] == "konu30")
        self.assertEqual(konu["metrics"]["precision_draft"], 0.4)  # Q1, Q2 / Q0..Q4
        # Q999 yalnız konu_01'in cevap listesinde ve veritabanında yok.
        missing = 1 if konu["key"] == "konu30:konu_01" else 0
        self.assertEqual(konu["answer_key"]["missing"], missing)
        self.assertIn(f"karşılığı olmayan {missing}", stdout)
        tone = report["requests"]["tone25:ton_01"]
        self.assertAlmostEqual(tone["metrics"]["precision_covered"], 2 / 3)
        self.assertIn("[known50]", stdout)
        self.assertIn("Tanım:", stdout)  # iki değerli oranların tanımı tabloda
        self.assertIn("n_total=1, n_ok=1", stdout)
        self.assertIn("tanımlı turlarda", stdout)
        self.assertIn("bütün isteklerde", stdout)
        self.assertIn("payda n_searched", stdout)  # her oran kendi paydasını söyler
        self.assertIn("payda n_with_draft", stdout)
        self.assertIn("payda n_total - n_unjudgeable", stdout)
        self.assertIn("yargılanamadı (genome kapsamı dışı): 0 tur", stdout)
        self.assertIn("en çok eşzamanlılık x tek tur maliyeti", stdout)
        self.assertIn("ALT SINIRDIR", stdout)

        self.assertIn(f"JSON: {out}", stdout)
        # Ölçüm bitince açılan sohbet ve taslaklar silinmiş; onaylama yok.
        self.assertFalse(Chat.objects.filter(user__username="eval_runner").exists())
        self.assertFalse(Collection.objects.filter(owner__username="eval_runner").exists())
        self.assertFalse(Collection.objects.filter(status="approved").exists())
