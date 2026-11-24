from django.test import SimpleTestCase

from apps.agent.services import eval_metrics, eval_sets
from apps.agent.tests.eval_base import make_eval_request


def record(**overrides) -> dict:
    fields = {
        "status": "ok",
        "seconds": 10.0,
        "film_count": 5,
        "quote_match_rate": 1.0,
        "dropped_films": 0,
        "calls": 6,
        "cost_usd": 0.1,
        "metrics": {
            "precision_draft": None
        },  # konu30 biçimi; diğer kümeler kendi metrics'ini verir
    }
    fields.update(overrides)
    fields.setdefault("total_cost_usd", fields["cost_usd"])
    return fields


def triple(rate: dict) -> tuple:
    """Oran, kendi paydası ve payda adı: üçü de açıkça sınanır."""
    return rate["value"], rate["n"], rate["denominator"]


class MetricFunctionTests(SimpleTestCase):
    def test_precision_draft_is_matched_over_draft_size(self):
        # Taslakta 4 film, 2'si cevap listesinde: 2 / 4.
        result = eval_metrics.precision_draft(["A", "B", "C", "D"], frozenset({"A", "C", "X"}))

        self.assertEqual(result, 0.5)

    def test_precision_draft_is_none_for_an_empty_draft(self):
        self.assertIsNone(eval_metrics.precision_draft([], frozenset({"A"})))

    def test_tone_metrics_separates_uncovered_films_and_zero_gain_films(self):
        gains = {1: 0.9, 2: 0.85, 3: 0.3, 4: 0.0}  # 4: ek kısıtı sağlamayan, yargılı
        relevant = frozenset({1, 2})

        result = eval_metrics.tone_metrics([1, 3, 4, 5, 9], gains, relevant)

        # Kapsamda 1, 3, 4; uygun yalnız 1; 5 ve 9 yargılanamaz.
        self.assertEqual(result["covered"], 3)
        self.assertEqual(result["uncovered"], 2)
        self.assertEqual(result["appropriate"], 1)
        self.assertAlmostEqual(result["precision_covered"], 1 / 3)

    def test_tone_metrics_has_no_precision_without_coverage(self):
        result = eval_metrics.tone_metrics([5, 9], {1: 0.9}, frozenset({1}))

        self.assertEqual(result["covered"], 0)
        self.assertIsNone(result["precision_covered"])

    def test_known_metrics_reports_draft_rank_and_search_ranks(self):
        result = eval_metrics.known_metrics(20, [10, 20, 30], [[5, 6, 20], [20, 1]])

        self.assertTrue(result["hit_draft"])
        self.assertEqual(result["draft_rank"], 2)
        self.assertEqual(result["first_search_rank"], 3)  # ilk arama çağrısı
        self.assertEqual(result["best_search_rank"], 1)  # tüm çağrıların en iyisi

    def test_known_metrics_miss_and_no_search(self):
        miss = eval_metrics.known_metrics(99, [10], [[1, 2, 3]])
        self.assertFalse(miss["hit_draft"])
        self.assertTrue(miss["searched"])
        self.assertIsNone(miss["first_search_rank"])  # arandı ama hedef listede yok

        no_search = eval_metrics.known_metrics(99, [], [])
        self.assertFalse(no_search["searched"])


