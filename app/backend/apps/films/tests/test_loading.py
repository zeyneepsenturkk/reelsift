import json
from datetime import UTC, datetime

import numpy as np
from django.test import TestCase

from apps.core.exceptions import ServiceError
from apps.films.models import Film, FilmChunk, FilmProfile, FilmReview
from apps.films.services import loading, sources
from apps.films.tests.base import (
    assert_vectors_equal,
    extra_record,
    fake_vector,
    make_archive_root,
    make_film,
    write_jsonl,
)


class ArchiveTestCase(TestCase):
    def setUp(self):
        self.temp, self.root, self.info = make_archive_root()
        self.addCleanup(self.temp.cleanup)

    def load_films(self, limit=None, merged_extras=None):
        summary = loading.LoadSummary()
        ids = loading.load_dataset_films(
            self.root,
            sources.load_tmdb_index(self.root),
            sources.load_plot_renewals(self.root),
            limit,
            summary,
            merged_extras,
        )
        return summary, ids


class LoadDatasetFilmsTests(ArchiveTestCase):
    def test_loads_every_row_and_matches_tmdb_by_wikidata_id_and_tmdb_id(self):
        summary, ids = self.load_films()

        self.assertEqual(ids, ["Q1", "Q2", "Q3", "Q4"])
        self.assertEqual(Film.objects.count(), 4)
        self.assertEqual(summary.dataset_films, 4)
        self.assertEqual(Film.objects.get(wikidata_id="Q1").title, "TMDB 101")
        self.assertEqual(Film.objects.get(wikidata_id="Q2").title, "Beta")
        self.assertEqual(Film.objects.get(wikidata_id="Q3").title, "TMDB 303")
        self.assertEqual(Film.objects.get(wikidata_id="Q3").runtime, 100)
        self.assertEqual(Film.objects.get(wikidata_id="Q4").tmdb_id, 404)

    def test_reports_tmdb_records_without_a_dataset_film(self):
        summary, _ids = self.load_films()

        self.assertEqual(summary.skipped["tmdb_kaydi_eslesmedi"], 1)

    def test_renewed_film_gets_new_plot_and_is_counted(self):
        summary, _ids = self.load_films()

        film = Film.objects.get(wikidata_id="Q3")
        self.assertEqual(film.plot, "A renewed story. It is longer now.")
        self.assertEqual(film.plot_source, Film.PlotSource.WIKIPEDIA_RENEWED)
        self.assertEqual(summary.renewed_films, 1)

    def test_limit_loads_only_the_first_rows(self):
        summary, ids = self.load_films(limit=2)

        self.assertEqual(ids, ["Q1", "Q2"])
        self.assertEqual(Film.objects.count(), 2)
        self.assertNotIn("tmdb_kaydi_eslesmedi", summary.skipped)

    def test_rerun_updates_instead_of_duplicating_and_keeps_card_vector(self):
        self.load_films()
        film = Film.objects.get(wikidata_id="Q1")
        film.card_embedding = fake_vector("kart")
        film.title = "Elle bozuldu"
        film.save()

        self.load_films()

        self.assertEqual(Film.objects.count(), 4)
        film.refresh_from_db()
        self.assertEqual(film.title, "TMDB 101")
        self.assertIsNotNone(film.card_embedding)

    def test_unchanged_films_are_not_rewritten_on_rerun(self):
        self.load_films()
        before = dict(Film.objects.values_list("wikidata_id", "updated_at"))

        summary, _ids = self.load_films()

        self.assertEqual(summary.skipped["film_zaten_guncel"], 4)
        self.assertEqual(dict(Film.objects.values_list("wikidata_id", "updated_at")), before)

    def test_duplicate_and_empty_dataset_ids_are_skipped(self):
        path = self.root / sources.DATASET_CSV
        lines = path.read_text(encoding="utf-8").splitlines()
        duplicate = lines[1]
        empty_id = lines[1].replace("Q1,", ",", 1)
        path.write_text("\n".join([*lines, duplicate, empty_id]) + "\n", encoding="utf-8")

        summary, ids = self.load_films()

        self.assertEqual(len(ids), 6)
        self.assertEqual(Film.objects.count(), 4)
        self.assertEqual(summary.skipped["dataset_yinelenen_wikidata_id"], 1)
        self.assertEqual(summary.skipped["dataset_wikidata_id_bos"], 1)


