from datetime import date

from django.test import SimpleTestCase

from apps.films.models import Film
from apps.films.services import film_records, sources
from apps.films.tests.base import dataset_row, extra_record, tmdb_record


class ParseHelperTests(SimpleTestCase):
    def test_parse_int_accepts_float_text_and_rejects_garbage(self):
        self.assertEqual(film_records.parse_int("108.0"), 108)
        self.assertIsNone(film_records.parse_int(""))
        self.assertIsNone(film_records.parse_int(None))

    def test_parse_float(self):
        self.assertEqual(film_records.parse_float("3.5"), 3.5)
        self.assertIsNone(film_records.parse_float("abc"))

    def test_parse_date_takes_iso_prefix_and_rejects_garbage(self):
        self.assertEqual(film_records.parse_date("1930-01-01T00:00:00Z"), date(1930, 1, 1))
        self.assertIsNone(film_records.parse_date("http://www.wikidata.org/.well-known/genid/abc"))
        self.assertIsNone(film_records.parse_date(""))
        self.assertIsNone(film_records.parse_date(None))

    def test_split_names(self):
        self.assertEqual(film_records.split_names("A, B ,, C"), ["A", "B", "C"])
        self.assertEqual(film_records.split_names(""), [])

    def test_clean_plot_strips_only_a_leading_section_heading(self):
        self.assertEqual(film_records.clean_plot("Plot \n\nIt begins."), "It begins.")
        self.assertEqual(
            film_records.clean_plot("The plot thickens.\nMore."), "The plot thickens.\nMore."
        )
        self.assertEqual(film_records.clean_plot(None), "")


class BuildDatasetFilmTests(SimpleTestCase):
    def test_tmdb_values_win_over_dataset_values(self):
        row = dataset_row(tmdb_id="101", title="Dataset Title", vote_count="1")
        tmdb = {**tmdb_record(101, "Q1"), "countries": ["United States of America"]}

        fields = film_records.build_dataset_film(row, tmdb, None)

        self.assertEqual(fields["title"], "TMDB 101")
        self.assertEqual(fields["tmdb_id"], 101)
        self.assertEqual(fields["vote_count"], 5000)
        self.assertEqual(fields["runtime"], 111)
        self.assertEqual(fields["genres"], ["Drama", "War"])
        self.assertEqual(fields["countries"], ["United States of America"])
        self.assertEqual(fields["release_date"], date(1999, 6, 2))
        self.assertEqual(fields["plot_source"], Film.PlotSource.DATASET)

    def test_dataset_values_fill_in_when_tmdb_is_missing(self):
        fields = film_records.build_dataset_film(dataset_row(), None, None)

        self.assertEqual(fields["title"], "Alpha")
        self.assertEqual(fields["runtime"], 100)
        self.assertEqual(fields["genres"], ["drama film", "war film"])
        self.assertEqual(fields["countries"], ["United States", "France"])
        self.assertEqual(fields["directors"], ["Director One"])
        self.assertEqual(fields["vote_count"], 120)
        self.assertEqual(fields["keywords"], [])
        self.assertEqual(fields["release_date"], date(1999, 5, 1))

    def test_zero_runtime_in_tmdb_falls_back_to_dataset(self):
        tmdb = {**tmdb_record(101, "Q1"), "countries": [], "runtime": 0}

        fields = film_records.build_dataset_film(dataset_row(), tmdb, None)

        self.assertEqual(fields["runtime"], 100)

    def test_renewed_plot_replaces_dataset_plot_and_loses_heading(self):
        fields = film_records.build_dataset_film(dataset_row(), None, "Plot\nRenewed story.")

        self.assertEqual(fields["plot"], "Renewed story.")
        self.assertEqual(fields["plot_source"], Film.PlotSource.WIKIPEDIA_RENEWED)

    def test_unusable_dataset_numbers_become_null(self):
        row = dataset_row(vote_average="", vote_count="", popularity="", duration="")

        fields = film_records.build_dataset_film(row, None, None)

        self.assertIsNone(fields["vote_average"])
        self.assertEqual(fields["vote_count"], 0)
        self.assertIsNone(fields["runtime"])


