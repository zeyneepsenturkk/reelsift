"""Türk filmleri: ikinci dosyalar, Türkçe hikâye, Türkçe özet yedeği, ham kimlik adları."""

from django.test import SimpleTestCase, TestCase

from apps.films.models import Film, FilmChunk, FilmProfile, FilmReview
from apps.films.services import embedding, film_records, loading, sources
from apps.films.tests.base import (
    dataset_row,
    extra_record,
    fake_embedder,
    make_archive_root,
    make_film,
    write_jsonl,
)

TURKISH_PLOT = "Konu\nBir adam kasabaya gelir ve eski dostunu arar. Sonunda yalnız kalır."
PROFILE = {"themes": ["yalnızlık"], "tone": "Sessiz.", "for_viewers": "Sabırlı izleyici."}


def turkish_film(tmdb_id: int, wikidata_id: str | None, **overrides) -> dict:
    fields = {
        "original_language": "tr",
        "plot": "Bir adam kasabaya gelir ve eski dostunu arar. Sonunda yalnız kalır.",
        "plot_kaynagi": "trwiki:Konu",
        "wikipedia_link": f"https://tr.wikipedia.org/wiki/Film_{tmdb_id}",
    }
    fields.update(overrides)
    return extra_record(tmdb_id, wikidata_id, **fields)


class TurkishFilesCase(TestCase):
    def setUp(self):
        self.temp, self.root, self.info = make_archive_root()
        self.addCleanup(self.temp.cleanup)

    def write_turkish(self, films=None, credits=None, profiles=None, reviews=None):
        for relative, records in (
            (sources.TURKISH_FILMS_JSONL, films),
            (sources.TURKISH_CREDITS_JSONL, credits),
            (sources.TURKISH_PROFILES_JSONL, profiles),
            (sources.TURKISH_REVIEWS_JSONL, reviews),
        ):
            if records is not None:
                write_jsonl(self.root / relative, records)


class SecondFileReadingTests(TurkishFilesCase):
    def test_second_files_are_read_after_the_first_ones(self):
        self.write_turkish(
            films=[turkish_film(2001, "Q200")],
            profiles=[{"id": "Q200", "p": PROFILE, "kaynak": "toplu"}],
            reviews=[{"movie_id": "Q200", "incelemeler": []}],
        )

        films = [film["wikidata_id"] for film in sources.iter_extra_films(self.root)]
        profiles = [record["id"] for record in sources.iter_profiles(self.root)]
        reviews = [record["movie_id"] for record in sources.iter_reviews(self.root)]

        self.assertEqual(films[-1], "Q200")
        self.assertEqual(len(films), 6)
        self.assertEqual(profiles[-1], "Q200")
        self.assertEqual(len(profiles), 7)
        self.assertEqual(reviews[-1], "Q200")
        self.assertEqual(len(reviews), 3)

    def test_missing_second_files_are_skipped_with_an_info_log(self):
        with self.assertLogs("apps.films.services.sources", level="INFO") as logs:
            films = list(sources.iter_extra_films(self.root))
            credits = sources.load_credits(self.root)

        self.assertEqual(len(films), 5)
        self.assertEqual(credits.by_wikidata_id, {})
        self.assertTrue(any(sources.TURKISH_FILMS_JSONL in line for line in logs.output))
        self.assertTrue(any(sources.TURKISH_CREDITS_JSONL in line for line in logs.output))

    def test_same_profile_and_review_id_in_both_files_keeps_the_first(self):
        self.write_turkish(
            profiles=[{"id": "Q1", "p": {"tone": "Ikinci."}}],
            reviews=[{"movie_id": "Q1", "incelemeler": []}],
        )

        profiles = list(sources.iter_profiles(self.root))
        reviews = list(sources.iter_reviews(self.root))

        self.assertEqual(len(profiles), 6)
        self.assertNotIn("Ikinci.", str([p["p"] for p in profiles]))
        self.assertEqual(len(reviews), 2)

    def test_credits_of_both_files_are_merged_and_the_first_wins(self):
        write_jsonl(
            self.root / sources.CREDITS_JSONL,
            [{"wikidata_id": "Q2", "directors": ["Birinci"], "actors": []}],
        )
        self.write_turkish(
            credits=[
                {"wikidata_id": "Q2", "directors": ["Ikinci"], "actors": []},
                {"wikidata_id": "Q200", "directors": ["Yeni"], "actors": ["Oyuncu"]},
            ]
        )

        index = sources.load_credits(self.root)

        self.assertEqual(index.by_wikidata_id["Q2"]["directors"], ["Birinci"])
        self.assertEqual(index.by_wikidata_id["Q200"]["actors"], ["Oyuncu"])
        self.assertEqual(index.duplicate_rows, 1)
        self.assertFalse(index.file_missing)

    def test_duplicate_extra_film_id_across_files_goes_to_the_existing_counter(self):
        self.write_turkish(films=[turkish_film(3001, "Q100")])

        summary = loading.LoadSummary()
        identifiers = loading.index_dataset_identifiers(self.root)
        plan = loading.plan_extra_films(self.root, identifiers, summary)

        self.assertEqual(summary.skipped["ek_film_yinelenen_id"], 1)
        self.assertEqual([e["tmdb_id"] for e in plan.new if e["wikidata_id"] == "Q100"], [1001])