class PlanExtraFilmsTests(ArchiveTestCase):
    def plan(self):
        summary = loading.LoadSummary()
        identifiers = loading.index_dataset_identifiers(self.root)
        return loading.plan_extra_films(self.root, identifiers, summary), summary

    def test_separates_new_merged_and_unmatched_records(self):
        plan, summary = self.plan()

        self.assertEqual([e["tmdb_id"] for e in plan.new], [1001, 1002])
        self.assertEqual(set(plan.merged), {"Q2", "Q4"})
        self.assertEqual(plan.aliases, {"Q103": "Q4"})
        self.assertEqual(summary.skipped["ek_film_eslesmedi"], 1)
        self.assertEqual(summary.unmatched_extras, ["Q105 TMDB 1005"])

    def test_non_unique_imdb_id_is_not_matched(self):
        identifiers = loading.index_dataset_identifiers(self.root)
        identifiers.by_imdb["tt0000004"] = ["Q4", "Q3"]

        self.assertIsNone(
            loading.match_archive_film({"imdb_id": "tt0000004", "tmdb_id": 1}, identifiers)
        )

    def test_tmdb_id_match_requires_a_single_archive_film(self):
        identifiers = loading.index_dataset_identifiers(self.root)

        self.assertEqual(
            loading.match_archive_film({"imdb_id": "", "tmdb_id": 404}, identifiers), "Q4"
        )
        self.assertIsNone(loading.match_archive_film({"imdb_id": "", "tmdb_id": 9999}, identifiers))

    def test_second_record_for_the_same_film_is_skipped(self):
        path = self.root / sources.EXTRA_FILMS_JSONL
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join([*lines, lines[3]]) + "\n", encoding="utf-8")

        plan, summary = self.plan()

        self.assertEqual(summary.skipped["ek_film_ayni_filme_ikinci_kayit"], 1)
        self.assertEqual(len(plan.merged), 2)

    def test_duplicate_new_ids_inside_the_file_are_loaded_once(self):
        path = self.root / sources.EXTRA_FILMS_JSONL
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join([*lines, lines[0]]) + "\n", encoding="utf-8")

        plan, summary = self.plan()

        self.assertEqual(len(plan.new), 2)
        self.assertEqual(summary.skipped["ek_film_yinelenen_id"], 1)


class LoadExtraFilmsTests(ArchiveTestCase):
    def test_writes_only_new_extra_films(self):
        plan, _ = PlanExtraFilmsTests.plan(self)
        summary = loading.LoadSummary()

        written = loading.load_extra_films(plan, summary)

        self.assertEqual(written, ["Q100", "tmdb-1002"])
        self.assertEqual(summary.extra_films, 2)
        self.assertEqual(
            Film.objects.get(wikidata_id="Q100").plot_source, Film.PlotSource.WIKIPEDIA_ADDED
        )

    def test_rerun_does_not_duplicate(self):
        plan, _ = PlanExtraFilmsTests.plan(self)
        loading.load_extra_films(plan, loading.LoadSummary())
        loading.load_extra_films(plan, loading.LoadSummary())

        self.assertEqual(Film.objects.filter(wikidata_id__in=["Q100", "tmdb-1002"]).count(), 2)

    def test_empty_plan_writes_nothing(self):
        self.assertEqual(loading.load_extra_films(loading.ExtraPlan(), loading.LoadSummary()), [])


class MergedExtrasTests(ArchiveTestCase):
    def test_extra_record_fills_tmdb_fields_of_an_archive_film_without_tmdb(self):
        plan, _ = PlanExtraFilmsTests.plan(self)

        summary, _ids = self.load_films(merged_extras=plan.merged)

        q4 = Film.objects.get(wikidata_id="Q4")
        self.assertEqual(q4.overview, "Overview of 1003.")
        self.assertEqual(q4.poster_path, "/poster.jpg")
        self.assertEqual(q4.title, "TMDB 1003")
        self.assertEqual(q4.plot, "Another short plot here.")  # arşiv hikâyesi korunur
        self.assertEqual(summary.merged_extras, 2)

    def test_archive_film_with_its_own_tmdb_record_is_not_overridden(self):
        extra = {**PlanExtraFilmsTests.plan(self)[0].merged["Q4"]}

        self.load_films(merged_extras={"Q1": extra})

        self.assertEqual(Film.objects.get(wikidata_id="Q1").title, "TMDB 101")


