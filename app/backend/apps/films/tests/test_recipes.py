from django.test import SimpleTestCase

from apps.films.services.recipes import card_text, chunk_text, film_prefix
from apps.films.tests.base import long_plot


class ChunkTextTests(SimpleTestCase):
    def test_short_plot_stays_single_chunk(self):
        self.assertEqual(
            chunk_text("One sentence. Two sentences."), ["One sentence. Two sentences."]
        )

    def test_long_plot_splits_on_sentence_boundaries_with_overlap(self):
        chunks = chunk_text(long_plot(40))

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertTrue(chunk.endswith("somebody new."))
            self.assertLessEqual(len(chunk.split()), 200)
        # Örtüşme: bir parçanın son cümlesi sonrakinin içinde de bulunur.
        last_sentence_of_first = chunks[0].rsplit(". ", 1)[-1]
        self.assertIn(last_sentence_of_first, chunks[1])

    def test_empty_plot_yields_single_empty_chunk(self):
        self.assertEqual(chunk_text("   "), [""])


class PrefixAndCardTests(SimpleTestCase):
    def test_prefix_includes_year_when_known(self):
        self.assertEqual(
            film_prefix("Alpha", 1999, "drama film", "France"),
            "Title: Alpha (1999). Genres: drama film. Country: France. ",
        )

    def test_prefix_omits_year_when_unknown(self):
        self.assertEqual(film_prefix("Alpha", None, "", ""), "Title: Alpha. Genres: . Country: . ")

    def test_card_text_collapses_whitespace(self):
        text = card_text(
            "Alpha", 1999, "", "Line one.\n\nLine two.", ["a", "b"], ["Drama"], ["France"]
        )

        self.assertEqual(
            text,
            "Alpha (1999). Line one. Line two. Keywords: a, b. Genres: Drama. Country: France.",
        )

    def test_card_text_uses_question_mark_for_unknown_year(self):
        self.assertTrue(card_text("Alpha", None, "t", "o", [], [], []).startswith("Alpha (?)."))