class TurkishTitleTests(SimpleTestCase):
    def test_turkish_film_without_translation_uses_original_title(self):
        tmdb = {
            **tmdb_record(101, "Q1"),
            "original_language": "tr",
            "original_title": "Kader",
            "tr_title": "",
        }

        fields = film_records.build_dataset_film(dataset_row(tmdb_id="101"), tmdb, None)

        self.assertEqual(fields["tr_title"], "Kader")

    def test_existing_translation_is_kept(self):
        tmdb = {
            **tmdb_record(101, "Q1"),
            "original_language": "tr",
            "original_title": "Masumiyet",
            "tr_title": "Masumiyet (Türkçe)",
        }

        fields = film_records.build_dataset_film(dataset_row(tmdb_id="101"), tmdb, None)

        self.assertEqual(fields["tr_title"], "Masumiyet (Türkçe)")

    def test_foreign_film_without_translation_stays_empty(self):
        tmdb = {
            **tmdb_record(101, "Q1"),
            "original_language": "fr",
            "original_title": "Amélie",
            "tr_title": "",
        }

        fields = film_records.build_dataset_film(dataset_row(tmdb_id="101"), tmdb, None)

        self.assertEqual(fields["tr_title"], "")

    def test_extra_turkish_film_uses_original_title(self):
        extra = {
            **extra_record(1003, "Q101"),
            "original_language": "tr",
            "original_title": "Kıskanmak",
            "tr_title": "",
        }

        self.assertEqual(film_records.build_extra_film(extra)["tr_title"], "Kıskanmak")

    def test_turkish_film_without_original_title_stays_empty(self):
        self.assertEqual(
            film_records.turkish_title({"original_language": "tr", "tr_title": ""}), ""
        )


class BuildExtraFilmTests(SimpleTestCase):
    def test_extra_film_uses_tmdb_fields_and_cleaned_plot(self):
        fields = film_records.build_extra_film(extra_record(1001, "Q100"))

        self.assertEqual(fields["wikidata_id"], "Q100")
        self.assertEqual(fields["plot"], "An extra film plot. It is short.")
        self.assertEqual(fields["plot_source"], Film.PlotSource.WIKIPEDIA_ADDED)
        self.assertEqual(fields["countries"], ["United States of America"])
        self.assertEqual(fields["directors"], [])

    def test_film_without_wikidata_id_gets_placeholder_and_year_from_release_date(self):
        extra = extra_record(1002, None, plot=None, year=None)

        fields = film_records.build_extra_film(extra)

        self.assertEqual(fields["wikidata_id"], "tmdb-1002")
        self.assertEqual(fields["year"], 1999)
        self.assertEqual(fields["plot"], "")
        self.assertEqual(fields["plot_source"], "")

    def test_extra_wikidata_id_prefers_real_id(self):
        self.assertEqual(film_records.extra_wikidata_id({"wikidata_id": "Q5", "tmdb_id": 9}), "Q5")
        self.assertEqual(
            film_records.extra_wikidata_id({"wikidata_id": None, "tmdb_id": 9}), "tmdb-9"
        )


class ApplyCreditsTests(SimpleTestCase):
    def credits(self, **entry):
        index = sources.CreditsIndex()
        index.by_wikidata_id["Q1"] = {"directors": [], "actors": [], **entry}
        return index

    def record(self, **overrides):
        return {"wikidata_id": "Q1", "directors": [], "actors": [], **overrides}

    def test_fills_only_empty_fields(self):
        record = self.record(directors=["Dataset Director"])
        credits = self.credits(directors=["Other"], actors=["Actor"])

        outcome = film_records.apply_credits(record, credits)

        self.assertEqual(outcome, "applied")
        self.assertEqual(record["directors"], ["Dataset Director"])
        self.assertEqual(record["actors"], ["Actor"])
        self.assertEqual(credits.matched, {"Q1"})

    def test_filled_fields_report_already_filled(self):
        record = self.record(directors=["D"], actors=["A"])

        outcome = film_records.apply_credits(record, self.credits(directors=["X"], actors=["Y"]))

        self.assertEqual(outcome, "already_filled")
        self.assertEqual((record["directors"], record["actors"]), (["D"], ["A"]))

    def test_unknown_film_and_empty_credits_do_nothing(self):
        record = self.record(wikidata_id="Q9")

        self.assertIsNone(film_records.apply_credits(record, self.credits(directors=["X"])))
        self.assertIsNone(film_records.apply_credits(self.record(), self.credits()))
        self.assertIsNone(film_records.apply_credits(self.record(), None))
        self.assertEqual(record["directors"], [])