class StaleChunkTests(ArchiveTestCase):
    def test_changed_plot_deletes_that_films_chunks_in_the_same_run(self):
        (self.root / sources.PLOT_RENEWALS_JSONL).write_text("", encoding="utf-8")
        loading.load_archive(self.root)
        self.assertTrue(FilmChunk.objects.filter(film__wikidata_id="Q3").exists())

        # Hikâyesi yenilenince Q3'ün eski parçaları bayatlar.
        renewal = {
            "movie_id": "Q3",
            "eski_uzunluk": 1,
            "yeni_plot": "Plot\nNew text. Longer now.",
            "yeni_uzunluk": 2,
        }
        (self.root / sources.PLOT_RENEWALS_JSONL).write_text(
            json.dumps(renewal) + "\n", encoding="utf-8"
        )
        summary = loading.load_archive(self.root)

        self.assertFalse(FilmChunk.objects.filter(film__wikidata_id="Q3").exists())
        self.assertGreater(summary.skipped["bayat_parca_silindi"], 0)
        self.assertEqual(Film.objects.get(wikidata_id="Q3").plot, "New text. Longer now.")

    def test_unchanged_plot_keeps_chunks(self):
        loading.load_archive(self.root)
        before = FilmChunk.objects.filter(film__wikidata_id="Q1").count()

        summary = loading.load_archive(self.root)

        self.assertEqual(FilmChunk.objects.filter(film__wikidata_id="Q1").count(), before)
        self.assertEqual(summary.skipped["bayat_parca_silindi"], 0)


class LoadChunksTests(ArchiveTestCase):
    def test_loads_chunks_in_order_and_skips_renewed_films(self):
        summary, ids = self.load_films()

        loading.load_chunks(self.root, ids, {"Q3"}, summary)

        q1_chunks = list(FilmChunk.objects.filter(film__wikidata_id="Q1"))
        self.assertGreater(len(q1_chunks), 1)
        self.assertEqual([c.position for c in q1_chunks], list(range(len(q1_chunks))))
        self.assertFalse(FilmChunk.objects.filter(film__wikidata_id="Q3").exists())
        self.assertEqual(FilmChunk.objects.count(), summary.chunks)
        self.assertGreater(summary.skipped["yenilenen_filmin_eski_parcasi"], 0)
        first = FilmChunk.objects.get(film__wikidata_id="Q1", position=0)
        self.assertEqual(first.text, self.info["texts"][0])
        assert_vectors_equal(first.embedding, self.info["chunk_vectors"][0])

    def test_rerun_keeps_counts_stable(self):
        summary, ids = self.load_films()
        loading.load_chunks(self.root, ids, {"Q3"}, summary)
        before = FilmChunk.objects.count()

        loading.load_chunks(self.root, ids, {"Q3"}, loading.LoadSummary())

        self.assertEqual(FilmChunk.objects.count(), before)

    def test_rerun_writes_nothing_for_unchanged_chunks_but_fixes_changed_ones(self):
        summary, ids = self.load_films()
        loading.load_chunks(self.root, ids, {"Q3"}, summary)
        FilmChunk.objects.filter(film__wikidata_id="Q1", position=0).update(text="elle bozuldu")

        again = loading.LoadSummary()
        loading.load_chunks(self.root, ids, {"Q3"}, again)

        self.assertEqual(again.chunks, 1)
        self.assertEqual(again.skipped["parca_zaten_yuklu"], summary.chunks - 1)
        first = FilmChunk.objects.get(film__wikidata_id="Q1", position=0)
        self.assertEqual(first.text, self.info["texts"][0])

    def test_limit_slice_loads_only_its_films(self):
        summary, ids = self.load_films()

        loading.load_chunks(self.root, ids[:1], set(), summary)

        self.assertEqual(set(FilmChunk.objects.values_list("film__wikidata_id", flat=True)), {"Q1"})

    def test_vector_count_mismatch_raises(self):
        summary, ids = self.load_films()
        path = self.root / sources.CHUNK_VECTOR_FILES.format(n=7)
        np.save(path, np.zeros((5, 1024), dtype=np.float16))

        with self.assertRaises(ServiceError) as ctx:
            loading.load_chunks(self.root, ids, set(), summary)

        self.assertEqual(ctx.exception.code, "chunk_misaligned")

    def test_chunk_text_that_does_not_match_the_plot_raises(self):
        summary, ids = self.load_films()
        path = self.root / sources.DATASET_CSV
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("Another short plot here.", "Changed plot."), encoding="utf-8")

        with self.assertRaises(ServiceError) as ctx:
            loading.load_chunks(self.root, ids, {"Q3"}, summary)

        self.assertEqual(ctx.exception.code, "chunk_misaligned")
        self.assertFalse(FilmChunk.objects.exists())


