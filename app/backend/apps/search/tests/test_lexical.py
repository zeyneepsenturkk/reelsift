import json
import threading
import time
from pathlib import Path
from unittest import mock

import numpy as np
from django.test import SimpleTestCase, TestCase

from apps.search.services import lexical
from apps.search.tests.base import make_film, search_settings


class LexicalIndexTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.whale = make_film(
            "Q1",
            title="Moby Quest",
            plot="A captain hunts a giant white whale across the stormy ocean. " * 8,
            overview="Obsession at sea.",
            keywords=("revenge",),
        )
        cls.heist = make_film(
            "Q2",
            title="The Vault Job",
            plot="A crew plans a bank robbery and the vault is full of gold. " * 8,
            overview="Heist.",
            keywords=("bank robbery", "betrayal"),
        )
        cls.quiet = make_film("Q3", title="Quiet Days", plot="A farmer waits for rain. " * 20)

    def test_build_writes_index_files_and_reports_counts(self):
        with search_settings() as directory:
            summary = lexical.build_index()
            self.assertEqual(summary["film_count"], 3)
            base = Path(directory) / "lexical"
            for name in ("a", "b", "film_ids.npy", "titles.json", "meta.json"):
                self.assertTrue((base / name).exists(), name)
            self.assertEqual(json.loads((base / "meta.json").read_text())["film_count"], 3)

    def test_plot_index_ranks_the_matching_film_first(self):
        with search_settings():
            index = lexical.get_index()  # dosya yok: kendiliğinden kurulur
            scores = index.scores("a", "white whale hunting")
            self.assertEqual(index.film_ids[scores.argmax()], self.whale.pk)

    def test_stemming_and_stopwords(self):
        with search_settings():
            index = lexical.get_index()
            scores = index.scores("a", "the robberies")
            self.assertEqual(index.film_ids[scores.argmax()], self.heist.pk)

    def test_second_index_also_covers_title_overview_and_keywords(self):
        with search_settings():
            index = lexical.get_index()
            by_title = index.scores("b", "Moby Quest")
            self.assertEqual(index.film_ids[by_title.argmax()], self.whale.pk)
            self.assertEqual(index.scores("a", "Moby").max(), 0)
            by_keyword = index.scores("b", "betrayal")
            self.assertEqual(index.film_ids[by_keyword.argmax()], self.heist.pk)

    def test_query_with_only_stopwords_scores_zero(self):
        with search_settings():
            index = lexical.get_index()
            self.assertEqual(float(index.scores("a", "the of and").max()), 0.0)

    def test_titles_are_available_for_matching(self):
        with search_settings():
            index = lexical.get_index()
            self.assertEqual(index.titles["vault job"], [(self.heist.pk, 2000)])

    def test_index_is_loaded_once_and_stale_index_is_logged(self):
        with search_settings():
            lexical.build_index()
            make_film("Q4", title="Late Arrival")
            with self.assertLogs("apps.search.services.lexical", level="WARNING") as logs:
                first = lexical.get_index()
            self.assertIn("eski", logs.output[0])
            self.assertIs(lexical.get_index(), first)

    def test_rebuild_replaces_loaded_index(self):
        with search_settings():
            first = lexical.get_index()
            make_film("Q4", title="Late Arrival")
            lexical.build_index()
            second = lexical.get_index()
            self.assertIsNot(first, second)
            self.assertEqual(second.film_count, 4)


class LexicalConcurrencyTests(SimpleTestCase):
    def test_concurrent_first_requests_load_the_index_once(self):
        calls = []

        def slow_loader():
            calls.append(threading.get_ident())
            time.sleep(0.2)  # ikinci iş parçacığı yükleme sürerken gelsin
            return lexical.LexicalIndex(np.array([1]), {}, {}, 1)

        results = []
        with (
            search_settings(),
            mock.patch.object(lexical, "index_exists", return_value=True),
            mock.patch.object(lexical, "_load_from_disk", side_effect=slow_loader),
            mock.patch.object(lexical, "_warn_if_stale"),
        ):
            threads = [
                threading.Thread(target=lambda: results.append(lexical.get_index()))
                for _ in range(4)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len({id(index) for index in results}), 1)
        self.assertEqual(len(results), 4)
