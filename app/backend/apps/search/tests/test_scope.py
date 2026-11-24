import numpy as np
from django.test import TestCase

from apps.search.services import scope
from apps.search.services.types import QueryFilters
from apps.search.tests.base import make_film, override_search

SMALL_MIN = {"min_filtered_films": 1}


class ScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.old_fr = make_film("Q1", year=1950, countries=("France",), vote_count=10)
        cls.new_fr = make_film("Q2", year=2015, countries=("France", "Italy"), vote_count=900)
        cls.new_us = make_film(
            "Q3", year=2018, countries=("United States of America",), vote_count=50
        )
        cls.nameless_year = make_film("Q4", year=None, countries=("Germany",), vote_count=5)

    def resolve(self, filters=None, **kwargs):
        with override_search(**SMALL_MIN):
            return scope.resolve_scope(filters or QueryFilters(), **kwargs)

    def ids(self, film_scope):
        return film_scope.film_ids.tolist()

    def test_no_filters_means_unrestricted_archive(self):
        film_scope = self.resolve()
        self.assertFalse(film_scope.restricted)
        self.assertIsNone(film_scope.film_ids)
        self.assertEqual(film_scope.relaxed, ())

    def test_year_range_excludes_films_without_year(self):
        film_scope = self.resolve(QueryFilters(year_min=2000))
        self.assertEqual(self.ids(film_scope), [self.new_fr.pk, self.new_us.pk])
        film_scope = self.resolve(QueryFilters(year_max=2016))
        self.assertEqual(self.ids(film_scope), [self.old_fr.pk, self.new_fr.pk])

    def test_country_matches_case_insensitive_substring_of_any_country(self):
        film_scope = self.resolve(QueryFilters(countries=("france",)))
        self.assertEqual(self.ids(film_scope), [self.old_fr.pk, self.new_fr.pk])
        film_scope = self.resolve(QueryFilters(countries=("Italy", "United States")))
        self.assertEqual(self.ids(film_scope), [self.new_fr.pk, self.new_us.pk])

    def test_country_wildcard_characters_are_literal(self):
        film_scope = self.resolve(QueryFilters(countries=("%",)))
        self.assertEqual(film_scope.relaxed, ("countries",))

    def test_vote_count_ceiling(self):
        film_scope = self.resolve(QueryFilters(max_vote_count=50))
        self.assertEqual(
            self.ids(film_scope), [self.old_fr.pk, self.new_us.pk, self.nameless_year.pk]
        )

    def test_filters_combine_with_and(self):
        film_scope = self.resolve(
            QueryFilters(year_min=2000, countries=("France",), max_vote_count=1000)
        )
        self.assertEqual(self.ids(film_scope), [self.new_fr.pk])

    def test_filter_leaving_too_few_films_is_dropped_and_named(self):
        film_scope = self.resolve(QueryFilters(year_min=2018, countries=("France",)))
        self.assertEqual(film_scope.relaxed, ("year_min", "countries"))
        self.assertFalse(film_scope.restricted)
        self.assertIsNone(film_scope.film_ids)

    def test_default_threshold_is_thirty_films(self):
        film_scope = scope.resolve_scope(QueryFilters(year_min=2000))
        self.assertEqual(film_scope.relaxed, ("year_min",))

    def test_pool_and_exclude_apply_after_relaxing(self):
        film_scope = self.resolve(
            QueryFilters(year_min=2018, countries=("France",)),
            pool_film_ids=[self.old_fr.pk, self.new_fr.pk, self.new_us.pk],
            exclude_film_ids=[self.new_us.pk],
        )
        self.assertEqual(film_scope.relaxed, ("year_min", "countries"))
        self.assertEqual(self.ids(film_scope), [self.old_fr.pk, self.new_fr.pk])

    def test_pool_restricts_even_without_filters(self):
        film_scope = self.resolve(pool_film_ids=[self.new_us.pk])
        self.assertTrue(film_scope.restricted)
        self.assertEqual(self.ids(film_scope), [self.new_us.pk])

    def test_exclude_only_does_not_query_the_database_for_ids(self):
        with self.assertNumQueries(0):
            film_scope = self.resolve(exclude_film_ids=[self.new_us.pk, self.old_fr.pk])
        self.assertTrue(film_scope.restricted)
        self.assertIsNone(film_scope.film_ids)
        self.assertEqual(film_scope.excluded.tolist(), sorted([self.new_us.pk, self.old_fr.pk]))

    def test_pool_only_does_not_query_the_database_for_ids(self):
        with self.assertNumQueries(0):
            film_scope = self.resolve(pool_film_ids=[self.new_fr.pk, self.old_fr.pk])
        self.assertEqual(self.ids(film_scope), sorted([self.old_fr.pk, self.new_fr.pk]))

    def test_filter_costs_one_count_and_one_id_query(self):
        with self.assertNumQueries(2):
            self.resolve(QueryFilters(year_min=2000))
        with self.assertNumQueries(1):  # gevşetilince kimlik sorgusu yok
            self.resolve(QueryFilters(year_min=2100))

    def test_mask_for_applies_exclusion_or_positive_ids(self):
        index_ids = np.array([self.old_fr.pk, self.new_fr.pk, self.new_us.pk, 9999])
        excluded = self.resolve(exclude_film_ids=[self.new_fr.pk])
        self.assertEqual(excluded.mask_for(index_ids).tolist(), [True, False, True, True])
        filtered = self.resolve(QueryFilters(year_min=2000), exclude_film_ids=[self.new_us.pk])
        self.assertEqual(filtered.mask_for(index_ids).tolist(), [False, True, False, False])
        self.assertIsNone(self.resolve().mask_for(index_ids))

    def test_allows_follows_the_same_rules(self):
        excluded = self.resolve(exclude_film_ids=[self.new_fr.pk])
        self.assertFalse(excluded.allows(self.new_fr.pk))
        self.assertTrue(excluded.allows(self.old_fr.pk))
        filtered = self.resolve(QueryFilters(year_min=2000))
        self.assertTrue(filtered.allows(self.new_us.pk))
        self.assertFalse(filtered.allows(self.old_fr.pk))
        self.assertTrue(self.resolve().allows(self.old_fr.pk))