class LoadCardVectorsTests(ArchiveTestCase):
    def test_fills_card_vectors_for_every_dataset_film(self):
        summary, ids = self.load_films()

        loading.load_card_vectors(self.root, ids, summary)

        self.assertEqual(summary.card_vectors, 4)
        self.assertEqual(Film.objects.filter(card_embedding__isnull=True).count(), 0)
        assert_vectors_equal(
            Film.objects.get(wikidata_id="Q2").card_embedding, fake_vector("card-1")
        )

    def test_rerun_does_not_overwrite_existing_vectors(self):
        summary, ids = self.load_films()
        loading.load_card_vectors(self.root, ids, summary)
        film = Film.objects.get(wikidata_id="Q1")
        film.card_embedding = fake_vector("uretilen")
        film.save()

        again = loading.LoadSummary()
        loading.load_card_vectors(self.root, ids, again)

        self.assertEqual(again.card_vectors, 0)
        film.refresh_from_db()
        assert_vectors_equal(film.card_embedding, fake_vector("uretilen"))

    def test_misordered_ids_raise(self):
        summary, ids = self.load_films()

        with self.assertRaises(ServiceError) as ctx:
            loading.load_card_vectors(self.root, list(reversed(ids)), summary)

        self.assertEqual(ctx.exception.code, "card_misaligned")


class StaleCardTests(ArchiveTestCase):
    def prepare(self):
        summary, ids = self.load_films()
        return summary, ids

    def test_stale_film_card_is_not_loaded_from_the_file(self):
        summary, ids = self.prepare()

        loading.load_card_vectors(self.root, ids, summary, {"Q2"})

        self.assertIsNone(Film.objects.get(wikidata_id="Q2").card_embedding)
        self.assertIsNotNone(Film.objects.get(wikidata_id="Q1").card_embedding)
        self.assertEqual(summary.card_vectors, 3)

    def test_card_still_equal_to_the_file_vector_is_cleared(self):
        summary, ids = self.prepare()
        loading.load_card_vectors(self.root, ids, summary)
        self.assertIsNotNone(Film.objects.get(wikidata_id="Q2").card_embedding)

        again = loading.LoadSummary()
        loading.load_card_vectors(self.root, ids, again, {"Q2"})

        self.assertIsNone(Film.objects.get(wikidata_id="Q2").card_embedding)
        self.assertEqual(again.skipped["bayat_kart_temizlendi"], 1)

    def test_generated_card_is_kept_on_rerun(self):
        summary, ids = self.prepare()
        loading.load_card_vectors(self.root, ids, summary, {"Q2"})
        film = Film.objects.get(wikidata_id="Q2")
        film.card_embedding = fake_vector("uretilen guncel kart")
        film.save()

        again = loading.LoadSummary()
        loading.load_card_vectors(self.root, ids, again, {"Q2"})

        film.refresh_from_db()
        assert_vectors_equal(film.card_embedding, fake_vector("uretilen guncel kart"))
        self.assertEqual(again.skipped["bayat_kart_temizlendi"], 0)


