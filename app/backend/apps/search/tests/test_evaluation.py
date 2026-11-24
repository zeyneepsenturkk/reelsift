from django.test import SimpleTestCase

from apps.search.services import evaluation


class MetricTests(SimpleTestCase):
    def test_rank_of_and_recall(self):
        self.assertEqual(evaluation.rank_of(7, [3, 7, 9]), 2)
        self.assertIsNone(evaluation.rank_of(1, [3, 7, 9]))
        ranks = [1, 5, 10, None]
        self.assertEqual(evaluation.recall_at(ranks, 1), 0.25)
        self.assertEqual(evaluation.recall_at(ranks, 10), 0.75)
        self.assertEqual(evaluation.recall_at(ranks, 50), 0.75)

    def test_precision_at_10_skips_unjudged_and_divides_by_ten(self):
        gains = {1: 0.9, 2: 0.2, 3: 0.85}
        relevant = {1, 3}
        # 99 yargısız, atlanır; ilk üç yargılı film 1, 2, 3 -> 2 uygun; payda 10.
        self.assertEqual(evaluation.precision_at_10([99, 1, 2, 3], gains, relevant), 0.2)

    def test_ndcg_matches_hand_computation(self):
        gains = {1: 1.0, 2: 0.5, 3: 0.0}
        log3 = 1.5849625007211562  # log2(3)
        # Sıra 2, 1: dcg = 0,5/log2(2) + 1,0/log2(3); ideal sıra 1, 2, 3: 1,0/log2(2) + 0,5/log2(3).
        dcg = 0.5 / 1.0 + 1.0 / log3
        ideal = 1.0 / 1.0 + 0.5 / log3
        self.assertAlmostEqual(evaluation.ndcg_at_10([2, 1], gains), dcg / ideal)
        self.assertAlmostEqual(evaluation.ndcg_at_10([1, 2, 3], gains), 1.0)

    def test_ndcg_without_gains_is_zero(self):
        self.assertEqual(evaluation.ndcg_at_10([1], {1: 0.0}), 0.0)

    def test_mean_relevance_pads_to_ten(self):
        self.assertAlmostEqual(evaluation.mean_relevance_at_10([1, 2], {1: 1.0, 2: 0.5}), 0.15)

    def test_coverage_recall_uses_min_of_fifty_and_relevant_count(self):
        self.assertEqual(evaluation.coverage_recall([1, 2, 3], {1, 2, 9, 10}), 0.5)
        self.assertEqual(evaluation.coverage_recall(list(range(50)), set(range(100))), 1.0)

    def test_median_and_max(self):
        self.assertEqual(evaluation.median_and_max([3.0, 1.0, 2.0]), (2.0, 3.0))


class ParsedQueryTests(SimpleTestCase):
    OUT = {
        "en_query": "a query",
        "hyde": "a story",
        "titles": [
            {"title": "Heat", "year": "1995"},
            {"title": "Bad", "year": None},
            {"title": "NoYear"},
        ],
        "filters": {
            "year_min": 1990,
            "year_max": None,
            "countries": ["France"],
            "genres": ["drama"],
            "max_vote_count": 500,
        },
    }

    def test_titles_without_readable_year_are_skipped(self):
        query = evaluation.query_from_parsed(self.OUT, with_filters=False)
        self.assertEqual([(t.title, t.year) for t in query.titles], [("Heat", 1995)])
        self.assertEqual(query.filters.countries, ())

    def test_filters_are_copied_without_genres(self):
        query = evaluation.query_from_parsed(self.OUT, with_filters=True)
        self.assertEqual(query.filters.year_min, 1990)
        self.assertEqual(query.filters.countries, ("France",))
        self.assertEqual(query.filters.max_vote_count, 500)
        self.assertEqual(query.genres, ())


class ConstraintTests(SimpleTestCase):
    ATTRS = ("drama film, crime film", "France, Italy", 1965.0)

    def test_no_constraint_is_always_ok(self):
        self.assertTrue(evaluation._constraint_ok(None, self.ATTRS))

    def test_genre_is_a_regex_search(self):
        self.assertTrue(evaluation._constraint_ok({"tur": "crime film"}, self.ATTRS))
        self.assertTrue(evaluation._constraint_ok({"tur": "horror film|crime film"}, self.ATTRS))
        self.assertFalse(evaluation._constraint_ok({"tur": "horror film"}, self.ATTRS))

    def test_year_and_country_bounds(self):
        self.assertTrue(evaluation._constraint_ok({"yil_max": 1969}, self.ATTRS))
        self.assertFalse(evaluation._constraint_ok({"yil_min": 2010}, self.ATTRS))
        self.assertTrue(evaluation._constraint_ok({"ulke": ["Italy", "Spain"]}, self.ATTRS))
        self.assertFalse(evaluation._constraint_ok({"ulke": ["Spain"]}, self.ATTRS))
        self.assertFalse(evaluation._constraint_ok({"yil_min": 1900}, ("", "", float("nan"))))