class SummaryTests(SimpleTestCase):
    def test_known50_summary_computes_rates_over_measured_turns(self):
        def known(hit, draft_rank, first, searched=True):
            return {
                "hit_draft": hit,
                "draft_rank": draft_rank,
                "searched": searched,
                "first_search_rank": first,
            }

        records = [
            record(metrics=known(True, 2, 1)),
            record(metrics=known(True, 4, 8)),
            record(metrics=known(False, None, 70)),
            record(metrics=known(False, None, None)),
            record(status="taslak yok", film_count=0, metrics=known(False, None, None, False)),
            record(status="hata", metrics={}, cost_usd=0.05),
        ]

        summary = eval_metrics.summarize_set("known50", records)

        self.assertEqual(
            (summary["n"], summary["ok"], summary["no_draft"], summary["failed"]), (6, 4, 1, 1)
        )
        self.assertEqual((summary["n_total"], summary["n_ok"]), (6, 5))
        # hit_draft: 2 isabet. Tanımlı küme hatasız turlar (n_ok = 5, 'taslak yok' ıska); hata
        # turu dışarıda. Bütün istekler: payda 6, hata turu da ıska.
        self.assertEqual(triple(summary["hit_draft_defined"]), (0.4, 5, "n_ok"))
        self.assertEqual(triple(summary["hit_draft_all"]), (0.3333, 6, "n_total"))
        self.assertEqual(summary["mean_draft_rank"], 3.0)
        self.assertEqual(summary["n_searched"], 4)  # taslak yok turunda arama yapılmamış
        # R@k: arama sıraları [1, 8, 70, None]. Tanımlı küme yalnız aranan turlar (payda 4);
        # bütün istekler paydası 6 (aramasız ve hatalı tur ıska).
        self.assertEqual(triple(summary["R@1_defined"]), (0.25, 4, "n_searched"))
        self.assertEqual(triple(summary["R@1_all"]), (0.1667, 6, "n_total"))
        self.assertEqual(triple(summary["R@10_defined"]), (0.5, 4, "n_searched"))
        self.assertEqual(triple(summary["R@10_all"]), (0.3333, 6, "n_total"))
        self.assertEqual(triple(summary["R@50_defined"]), (0.5, 4, "n_searched"))
        self.assertEqual(triple(summary["R@50_all"]), (0.3333, 6, "n_total"))

    def test_general_summary_numbers(self):
        records = [
            record(seconds=10.0, cost_usd=0.1, quote_match_rate=1.0, dropped_films=0),
            record(seconds=30.0, cost_usd=0.3, quote_match_rate=0.5, dropped_films=2),
            record(seconds=20.0, cost_usd=0.2, quote_match_rate=None, dropped_films=1),
            record(status="hata", seconds=99.0, cost_usd=0.4),
        ]

        summary = eval_metrics.summarize_set("konu30", records)

        self.assertEqual(summary["seconds_median"], 20.0)  # hatalı tur süreye girmez
        self.assertEqual(summary["seconds_max"], 30.0)
        self.assertEqual(summary["total_cost_usd"], 1.0)  # hatalı tur harcaması dahil
        self.assertEqual(summary["mean_cost_usd"], 0.25)
        self.assertEqual(summary["mean_quote_match"], 0.75)  # None atlanır
        self.assertEqual(summary["mean_dropped"], 1.0)

    def test_retried_turn_keeps_the_spend_of_its_earlier_attempts(self):
        retried = record(cost_usd=0.1, total_cost_usd=0.35, attempts=2)

        summary = eval_metrics.summarize_set("konu30", [retried, record(cost_usd=0.2)])

        self.assertEqual(summary["total_cost_usd"], 0.55)  # 0,35 + 0,2; yalnız son deneme değil
        self.assertEqual(summary["attempts"], 3)

    def test_cost_is_unknown_when_any_turn_has_no_price(self):
        summary = eval_metrics.summarize_set(
            "konu30", [record(cost_usd=0.1), record(cost_usd=None)]
        )

        self.assertIsNone(summary["total_cost_usd"])
        self.assertIsNone(summary["mean_cost_usd"])

    def test_konu30_and_tone25_summaries(self):
        konu = eval_metrics.summarize_set(
            "konu30",
            [
                record(metrics={"precision_draft": 0.4}),
                record(metrics={"precision_draft": 0.8}),
                record(status="taslak yok", metrics={"precision_draft": None}),
                record(status="hata", metrics={}),
            ],
        )
        # Tanımlı küme: taslağı çıkan iki tur, (0,4 + 0,8) / 2 = 0,6. Taslaksız ve hatalı tur
        # dışarıda. Bütün istekler: 1,2 / 4 = 0,3 (taslaksız ve hatalı tur 0).
        self.assertEqual(triple(konu["precision_draft_defined"]), (0.6, 2, "n_with_draft"))
        self.assertEqual(triple(konu["precision_draft_all"]), (0.3, 4, "n_total"))
        self.assertEqual((konu["n_ok"], konu["n_total"]), (3, 4))

        tone = eval_metrics.summarize_set(
            "tone25",
            [
                record(
                    metrics={
                        "covered": 3,
                        "uncovered": 2,
                        "appropriate": 1,
                        "precision_covered": 1 / 3,
                    }
                ),
                record(
                    metrics={
                        "covered": 0,
                        "uncovered": 5,
                        "appropriate": 0,
                        "precision_covered": None,
                    }
                ),
                record(
                    status="taslak yok",
                    film_count=0,
                    metrics={
                        "covered": 0,
                        "uncovered": 0,
                        "appropriate": 0,
                        "precision_covered": None,
                    },
                ),
                record(status="hata", metrics={}),
                record(
                    metrics={
                        "covered": 2,
                        "uncovered": 0,
                        "appropriate": 2,
                        "precision_covered": 1.0,
                    }
                ),
            ],
        )
        # 5 istek: A (kesinlik 1/3), E (kesinlik 1), B (taslak var ama genome kapsamı dışı:
        # yargılanamadı), C (taslak yok), D (hata). Tanımlı küme A ve E: (1/3 + 1) / 2 = 0,6667.
        self.assertEqual(triple(tone["precision_covered_defined"]), (0.6667, 2, "n_with_coverage"))
        # Bütün istekler: B payda dışı (n_unjudgeable = 1); C ve D payda içinde 0:
        # (1/3 + 1) / (5 - 1) = 0,3333.
        self.assertEqual(tone["n_unjudgeable"], 1)
        self.assertEqual(
            triple(tone["precision_covered_all"]), (0.3333, 4, "n_total - n_unjudgeable")
        )
        self.assertEqual((tone["covered"], tone["uncovered"]), (5, 7))

    def test_tone25_ok_turn_with_an_empty_draft_is_a_miss_not_unjudgeable(self):
        no_films = record(
            film_count=0,
            metrics={"covered": 0, "uncovered": 0, "appropriate": 0, "precision_covered": None},
        )
        judged = record(
            metrics={"covered": 2, "uncovered": 0, "appropriate": 1, "precision_covered": 0.5}
        )

        tone = eval_metrics.summarize_set("tone25", [no_films, judged])

        # Filmi olmayan "ok" tur payda içinde 0 kalır: (0,5) / 2 = 0,25; yargılanamadı sayılmaz.
        self.assertEqual(tone["n_unjudgeable"], 0)
        self.assertEqual(
            triple(tone["precision_covered_all"]), (0.25, 2, "n_total - n_unjudgeable")
        )

    def test_empty_set_does_not_divide_by_zero(self):
        summary = eval_metrics.summarize_set("known50", [])

        self.assertEqual(summary["n"], 0)
        self.assertEqual(triple(summary["hit_draft_defined"]), (None, 0, "n_ok"))
        self.assertEqual(triple(summary["hit_draft_all"]), (None, 0, "n_total"))
        self.assertEqual(triple(summary["R@10_defined"]), (None, 0, "n_searched"))
        self.assertEqual(triple(summary["R@10_all"]), (None, 0, "n_total"))