class LoadProfilesTests(ArchiveTestCase):
    def test_build_profile_drops_moods_outside_the_allowed_list(self):
        film = make_film("Q1")
        summary = loading.LoadSummary()

        profile = loading.build_profile(
            film.pk, {"mood": ["warm", "bittersweet", "dark"], "tr_pitch": ""}, summary
        )

        self.assertEqual(profile.moods, ["warm"])
        self.assertEqual(summary.dropped_moods, 2)
        self.assertEqual(profile.tr_pitch, "")
        self.assertEqual(profile.evidence, "")

    def test_loads_profiles_and_reports_unmatched_ids(self):
        make_film("Q1")
        make_film("Q2")
        make_film("Q100")
        summary = loading.LoadSummary()

        loading.load_profiles(self.root, {"Q1", "Q2", "Q100"}, False, summary)

        self.assertEqual(FilmProfile.objects.count(), 3)
        self.assertEqual(summary.skipped["profil_film_bulunamadi"], 3)  # Q88, Q4, Q103
        self.assertEqual(summary.dropped_moods, 3)
        profile = FilmProfile.objects.get(film__wikidata_id="Q1")
        self.assertEqual(profile.moods, ["warm", "tense"])
        self.assertEqual(profile.setting_place, "Paris")
        self.assertEqual(profile.evidence, FilmProfile.Evidence.RICH)
        self.assertEqual(FilmProfile.objects.get(film__wikidata_id="Q2").evidence, "")

    def test_alias_profile_replaces_the_archive_films_own_profile(self):
        make_film("Q4")
        summary = loading.LoadSummary()

        loading.load_profiles(self.root, {"Q4"}, False, summary, {"Q103": "Q4"})

        self.assertEqual(FilmProfile.objects.get(film__wikidata_id="Q4").tone, "Extra tone.")
        self.assertEqual(summary.skipped["profil_ek_kayitla_degistirildi"], 1)

    def test_limit_marks_out_of_scope_profiles_separately(self):
        make_film("Q1")
        summary = loading.LoadSummary()

        loading.load_profiles(self.root, {"Q1"}, True, summary)

        self.assertEqual(summary.skipped["profil_kapsam_disi_limit"], 5)

    def test_rerun_updates_in_place(self):
        make_film("Q1")
        loading.load_profiles(self.root, {"Q1"}, False, loading.LoadSummary())
        FilmProfile.objects.update(tone="elle değişti")

        loading.load_profiles(self.root, {"Q1"}, False, loading.LoadSummary())

        self.assertEqual(FilmProfile.objects.count(), 1)
        self.assertEqual(FilmProfile.objects.get().tone, "A warm tone.")


class LoadReviewsTests(ArchiveTestCase):
    def test_parse_review_time(self):
        self.assertEqual(
            loading.parse_review_time("2024-07-07T04:49:42Z"),
            datetime(2024, 7, 7, 4, 49, 42, tzinfo=UTC),
        )
        self.assertIsNone(loading.parse_review_time("bozuk"))
        self.assertIsNone(loading.parse_review_time(None))

    def test_loads_reviews_and_counts_orphans(self):
        make_film("Q1")
        summary = loading.LoadSummary()

        loading.load_reviews(self.root, {"Q1"}, False, summary)

        self.assertEqual(FilmReview.objects.count(), 2)
        self.assertEqual(summary.reviews, 2)
        self.assertEqual(summary.review_films, 1)
        self.assertEqual(summary.skipped["inceleme_film_bulunamadi"], 1)
        self.assertEqual(FilmReview.objects.get(url="https://x.test/r/1").rating, 9.0)
        self.assertIsNone(FilmReview.objects.get(url="https://x.test/r/2").published_at)

    def test_rerun_does_not_duplicate_reviews(self):
        make_film("Q1")
        loading.load_reviews(self.root, {"Q1"}, False, loading.LoadSummary())
        loading.load_reviews(self.root, {"Q1"}, False, loading.LoadSummary())

        self.assertEqual(FilmReview.objects.count(), 2)


