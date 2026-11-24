import json
import pickle
import tempfile
from pathlib import Path

import numpy as np
from django.test import SimpleTestCase

from apps.core.exceptions import ServiceError
from apps.films.services import sources
from apps.films.tests.base import make_archive_root, write_jsonl


class SourceFileTests(SimpleTestCase):
    def setUp(self):
        self.temp, self.root, self.info = make_archive_root()
        self.addCleanup(self.temp.cleanup)

    def test_iter_dataset_rows_respects_limit(self):
        self.assertEqual(len(list(sources.iter_dataset_rows(self.root))), 4)
        self.assertEqual(
            [r["movie_id"] for r in sources.iter_dataset_rows(self.root, 2)], ["Q1", "Q2"]
        )

    def test_missing_file_raises_service_error(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(ServiceError) as ctx:
                list(sources.iter_dataset_rows(Path(empty)))

        self.assertEqual(ctx.exception.code, "source_file_missing")

    def test_invalid_json_line_raises_service_error(self):
        (self.root / sources.PLOT_RENEWALS_JSONL).write_text("{bozuk\n", encoding="utf-8")

        with self.assertRaises(ServiceError) as ctx:
            sources.load_plot_renewals(self.root)

        self.assertEqual(ctx.exception.code, "source_file_invalid")

    def test_read_dataset_rows_by_id_returns_only_requested_rows(self):
        rows = sources.read_dataset_rows_by_id(self.root, {"Q2", "Q4", "Q404"})

        self.assertEqual(set(rows), {"Q2", "Q4"})
        self.assertEqual(sources.read_dataset_rows_by_id(self.root, set()), {})

    def test_tmdb_index_maps_by_each_wikidata_id_and_tmdb_id(self):
        index = sources.load_tmdb_index(self.root)

        self.assertEqual(index.record_count, 3)
        self.assertEqual(index.by_wikidata_id["Q1"]["tmdb_id"], 101)
        self.assertEqual(index.by_wikidata_id["Q555"], index.by_wikidata_id["Q556"])
        self.assertEqual(index.by_tmdb_id[303]["tmdb_id"], 303)
        self.assertEqual(index.by_tmdb_id[101]["countries"], ["United States of America"])
        self.assertNotIn("spoken_languages", index.by_tmdb_id[101])

    def test_small_jsonl_readers(self):
        self.assertEqual(
            sources.load_plot_renewals(self.root)["Q3"], "Plot\nA renewed story. It is longer now."
        )
        self.assertEqual(len(list(sources.iter_extra_films(self.root))), 5)
        self.assertEqual(len(list(sources.iter_reviews(self.root))), 2)
        self.assertEqual(len(list(sources.iter_profiles(self.root))), 6)

    def test_dataset_ids_alignment_file(self):
        self.assertEqual(sources.load_dataset_ids_alignment(self.root), ["Q1", "Q2", "Q3", "Q4"])

    def test_chunk_texts_match_film_rows(self):
        film_rows, texts = sources.load_chunk_texts(self.root)

        self.assertEqual(film_rows.tolist(), self.info["film_rows"])
        self.assertEqual(texts, self.info["texts"])

    def test_chunk_texts_with_different_lengths_raise(self):
        with open(self.root / sources.CHUNK_TEXTS_PKL, "wb") as handle:
            pickle.dump((np.array([0, 1]), ["only one text"]), handle)

        with self.assertRaises(ServiceError) as ctx:
            sources.load_chunk_texts(self.root)

        self.assertEqual(ctx.exception.code, "chunk_misaligned")

    def test_chunk_vectors_read_spans_files(self):
        vectors = sources.open_chunk_vectors(self.root)

        self.assertEqual(vectors.total, len(self.info["texts"]))
        np.testing.assert_array_equal(vectors.read(0, vectors.total), self.info["chunk_vectors"])
        np.testing.assert_array_equal(vectors.read(2, 5), self.info["chunk_vectors"][2:5])
        self.assertEqual(len(vectors.read(3, 3)), 0)

    def test_chunk_vector_file_missing_raises(self):
        (self.root / sources.CHUNK_VECTOR_FILES.format(n=3)).unlink()

        with self.assertRaises(ServiceError) as ctx:
            sources.open_chunk_vectors(self.root)

        self.assertEqual(ctx.exception.code, "source_file_missing")

    def test_card_vectors_are_memory_mapped(self):
        cards = sources.open_card_vectors(self.root)

        self.assertEqual(cards.shape, (4, 1024))
        self.assertIsInstance(cards, np.memmap)

    def test_card_vectors_missing_file_raises(self):
        (self.root / sources.CARD_VECTORS_NPY).unlink()

        with self.assertRaises(ServiceError) as ctx:
            sources.open_card_vectors(self.root)

        self.assertEqual(ctx.exception.code, "source_file_missing")

    def test_credits_missing_file_returns_empty_index(self):
        index = sources.load_credits(self.root)

        self.assertEqual(index.by_wikidata_id, {})
        self.assertEqual(index.invalid_rows, 0)

    def test_credits_are_read_by_wikidata_id(self):
        write_jsonl(
            self.root / sources.CREDITS_JSONL,
            [{"wikidata_id": "Q2", "directors": ["A B"], "actors": [" C D ", ""], "status": "ok"}],
        )

        index = sources.load_credits(self.root)

        self.assertEqual(index.by_wikidata_id, {"Q2": {"directors": ["A B"], "actors": ["C D"]}})

    def test_credits_count_invalid_and_duplicate_rows_without_stopping(self):
        good = {"wikidata_id": "Q2", "directors": ["A"], "actors": []}
        lines = [
            "{bozuk",
            json.dumps({"directors": ["A"], "actors": []}),
            json.dumps({"wikidata_id": "Q3", "directors": "A", "actors": []}),
            json.dumps({"wikidata_id": "Q4", "directors": [1], "actors": []}),
            json.dumps(["liste"]),
            json.dumps(good),
            json.dumps({**good, "directors": ["Başka"]}),
        ]
        (self.root / sources.CREDITS_JSONL).write_text("\n".join(lines) + "\n", encoding="utf-8")

        index = sources.load_credits(self.root)

        self.assertEqual(index.invalid_rows, 5)
        self.assertEqual(index.duplicate_rows, 1)
        self.assertEqual(index.by_wikidata_id, {"Q2": {"directors": ["A"], "actors": []}})