class TurkishLoadingTests(TurkishFilesCase):
    def test_turkish_film_loads_with_its_plot_profile_and_review(self):
        self.write_turkish(
            films=[
                turkish_film(2001, None),
                turkish_film(2002, "Q202", plot=None, plot_kaynagi=None),
            ],
            credits=[{"wikidata_id": "tmdb-2001", "directors": ["Zeki Demirkubuz"], "actors": []}],
            profiles=[{"id": "tmdb-2001", "p": PROFILE, "kaynak": "toplu"}],
            reviews=[
                {
                    "movie_id": "tmdb-2001",
                    "incelemeler": [{"icerik": "Güzel.", "puan": 8.0, "url": "https://x.test/t/1"}],
                }
            ],
        )

        summary = loading.load_archive(self.root)

        film = Film.objects.get(wikidata_id="tmdb-2001")
        self.assertEqual(film.plot_source, Film.PlotSource.WIKIPEDIA_ADDED)
        self.assertEqual(film.wikipedia_url, "https://tr.wikipedia.org/wiki/Film_2001")
        self.assertTrue(film.plot.startswith("Bir adam kasabaya gelir"))
        self.assertEqual(film.directors, ["Zeki Demirkubuz"])
        self.assertEqual(film.profile.tone, "Sessiz.")
        self.assertEqual(FilmReview.objects.filter(film=film).count(), 1)
        self.assertEqual(Film.objects.get(wikidata_id="Q202").plot_source, "")
        self.assertEqual(summary.extra_films, 4)  # arşivin 2 yeni ek filmi + 2 Türk filmi
        self.assertEqual(FilmProfile.objects.filter(film=film).count(), 1)

    def test_the_loader_runs_without_any_second_file(self):
        summary = loading.load_archive(self.root)

        self.assertEqual(summary.extra_films, 2)
        self.assertEqual(Film.objects.count(), 6)

    def test_heading_line_of_an_english_plot_is_dropped_turkish_text_is_kept(self):
        record = film_records.build_extra_film(
            turkish_film(2003, "Q203", plot="Plot\n\nEnglish plot of a Turkish film.")
        )
        turkish = film_records.build_extra_film(turkish_film(2004, "Q204", plot=TURKISH_PLOT))

        self.assertEqual(record["plot"], "English plot of a Turkish film.")
        self.assertTrue(turkish["plot"].startswith("Konu\n"))  # başlık listede yok: metin korunur


class RawWikidataIdNameTests(SimpleTestCase):
    def test_drop_raw_ids_removes_only_unresolved_identifiers(self):
        names = ["Zeki Demirkubuz", "Q3325924", " Q1 ", "", "Q", "Quentin Tarantino", "Q12a"]

        self.assertEqual(
            sources.drop_raw_ids(names), ["Zeki Demirkubuz", "Q", "Quentin Tarantino", "Q12a"]
        )

    def test_dataset_row_drops_raw_ids_from_directors_and_actors(self):
        row = dataset_row(directors="Q3325924, Reha Erdem", actors="Q1, Q2")

        record = film_records.build_dataset_film(row, None, None)

        self.assertEqual(record["directors"], ["Reha Erdem"])
        self.assertEqual(record["actors"], [])


class RawWikidataIdLoadingTests(TurkishFilesCase):
    def test_credits_file_names_with_raw_ids_are_dropped(self):
        write_jsonl(
            self.root / sources.CREDITS_JSONL,
            [{"wikidata_id": "Q2", "directors": ["Q3325924", "Reha Erdem"], "actors": ["Q9"]}],
        )

        loading.load_archive(self.root)

        film = Film.objects.get(wikidata_id="Q2")
        self.assertEqual(film.directors, ["Reha Erdem"])
        self.assertEqual(film.actors, [])


class TurkishOverviewCardTests(TestCase):
    def test_card_text_uses_the_turkish_overview_only_when_the_english_one_is_empty(self):
        turkish_only = make_film("Q1", tr_overview="Türkçe özet metni.")
        both = make_film("Q2", overview="English overview.", tr_overview="Türkçe özet metni.")

        self.assertIn("Türkçe özet metni.", embedding.film_card_text(turkish_only))
        self.assertIn("English overview.", embedding.film_card_text(both))
        self.assertNotIn("Türkçe özet metni.", embedding.film_card_text(both))

    def test_film_with_only_a_turkish_overview_gets_a_card(self):
        turkish_only = make_film("Q1", tr_overview="Türkçe özet metni.")
        nothing = make_film("Q2")
        summary = embedding.EmbedSummary()

        embedding.embed_missing_cards(fake_embedder, [turkish_only, nothing], summary)

        turkish_only.refresh_from_db()
        self.assertEqual(summary.cards, 1)
        self.assertEqual(summary.skipped["kart_tmdb_metni_yok"], 1)
        self.assertIsNotNone(turkish_only.card_embedding)
        self.assertEqual(FilmChunk.objects.count(), 0)