class AliasNotAppliedTests(ArchiveTestCase):
    def test_profile_is_not_replaced_when_extra_data_was_not_applied(self):
        # Q3'ün kendi TMDB kaydı var: ek kaydın verisi uygulanmaz, profili de değişmez.
        extra = extra_record(1006, "Q106", in_archive_by_id=True, imdb_id="tt0000003")
        with open(self.root / sources.EXTRA_FILMS_JSONL, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(extra) + "\n")
        profile = {"tone": "Q3 own tone."}
        with open(self.root / sources.PROFILES_JSONL, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"id": "Q3", "p": profile}) + "\n")
            handle.write(json.dumps({"id": "Q106", "p": {"tone": "Extra tone."}}) + "\n")

        summary = loading.load_archive(self.root)

        self.assertEqual(FilmProfile.objects.get(film__wikidata_id="Q3").tone, "Q3 own tone.")
        self.assertNotIn("Q106", summary.merged_extra_ids)
        self.assertEqual(Film.objects.get(wikidata_id="Q3").title, "TMDB 303")
        self.assertEqual(FilmProfile.objects.get(film__wikidata_id="Q4").tone, "Extra tone.")


class LoadArchiveTests(ArchiveTestCase):
    def counts(self):
        return (
            Film.objects.count(),
            FilmChunk.objects.count(),
            FilmProfile.objects.count(),
            FilmReview.objects.count(),
            Film.objects.filter(card_embedding__isnull=False).count(),
        )

    def test_full_load_then_second_load_leaves_counts_unchanged(self):
        summary = loading.load_archive(self.root)

        first = self.counts()
        self.assertEqual(first[0], 6)  # 4 veri seti + 2 ek film
        self.assertEqual(summary.dataset_films, 4)
        self.assertEqual(summary.extra_films, 2)
        self.assertEqual(first[2], 4)  # Q1, Q2, Q100, Q4 (ek kaydın profiliyle)
        self.assertEqual(first[3], 2)
        # Kartı dolu: Q1, Q3 (Q2 ve Q4'ün dosya kartı bayat sayılır).
        self.assertEqual(first[4], 2)
        # Hikâyesi olup parçası olmayanlar: yenilenen Q3 ve ek film Q100 (embed_missing üretecek).
        self.assertEqual(Film.objects.filter(chunks__isnull=True).exclude(plot="").count(), 2)

        loading.load_archive(self.root)

        self.assertEqual(self.counts(), first)

    def test_limit_load_skips_extra_films(self):
        loading.load_archive(self.root, limit=2)

        self.assertEqual(self.counts()[0], 2)
        self.assertFalse(Film.objects.filter(wikidata_id="Q100").exists())

    def test_summary_text_lists_counts_and_skip_reasons(self):
        summary = loading.load_archive(self.root)

        self.assertIn("film=6", summary.describe())
        self.assertIn("ek_film_eslesmedi=1", summary.describe())
        self.assertEqual(
            set(summary.seconds),
            {"filmler", "parcalar", "kart_vektorleri", "profil_ve_incelemeler"},
        )

    def test_missing_source_stops_the_load(self):
        (self.root / sources.PROFILES_JSONL).unlink()

        with self.assertRaises(ServiceError) as ctx:
            loading.load_archive(self.root)

        self.assertEqual(ctx.exception.code, "source_file_missing")


