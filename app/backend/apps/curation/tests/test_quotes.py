from django.test import SimpleTestCase, TestCase

from apps.agent.services.data import neutralize
from apps.core.exceptions import ServiceError
from apps.curation.services import quotes
from apps.curation.tests.base import (
    OVERVIEW_QUOTE,
    PLOT_QUOTE,
    REVIEW_QUOTE,
    make_review,
    make_story_film,
)


class NormalizeTests(SimpleTestCase):
    def test_whitespace_and_quote_styles_are_equalized(self):
        text = "He said “hello” — it’s  late.\n  Really."

        self.assertEqual(quotes.normalize(text), 'He said "hello" - it\'s late. Really.')

    def test_neutralized_tag_marker_equals_the_original_angle_bracket(self):
        self.assertEqual(quotes.normalize("a ‹/film> b"), quotes.normalize("a </film> b"))

    def test_letters_stay_case_sensitive(self):
        self.assertNotEqual(quotes.normalize("Snow"), quotes.normalize("snow"))


class CheckQuoteTests(TestCase):
    def setUp(self):
        self.film = make_story_film()
        make_review(self.film)

    def test_exact_plot_quote_returns_wikipedia_url(self):
        url = quotes.check_quote(self.film, "plot", PLOT_QUOTE)

        self.assertEqual(url, self.film.wikipedia_url)

    def test_quote_with_different_whitespace_and_quotes_is_accepted(self):
        spaced = PLOT_QUOTE.replace(" ", "  ").replace("detective", "\ndetective")

        self.assertEqual(quotes.check_quote(self.film, "plot", spaced), self.film.wikipedia_url)

    def test_overview_quote_returns_tmdb_url(self):
        url = quotes.check_quote(self.film, "overview", OVERVIEW_QUOTE)

        self.assertEqual(url, f"https://www.themoviedb.org/movie/{self.film.tmdb_id}")

    def test_overview_quote_is_also_checked_in_the_turkish_overview(self):
        quote = "Bir polis, uzun bir kış boyunca kaybolan bir adamı arar."
        film = make_story_film(3, overview="", tr_overview=quote)

        url = quotes.check_quote(film, "overview", quote)

        self.assertEqual(url, f"https://www.themoviedb.org/movie/{film.tmdb_id}")

    def test_quote_missing_from_both_overviews_is_rejected(self):
        film = make_story_film(4, tr_overview="Bir polis, uzun bir kış boyunca adam arar.")

        with self.assertRaises(ServiceError):
            quotes.check_quote(film, "overview", "Tamamen başka bir cümle, hiçbir yerde geçmez.")

    def test_review_quote_returns_review_url(self):
        url = quotes.check_quote(self.film, "review", REVIEW_QUOTE)

        self.assertEqual(url, f"https://example.test/review/{self.film.pk}")

    def test_quote_the_model_saw_through_tag_neutralization_is_accepted(self):
        sentence = "The sign read </film> and nobody dared to open the old cellar door."
        film = make_story_film(2, plot=f"Snow fell. {sentence} Then silence.")
        seen_by_model = neutralize(sentence)
        self.assertIn("‹", seen_by_model)

        url = quotes.check_quote(film, "plot", seen_by_model)

        self.assertEqual(url, film.wikipedia_url)

    def test_invented_quote_is_rejected(self):
        with self.assertRaises(ServiceError) as ctx:
            quotes.check_quote(self.film, "plot", "The detective discovers a hidden bunker.")

        self.assertEqual(ctx.exception.code, "quote_unverified")

    def test_quote_from_another_source_is_rejected(self):
        with self.assertRaises(ServiceError):
            quotes.check_quote(self.film, "overview", PLOT_QUOTE)

    def test_too_short_and_too_long_quotes_are_rejected(self):
        with self.assertRaises(ServiceError):
            quotes.check_quote(self.film, "plot", "Snow covers")
        with self.assertRaises(ServiceError):
            quotes.check_quote(self.film, "plot", "x" * (quotes.MAX_QUOTE_LENGTH + 1))

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ServiceError):
            quotes.check_quote(self.film, "blog", PLOT_QUOTE)