class SamplingTests(SimpleTestCase):
    def requests(self, count=30, set_name="konu30"):
        return [make_eval_request(set_name, f"{n:02d}") for n in range(count)]

    def test_same_sample_is_chosen_every_time_regardless_of_input_order(self):
        requests = self.requests()

        first = eval_sets.sample_requests(requests, 7)
        second = eval_sets.sample_requests(list(reversed(requests)), 7)

        self.assertEqual([r.key for r in first], [r.key for r in second])
        self.assertEqual(len(first), 7)

    def test_small_sample_is_inside_the_larger_one_and_keeps_file_order(self):
        small = [r.key for r in eval_sets.sample_requests(self.requests(), 5)]
        large = [r.key for r in eval_sets.sample_requests(self.requests(), 12)]

        self.assertTrue(set(small) <= set(large))
        self.assertEqual(large, sorted(large))

    def test_sample_is_different_per_set_but_stable(self):
        def numbers(set_name):
            chosen = eval_sets.sample_requests(self.requests(set_name=set_name), 5)
            return [r.key.split(":")[1] for r in chosen]

        self.assertNotEqual(numbers("konu30"), numbers("tone25"))
        self.assertEqual(numbers("konu30"), numbers("konu30"))

    def test_sample_larger_than_set_returns_everything(self):
        self.assertEqual(len(eval_sets.sample_requests(self.requests(4), 10)), 4)
        self.assertEqual(len(eval_sets.sample_requests(self.requests(4), None)), 4)