class CreditsLoadingTests(ArchiveTestCase):
    def write_credits(self, records):
        write_jsonl(self.root / sources.CREDITS_JSONL, records)

    def credits_row(self, wikidata_id, directors=("New Director",), actors=("New Actor",)):
        return {
            "wikidata_id": wikidata_id,
            "tmdb_id": 1,
            "directors": list(directors),
            "actors": list(actors),
            "status": "ok",
        }

    def test_fills_empty_fields_of_dataset_and_extra_films(self):
        # Q2: veri setinde künyesi boş; Q100: yeni ek film (künyesi hep boş başlar).
        self.write_credits([self.credits_row("Q2"), self.credits_row("Q100", ("D2",), ("A2",))])

        summary = loading.load_archive(self.root)

        q2 = Film.objects.get(wikidata_id="Q2")
        self.assertEqual((q2.directors, q2.actors), (["New Director"], ["New Actor"]))
        q100 = Film.objects.get(wikidata_id="Q100")
        self.assertEqual((q100.directors, q100.actors), (["D2"], ["A2"]))
        self.assertEqual((summary.credits_films, summary.credits_written), (2, 2))
        self.assertEqual(summary.credits_unmatched, 0)
        self.assertIn(
            "künye (künyeli film=2, bu koşuda künye yüzünden yazılan=2, zaten dolu=0, "
            "eşleşmeyen=0)",
            summary.describe(),
        )

    def test_filled_fields_are_not_overwritten(self):
        self.write_credits([self.credits_row("Q1")])

        summary = loading.load_archive(self.root)

        q1 = Film.objects.get(wikidata_id="Q1")
        self.assertEqual(q1.directors, ["Director One"])
        self.assertEqual(q1.actors, ["Actor One", "Actor Two"])
        self.assertEqual(summary.credits_films, 0)
        self.assertEqual(summary.credits_already_filled, 1)

    def test_unmatched_and_invalid_rows_are_counted_and_load_continues(self):
        self.write_credits([self.credits_row("Q2"), self.credits_row("Q404")])
        with open(self.root / sources.CREDITS_JSONL, "a", encoding="utf-8") as handle:
            handle.write("{bozuk\n")

        with self.assertLogs("apps.films.services.loading", level="WARNING") as logs:
            summary = loading.load_archive(self.root)

        self.assertEqual(summary.credits_unmatched, 1)
        self.assertEqual(summary.skipped["kunye_bozuk_satir"], 1)
        self.assertEqual(summary.credits_films, 1)
        self.assertTrue(any("Q404" in line for line in logs.output))
        self.assertEqual(Film.objects.count(), 6)

    def test_missing_credits_file_does_not_stop_the_load(self):
        self.assertFalse((self.root / sources.CREDITS_JSONL).exists())

        summary = loading.load_archive(self.root)

        self.assertEqual(Film.objects.count(), 6)
        self.assertEqual(summary.credits_films, 0)
        self.assertEqual(summary.credits_unmatched, 0)
        self.assertIn("künye dosyası bulunamadı", summary.describe())

    def test_missing_credits_file_logs_a_warning_about_the_consequence(self):
        with self.assertLogs("apps.films.services.sources", level="WARNING") as logs:
            sources.load_credits(self.root)

        self.assertIn("boşaltır", logs.output[0])

    def test_limit_load_does_not_count_out_of_scope_credits_as_unmatched(self):
        self.write_credits([self.credits_row("Q2"), self.credits_row("Q100")])

        summary = loading.load_archive(self.root, limit=2)

        self.assertEqual(summary.credits_films, 1)
        self.assertEqual(summary.credits_unmatched, 0)

    def test_second_run_rewrites_nothing(self):
        self.write_credits([self.credits_row("Q2"), self.credits_row("Q100")])
        first = loading.load_archive(self.root)
        before = dict(Film.objects.values_list("wikidata_id", "updated_at"))

        summary = loading.load_archive(self.root)

        self.assertEqual((first.credits_films, first.credits_written), (2, 2))
        self.assertEqual((summary.credits_films, summary.credits_written), (2, 0))
        self.assertNotIn("künye dosyası bulunamadı", summary.describe())
        self.assertEqual(summary.skipped["film_zaten_guncel"], 6)
        self.assertEqual(dict(Film.objects.values_list("wikidata_id", "updated_at")), before)
        self.assertEqual(Film.objects.get(wikidata_id="Q2").directors, ["New Director"])

    def test_credits_do_not_touch_vectors_or_chunks(self):
        loading.load_archive(self.root)
        Film.objects.filter(wikidata_id="Q2").update(card_embedding=fake_vector("kart"))
        chunks_before = list(FilmChunk.objects.order_by("pk").values_list("pk", "updated_at"))
        cards_before = Film.objects.filter(card_embedding__isnull=False).count()
        self.write_credits([self.credits_row("Q2")])

        summary = loading.load_archive(self.root)

        q2 = Film.objects.get(wikidata_id="Q2")
        self.assertEqual(q2.directors, ["New Director"])
        assert_vectors_equal(q2.card_embedding, fake_vector("kart"))
        self.assertEqual(Film.objects.filter(card_embedding__isnull=False).count(), cards_before)
        self.assertEqual(
            list(FilmChunk.objects.order_by("pk").values_list("pk", "updated_at")), chunks_before
        )
        self.assertEqual((summary.chunks, summary.card_vectors), (0, 0))
