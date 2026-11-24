from django.test import TestCase

from apps.search.services import scope, vectors
from apps.search.services.types import QueryFilters
from apps.search.tests.base import axis_vector, make_film, override_search


class VectorSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dream_old = make_film("Q1", word="dream", year=1950)
        cls.dream_new = make_film("Q2", word="dream", year=2015)
        cls.ocean = make_film("Q3", word="ocean", year=2015)
        cls.no_card = make_film("Q4", word="dream", year=2015, with_card=False)
        cls.no_chunk = make_film("Q5", word="dream", year=2015, with_chunk=False)

    def unrestricted(self):
        return scope.resolve_scope(QueryFilters())

    def test_chunk_scores_exact_gives_best_chunk_per_film(self):
        # İkinci parça alakasız; film puanı en iyi parçanın puanıdır.
        from apps.films.models import FilmChunk

        FilmChunk.objects.create(
            film=self.dream_old, position=1, text="other", embedding=axis_vector(3)
        )
        film_ids, scores = vectors.chunk_scores(axis_vector(0), self.unrestricted(), "exact")
        by_film = dict(zip(film_ids.tolist(), scores.tolist(), strict=True))
        self.assertAlmostEqual(by_film[self.dream_old.pk], 1.0, places=3)
        self.assertAlmostEqual(by_film[self.ocean.pk], 0.0, places=3)
        self.assertNotIn(self.no_chunk.pk, by_film)
        self.assertEqual(len(film_ids), 4)

    def test_chunk_scores_apply_scope_before_ranking(self):
        with override_search(min_filtered_films=1):
            film_scope = scope.resolve_scope(QueryFilters(year_min=2000))
        film_ids, _ = vectors.chunk_scores(axis_vector(0), film_scope, "exact")
        self.assertNotIn(self.dream_old.pk, film_ids.tolist())
        self.assertIn(self.dream_new.pk, film_ids.tolist())

    def test_chunk_scores_respect_exclude_and_pool(self):
        film_scope = scope.resolve_scope(
            QueryFilters(),
            exclude_film_ids=[self.dream_new.pk],
            pool_film_ids=[
                self.dream_new.pk,
                self.dream_old.pk,
            ],
        )
        film_ids, _ = vectors.chunk_scores(axis_vector(0), film_scope, "exact")
        self.assertEqual(film_ids.tolist(), [self.dream_old.pk])

    def test_card_scores_exact_orders_by_similarity_and_skips_missing_cards(self):
        film_ids, scores = vectors.card_scores(axis_vector(1), self.unrestricted(), "exact")
        self.assertEqual(film_ids[0], self.ocean.pk)
        self.assertAlmostEqual(float(scores[0]), 1.0, places=3)
        self.assertNotIn(self.no_card.pk, film_ids.tolist())
        self.assertEqual(len(film_ids), 4)

    def test_hnsw_mode_finds_the_same_best_film(self):
        exact_ids, _ = vectors.chunk_scores(axis_vector(1), self.unrestricted(), "exact")
        hnsw_ids, hnsw_scores = vectors.chunk_scores(axis_vector(1), self.unrestricted(), "hnsw")
        self.assertEqual(hnsw_ids[hnsw_scores.argmax()], self.ocean.pk)
        self.assertEqual(set(hnsw_ids.tolist()), set(exact_ids.tolist()))
        card_ids, _ = vectors.card_scores(axis_vector(1), self.unrestricted(), "hnsw")
        self.assertEqual(card_ids[0], self.ocean.pk)

    def test_hnsw_mode_applies_scope(self):
        film_scope = scope.resolve_scope(QueryFilters(), exclude_film_ids=[self.ocean.pk])
        hnsw_ids, _ = vectors.chunk_scores(axis_vector(1), film_scope, "hnsw")
        self.assertNotIn(self.ocean.pk, hnsw_ids.tolist())
