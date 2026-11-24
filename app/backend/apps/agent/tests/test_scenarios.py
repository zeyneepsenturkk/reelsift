import re

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from apps.agent import runtime, scenarios
from apps.agent.tests.base import FakeLLM, FakeRetrieval, make_graph, understood
from apps.curation.tests.base import make_story_film, make_user


def scripted_understanding(user: str):
    message = re.search(r"<user_message>(.*?)</user_message>", user, re.DOTALL).group(1)
    if "Daha karanlık" in message:
        return understood("refine", instruction="darker")
    if "neden seçildi" in message:
        return understood("question", request=None)
    return understood()


class ScenarioRunTests(TestCase):
    def setUp(self):
        self.user = make_user("gelistirme")
        self.films = [make_story_film(n) for n in range(1, 13)]
        self.llm = FakeLLM(understand=scripted_understanding)
        self.retrieval = FakeRetrieval([film.pk for film in self.films])
        runtime.set_graph(make_graph(self.llm, self.retrieval))
        self.addCleanup(runtime.set_graph, None)

    async def test_all_six_turns_run_through_the_stream_endpoint_and_are_measured(self):
        result = await scenarios.run_scenarios(self.user, "claude-haiku-5-5")

        reports = result["scenarios"]
        self.assertEqual([r["number"] for r in reports], [1, 2, 3, 4, 5, 6])
        self.assertEqual({r["status"] for r in reports}, {"ok"})
        # Metninde sayı olmayan turlar (tema, düzeltme, değiştirme) varsayılan 10 filmi alır;
        # sayı söyleyenler 5.
        expected = {"tema": 10, "ton + dönem": 5, "ülke filtreli": 5}
        for report in reports[:3]:
            self.assertEqual(report["film_count"], expected[report["name"]], report["name"])
        for report in reports[3:5]:
            self.assertEqual(report["film_count"], 10, report["name"])
        for report in reports[:5]:
            self.assertEqual(report["filter_violations"], 0)
            self.assertEqual(report["quote_match_rate"], 1.0)
        self.assertEqual(reports[5]["film_count"], 0)  # soru turu koleksiyon üretmez
        self.assertIn("parse", reports[0]["step_seconds"])
        self.assertIn("select", reports[0]["step_seconds"])
        self.assertIn("update", reports[4]["step_seconds"])
        self.assertIn("Snow Town", reports[5]["text"])  # 6. turda taslaktaki ilk filmin adı
        self.assertEqual(result["model"], "claude-haiku-5-5")
        self.assertEqual(result["spent_usd"], 0.0)  # sahte model token harcamaz
        self.assertIsNotNone(result["median_new_search_seconds"])
        self.assertIn("Toplam", scenarios.format_summary(result))

    async def test_follow_up_turns_share_the_first_chat(self):
        await scenarios.run_scenarios(self.user, "claude-haiku-5-5", only={1, 4})

        # 4. tur refine: 1. senaryonun sohbetindeki taslak güncellendi, ikinci taslak açılmadı.
        from apps.curation.models import Collection

        self.assertEqual(await Collection.objects.acount(), 1)
        self.assertEqual((await Collection.objects.afirst()).version, 2)

    async def test_budget_limit_skips_remaining_turns(self):
        result = await scenarios.run_scenarios(self.user, "claude-haiku-5-5", budget_usd=0.0)

        self.assertTrue(all(r["status"].startswith("atlandı") for r in result["scenarios"]))
        self.assertEqual(self.retrieval.calls, [])

    async def test_unknown_model_price_gives_no_cost(self):
        result = await scenarios.run_scenarios(self.user, "bilinmeyen-model", only={1})

        self.assertIsNone(result["scenarios"][0]["cost_usd"])
        self.assertIsNone(result["spent_usd"])

    async def test_model_error_is_reported_per_turn(self):
        self.llm.fail_step = "parse"

        result = await scenarios.run_scenarios(self.user, "claude-haiku-5-5", only={1})

        report = result["scenarios"][0]
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["error"]["code"], "model_error")

    async def test_dependent_turns_are_skipped_without_a_draft(self):
        result = await scenarios.run_scenarios(self.user, "claude-haiku-5-5", only={5})

        self.assertEqual(result["scenarios"][0]["status"], "atlandı (taslak yok)")


class MeasurementTests(SimpleTestCase):
    def test_cost_uses_per_million_prices(self):
        self.assertAlmostEqual(
            scenarios.cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000), 0.60, places=6
        )
        self.assertIsNone(scenarios.cost_usd("x", 1, 1))
        self.assertEqual(scenarios.cost_usd("x", 1_000_000, 0, {"x": (3.0, 15.0)}), 3.0)

    def test_filter_violations_are_counted_for_year_and_country(self):
        request = {"filters": {"year_min": 2000, "year_max": 2010, "countries": ["Japan"]}}
        films = [
            {"year": 2005, "countries": ["Japan"]},  # uygun
            {"year": 1999, "countries": ["Japan"]},  # yıl ihlali
            {"year": 2011, "countries": ["japan"]},  # yıl ihlali
            {"year": 2005, "countries": ["France"]},  # ülke ihlali
            {"year": None, "countries": ["Japan"]},  # yılı bilinmeyen: ihlal sayılır
        ]

        self.assertEqual(scenarios.count_filter_violations(request, films), 4)
        self.assertEqual(scenarios.count_filter_violations({}, films), 0)

    def test_step_durations_sum_repeated_steps(self):
        timeline = [
            (0.0, "step.start", {"key": "search"}),
            (1.0, "step.done", {"key": "search"}),
            (1.5, "step.start", {"key": "search"}),
            (3.0, "step.done", {"key": "search"}),
            (3.0, "notice", {"text": "x"}),
        ]

        self.assertEqual(scenarios.step_durations(timeline), {"search": 2.5})

    def test_quote_match_rate_counts_only_exact_matches(self):
        rows = [
            {
                "quote": "A quiet night.",
                "plot": "It was A quiet night.",
                "overview": "",
                "reviews": [],
            },
            {"quote": "Made up.", "plot": "Something else.", "overview": "", "reviews": ["Other"]},
        ]

        self.assertEqual(scenarios.quote_match_rate(rows), 0.5)
        self.assertIsNone(scenarios.quote_match_rate([]))


class CommandTests(TestCase):
    @override_settings(ANTHROPIC_MODEL="model-without-known-price")
    def test_command_refuses_to_run_without_a_known_price(self):
        with self.assertRaises(CommandError):
            call_command("run_scenarios")
