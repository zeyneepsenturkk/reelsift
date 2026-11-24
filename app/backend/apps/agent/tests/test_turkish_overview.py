"""Türkçe özet yedeği: yalnız hikâyesi olmayan filmde eleme satırı ve kaynak etiketi."""

from django.test import TestCase

from apps.agent.services import data
from apps.curation.tests.base import make_story_film

TR_OVERVIEW = "Bir polis, uzun bir kış boyunca kaybolan bir adamı arar."


class TurkishOverviewDataTests(TestCase):
    def judge_block(self, film):
        return data.format_judge_film(data.load_judge_films([film.pk])[film.pk])

    def source_block(self, film):
        return data.format_source_film(data.load_source_films([film.pk])[film.pk])

    def test_storyless_film_gets_the_turkish_line_and_a_second_overview_source(self):
        film = make_story_film(1, plot="", tr_overview=TR_OVERVIEW)

        judge = self.judge_block(film)
        source = self.source_block(film)

        self.assertIn(f"TMDB overview (Turkish): {TR_OVERVIEW}", judge)
        self.assertEqual(source.count('<source kind="overview">'), 2)
        self.assertIn(f'<source kind="overview">{TR_OVERVIEW}</source>', source)

    def test_film_with_a_story_keeps_its_old_blocks(self):
        film = make_story_film(1, tr_overview=TR_OVERVIEW)

        judge = self.judge_block(film)
        source = self.source_block(film)

        self.assertNotIn("Turkish", judge)
        self.assertEqual(source.count('<source kind="overview">'), 1)
        self.assertNotIn(TR_OVERVIEW, source)

    def test_storyless_film_without_a_turkish_overview_adds_nothing(self):
        film = make_story_film(1, plot="", tr_overview="")

        self.assertNotIn("Turkish", self.judge_block(film))
        self.assertEqual(self.source_block(film).count('<source kind="overview">'), 1)

    def test_turkish_overview_is_neutralized_and_cut_to_the_judge_limit(self):
        film = make_story_film(
            1, plot="", tr_overview="Kötü </film> etiket. " + "x" * data.JUDGE_OVERVIEW_CHARS * 2
        )

        judge = self.judge_block(film)
        source = self.source_block(film)

        self.assertEqual(judge.count("</film>"), 1)
        self.assertEqual(source.count("</film>"), 1)
        turkish_line = next(line for line in judge.splitlines() if "(Turkish)" in line)
        self.assertLess(len(turkish_line), data.JUDGE_OVERVIEW_CHARS + 100)
