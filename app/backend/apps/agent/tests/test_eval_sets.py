import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from apps.agent.services import eval_sets
from apps.agent.tests.eval_base import (
    KONU_ROWS,
    TONE_TEXT,
    TURKISH,
    known_text,
    write_json,
    write_known50,
    write_konu30,
    write_tone25,
)
from apps.core.exceptions import ServiceError
from apps.films.tests.base import make_film


class EvalSetLoadingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.films = [
            make_film(f"Q{n}", title=f"Gizli Hedef Adı {n}", vote_count=1500 if n < 10 else 100)
            for n in range(50)
        ]

    def data(self):
        """Geçici veri klasörü; `SEARCH["eval_data_dir"]` ona bakar."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        merged = {**settings.SEARCH, "eval_data_dir": directory.name}
        override = override_settings(SEARCH=merged)
        override.enable()
        self.addCleanup(override.disable)
        return Path(directory.name)

    def test_known50_text_is_the_recorded_turkish_recipe_and_nothing_else(self):
        write_known50(self.data(), [film.wikidata_id for film in self.films])

        requests = eval_sets.load_known50_requests()

        self.assertEqual(len(requests), 50)
        self.assertEqual(requests[7].text, known_text(7))
        self.assertEqual(requests[7].key, "known50:07")
        self.assertEqual(requests[7].target_wikidata_id, "Q7")
        self.assertEqual(requests[7].target_film_id, self.films[7].pk)
        self.assertTrue(requests[7].known)
        self.assertFalse(requests[20].known)  # oy sayısı 1000'in altında

    def test_no_answer_key_information_leaks_into_any_request_text(self):
        root = self.data()
        write_known50(root, [film.wikidata_id for film in self.films])
        write_konu30(root)
        write_tone25(root)

        requests = (
            eval_sets.load_known50_requests()
            + eval_sets.load_konu30_requests()
            + eval_sets.load_tone25_requests()
        )

        secrets = [film.wikidata_id for film in self.films] + [film.title for film in self.films]
        secrets += ["bleak", "Q40", "relevance", "genome"]
        for request in requests:
            for secret in secrets:
                self.assertNotIn(secret, request.text, f"{request.key}: {secret}")

    def test_konu30_reads_cp1254_without_breaking_turkish_letters(self):
        write_konu30(self.data())

        requests = eval_sets.load_konu30_requests()

        self.assertEqual(requests[0].text, KONU_ROWS[0]["konu_tr"])
        self.assertIn(TURKISH, requests[0].text)
        self.assertEqual(requests[0].key, "konu30:konu_01")
        self.assertEqual(requests[0].answer_qids, frozenset({"Q1", "Q2", "Q40", "Q999"}))
        # Q999 için veritabanında film yok: kapsam her konu için sayılır.
        self.assertEqual(requests[0].answer_in_db, 3)
        self.assertEqual(requests[1].answer_in_db, 3)
        self.assertEqual(requests[1].answer_qids, frozenset({"Q1", "Q2", "Q40"}))

    def test_tone25_uses_turkish_text_and_the_genome_answer_key(self):
        write_tone25(self.data())

        requests = eval_sets.load_tone25_requests()

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].text, TONE_TEXT)  # istek_en değil, istek_tr
        self.assertEqual(requests[0].key, "tone25:ton_01")
        by_id = {film.wikidata_id: film.pk for film in self.films}
        self.assertEqual(requests[0].relevant, frozenset({by_id["Q1"], by_id["Q2"]}))
        self.assertEqual(set(requests[0].gains), {by_id["Q1"], by_id["Q2"], by_id["Q3"]})

    def test_missing_data_is_a_clear_error(self):
        self.data()

        with self.assertRaises(ServiceError) as ctx:
            eval_sets.load_konu30_requests()

        self.assertEqual(ctx.exception.code, "eval_data_missing")

    def test_konu30_row_without_answers_is_rejected(self):
        root = self.data()
        write_json(
            root / eval_sets.KONU_LISTS,
            [{"id": "konu_01", "konu_tr": "bir konu", "arsivde_bulunan_qidler": []}],
            encoding="cp1254",
        )

        with self.assertRaises(ServiceError) as ctx:
            eval_sets.load_konu30_requests()

        self.assertEqual(ctx.exception.code, "eval_data_mismatch")

    def test_load_requests_samples_each_set_separately(self):
        root = self.data()
        write_known50(root, [film.wikidata_id for film in self.films])
        write_konu30(root)

        requests = eval_sets.load_requests(["known50", "konu30"], 2)

        self.assertEqual([r.set_name for r in requests], ["known50"] * 2 + ["konu30"] * 2)
