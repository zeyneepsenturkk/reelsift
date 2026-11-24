from django.test import TestCase

from apps.search.services import lexical, pipeline
from apps.search.services.types import ParsedQuery, QueryFilters, SearchResult, TitleHint
from apps.search.tests.base import (
    fake_models,
    make_film,
    make_profile,
    override_search,
    search_settings,
)


class PipelineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dream = make_film(
            "Q1", title="Dream Heist", word="dream", year=2010, overview="Thieves enter dreams."
        )
        cls.dream_old = make_film("Q2", title="Old Dream", word="dream", year=1950)
        cls.ocean = make_film("Q3", title="Deep Ocean", word="ocean", year=2012)
        cls.war = make_film("Q4", title="Trench War", word="war", year=2014)
        cls.short = make_film("Q5", title="Tiny Dream", word="dream", plot="A dream.", year=2011)
        make_profile(cls.dream, tone="A tense and layered dream thriller for patient viewers.")

    def run_search(self, query, **kwargs):
        with search_settings(), fake_models():
            return pipeline.search(query, **kwargs)

    def test_result_has_the_agreed_shape(self):
        result = self.run_search(ParsedQuery("dream", "a dream story"))
        self.assertIsInstance(result, SearchResult)
        first = result.candidates[0]
        self.assertEqual(first.film_id in {self.dream.pk, self.dream_old.pk}, True)
        self.assertIsInstance(first.rerank_score, float)
        self.assertGreaterEqual(first.rrf_rank, 1)
        self.assertEqual(result.relaxed_filters, ())
        self.assertEqual(result.pool_size, len(result.candidates))
        for name in ("scope", "encode", "dense", "hyde", "card", "bm25", "g", "fuse", "rerank"):
            self.assertIn(name, result.timings)
        self.assertIn("total", result.timings)

    def test_sources_name_the_lists_that_found_the_film(self):
        query = ParsedQuery("dream", "a dream story", titles=(TitleHint("Dream Heist", 2010),))
        result = self.run_search(query)
        by_film = {c.film_id: c for c in result.candidates}
        self.assertEqual(
            set(by_film[self.dream.pk].sources), {"dense", "hyde", "card", "bma", "bmb", "g"}
        )
        # "dream" kelimesi geçmeyen okyanus filmi kelime listelerinde kaynak sayılmaz.
        self.assertNotIn("bma", by_film[self.ocean.pk].sources)
        self.assertNotIn("g", by_film[self.dream_old.pk].sources)

    def test_short_plot_film_is_dropped_unless_model_suggested_it(self):
        result = self.run_search(ParsedQuery("dream", "a dream story"))
        self.assertNotIn(self.short.pk, [c.film_id for c in result.candidates])
        suggested = ParsedQuery("dream", "a dream", titles=(TitleHint("Tiny Dream", 2011),))
        result = self.run_search(suggested)
        by_film = {c.film_id: c for c in result.candidates}
        self.assertIn("g", by_film[self.short.pk].sources)

    def test_filters_are_hard_and_applied_before_ranking(self):
        query = ParsedQuery("dream", "a dream", filters=QueryFilters(year_min=2000))
        with override_search(min_filtered_films=1):
            result = self.run_search(query)
        film_ids = [c.film_id for c in result.candidates]
        self.assertNotIn(self.dream_old.pk, film_ids)
        self.assertIn(self.dream.pk, film_ids)
        self.assertEqual(result.relaxed_filters, ())

    def test_too_restrictive_filter_is_relaxed_and_reported(self):
        query = ParsedQuery("dream", "a dream", filters=QueryFilters(year_max=1900))
        result = self.run_search(query)
        self.assertEqual(result.relaxed_filters, ("year_max",))
        self.assertIn(self.dream.pk, [c.film_id for c in result.candidates])

    def test_exclude_and_pool_film_ids(self):
        query = ParsedQuery("dream", "a dream")
        result = self.run_search(query, exclude_film_ids=[self.dream.pk])
        self.assertNotIn(self.dream.pk, [c.film_id for c in result.candidates])
        result = self.run_search(query, pool_film_ids=[self.dream_old.pk, self.ocean.pk])
        self.assertLessEqual(
            {c.film_id for c in result.candidates}, {self.dream_old.pk, self.ocean.pk}
        )

    def test_limit_caps_the_candidates(self):
        result = self.run_search(ParsedQuery("dream", "a dream"), limit=2)
        self.assertEqual(len(result.candidates), 2)
        self.assertGreater(result.pool_size, 2)

    def test_final_order_follows_rerank_scores_and_keeps_rrf_rank(self):
        def prefer_ocean(pairs):
            return [10.0 if "ocean" in document else 1.0 for _, document in pairs]

        with search_settings(), fake_models(score_pairs=prefer_ocean):
            result = pipeline.search(ParsedQuery("dream", "a dream"))
        self.assertEqual(result.candidates[0].film_id, self.ocean.pk)
        self.assertGreater(result.candidates[0].rrf_rank, 1)

    def test_blend_one_keeps_rrf_order(self):
        def prefer_ocean(pairs):
            return [10.0 if "ocean" in document else 1.0 for _, document in pairs]

        with search_settings(blend=1.0), fake_models(score_pairs=prefer_ocean):
            result = pipeline.search(ParsedQuery("dream", "a dream"))
        self.assertEqual(
            [c.rrf_rank for c in result.candidates], sorted(c.rrf_rank for c in result.candidates)
        )

    def test_rerank_documents_follow_doc_mode(self):
        film_ids = [self.dream.pk, self.ocean.pk]
        doc_a = pipeline.rerank_documents(film_ids, "A")
        doc_b = pipeline.rerank_documents(film_ids, "B")
        doc_end = pipeline.rerank_documents(film_ids, "B_end")
        self.assertTrue(doc_a[0].startswith("Thieves enter dreams. The story"))
        self.assertTrue(doc_b[0].startswith("Themes: memory."))
        self.assertTrue(doc_b[0].endswith(doc_a[0].strip()))
        self.assertTrue(doc_end[0].startswith(doc_a[0]))
        self.assertEqual(doc_b[1], doc_a[1].strip())  # profili olmayan film: B = A

    def test_rerank_document_falls_back_to_the_turkish_overview(self):
        turkish = make_film("Q6", title="Yalnız Film", word="dream", overview="")
        turkish.tr_overview = "Türkçe özet metni."
        turkish.save(update_fields=["tr_overview"])
        both = make_film("Q7", title="Both", word="dream", overview="English overview.")
        both.tr_overview = "Türkçe özet metni."
        both.save(update_fields=["tr_overview"])

        docs = pipeline.rerank_documents([turkish.pk, both.pk], "A")

        self.assertTrue(docs[0].startswith("Türkçe özet metni."))
        self.assertTrue(docs[1].startswith("English overview."))
        self.assertNotIn("Türkçe", docs[1])

    def test_documents_are_scored_against_the_english_query(self):
        with search_settings(), fake_models() as scorer:
            pipeline.search(ParsedQuery("my english query", "story"))
        pairs = scorer.call_args.args[0]
        self.assertTrue(all(query == "my english query" for query, _ in pairs))

    def test_empty_result_when_scope_is_empty(self):
        result = self.run_search(ParsedQuery("dream", "a dream"), pool_film_ids=[])
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.pool_size, 0)

    def test_index_is_built_on_first_search_when_missing(self):
        with search_settings(), fake_models():
            self.assertFalse(lexical.index_exists())
            pipeline.search(ParsedQuery("dream", "a dream"))
            self.assertTrue(lexical.index_exists())
