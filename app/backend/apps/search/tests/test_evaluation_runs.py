import csv
import json
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from django.test import TestCase

from apps.core.exceptions import ServiceError
from apps.search.services import evaluation
from apps.search.tests.base import fake_models, make_film, search_settings


def write_json(path: Path, data, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(data, ensure_ascii=False).encode(encoding))


class Known50RunTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.films = [
            make_film(
                f"Q{n}",
                word="dream" if n % 2 == 0 else "ocean",
                title=f"Film number {n}",
                vote_count=1500 if n < 10 else 100,
            )
            for n in range(50)
        ]

    def write_data(self, root: Path, *, mismatch=False):
        base = root / evaluation.KNOWN_DIR
        targets = [
            {"id": film.wikidata_id, "tr": f"tarif {n}"} for n, film in enumerate(self.films)
        ]
        write_json(base / "b.json", targets[:25])
        write_json(base / "b2.json", targets[25:])
        rows = [
            {
                "kind": "b",
                "n": n,
                "tr": f"tarif {n}" if not (mismatch and n == 3) else "başka",
                "out": {
                    "en_query": "a dream story" if n % 2 == 0 else "ocean tale",
                    "hyde": "dream" if n % 2 == 0 else "ocean",
                    "titles": [{"title": f"Film number {n}", "year": 2000}],
                    "filters": {"year_min": 2050},
                },
            }
            for n in range(50)
        ]
        write_json(base / "haiku_out.json", {"R": rows[::-1]})  # sıra karışık: n ile sıralanmalı
        write_json(base / "kor_tarifler.json", [{"tr": f"tarif {n}"} for n in range(50)])

    def test_each_target_is_found_and_groups_are_reported(self):
        with tempfile.TemporaryDirectory() as data, search_settings(eval_data_dir=data):
            self.write_data(Path(data))
            with fake_models():
                result = evaluation.run_known50(["A", "B"], [0.0, 0.5], "exact", False)
        arms = [row["arm"] for row in result["rows"]]
        self.assertEqual(
            arms,
            [
                "RRF sırası",
                "belge A, harman 0",
                "belge A, harman 0.5",
                "belge B, harman 0",
                "belge B, harman 0.5",
            ],
        )
        everything = result["rows"][0]["all"]
        self.assertEqual(everything["n"], 50)
        self.assertEqual(everything["R@50"], 1.0)  # model önerisi (g) hedefi her zaman getirir
        self.assertEqual(result["rows"][0]["known"]["n"], 10)
        self.assertEqual(result["rows"][0]["less_known"]["n"], 40)
        self.assertEqual(len(result["per_query"]), 50)
        self.assertGreater(result["gather_seconds"]["median"], 0)

    def test_filters_are_ignored_unless_requested(self):
        with tempfile.TemporaryDirectory() as data, search_settings(eval_data_dir=data):
            self.write_data(Path(data))
            items = evaluation.load_known50(with_filters=False)
            self.assertIsNone(items[0].query.filters.year_min)
            items = evaluation.load_known50(with_filters=True)
            self.assertEqual(items[0].query.filters.year_min, 2050)

    def test_description_mismatch_is_an_error(self):
        with tempfile.TemporaryDirectory() as data, search_settings(eval_data_dir=data):
            self.write_data(Path(data), mismatch=True)
            with self.assertRaises(ServiceError):
                evaluation.load_known50()

    def test_missing_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as data, search_settings(eval_data_dir=data):
            with self.assertRaises(ServiceError) as ctx:
                evaluation.load_known50()
        self.assertEqual(ctx.exception.code, "eval_data_missing")


class Tone25RunTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bleak = make_film("Q1", word="dream", title="Bleak One")
        cls.also = make_film("Q2", word="dream", title="Bleak Two")
        cls.cheery = make_film("Q3", word="ocean", title="Cheery")
        cls.unjudged = make_film("Q4", word="dream", title="Not In Genome")

    def write_data(self, root: Path, relevant_count: int):
        write_json(
            root / evaluation.TONE_REQUESTS,
            [
                {
                    "id": "ton_01",
                    "istek_en": "bleak films",
                    "etiketler": ["bleak"],
                    "ek_kisit": None,
                    "uygun_qidler_sayisi": relevant_count,
                }
            ],
            encoding="cp1254",
        )
        write_json(
            root / evaluation.TONE_PARSED,
            [{"id": "ton_01", "out": {"en_query": "dream bleak", "hyde": "dream", "titles": []}}],
        )
        table = pa.table(
            {
                "QID": ["Q1", "Q2", "Q3"],
                "tag": ["bleak", "bleak", "bleak"],
                "relevance": [0.95, 0.5, 0.1],
            }
        )
        (root / "degerlendirme").mkdir(parents=True, exist_ok=True)
        pq.write_table(table, root / evaluation.GENOME_PARQUET)
        (root / "dataset").mkdir(parents=True, exist_ok=True)
        with open(root / evaluation.DATASET_CSV, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["movie_id", "genre", "country", "year"])
            for key in ("Q1", "Q2", "Q3"):
                writer.writerow([key, "drama film", "France", "2000"])

    def test_pool_is_limited_to_genome_films_and_metrics_are_computed(self):
        with tempfile.TemporaryDirectory() as data, search_settings(eval_data_dir=data):
            self.write_data(Path(data), relevant_count=1)
            with fake_models():
                result = evaluation.run_tone25(["A"], [0.0], "exact", "genome")
        self.assertEqual(result["n"], 1)
        rrf, doc_a = result["rows"]
        self.assertEqual(rrf["arm"], "RRF sırası")
        # Havuzda 3 yargılı film var; uygun olan tek film ilk 10'da: P@10 = 1/10.
        self.assertAlmostEqual(rrf["P@10"], 0.1)
        self.assertEqual(rrf["R@50"], 1.0)
        self.assertGreater(rrf["nDCG@10"], 0.5)
        self.assertEqual(result["per_query"][0]["pool_size"], 3)
        self.assertEqual(doc_a["arm"], "belge A, harman 0")

    def test_answer_key_that_does_not_match_the_expected_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as data, search_settings(eval_data_dir=data):
            self.write_data(Path(data), relevant_count=2)
            with self.assertRaises(ServiceError) as ctx:
                evaluation.load_tone25()
        self.assertEqual(ctx.exception.code, "eval_data_mismatch")
