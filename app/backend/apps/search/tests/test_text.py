import numpy as np
from django.test import SimpleTestCase

from apps.search.services import text
from apps.search.services.types import TitleHint


class TitleMatchingTests(SimpleTestCase):
    def test_normalize_title_strips_accents_punctuation_and_article(self):
        self.assertEqual(text.normalize_title("The Amélie: Poulain!"), "amelie poulain")
        self.assertEqual(text.normalize_title("Les  Misérables"), "miserables")
        self.assertEqual(text.normalize_title("A Clockwork Orange"), "clockwork orange")

    def test_match_titles_requires_year_within_one(self):
        index = text.build_title_index(
            [(1, "Inception", 2010), (2, "Inception", 1990), (3, "Paprika", 2006)]
        )
        hints = (TitleHint("inception", 2011), TitleHint("Paprika", 2010), TitleHint("Nope", 2000))
        self.assertEqual(text.match_titles(index, hints), [1])

    def test_match_titles_takes_first_film_in_row_order(self):
        index = text.build_title_index([(7, "Heat", 1995), (4, "Heat", 1995)])
        self.assertEqual(text.match_titles(index, (TitleHint("Heat", 1995),)), [7])

    def test_match_titles_without_hint_year_uses_title_only(self):
        index = text.build_title_index([(1, "Heat", 1995)])
        self.assertEqual(text.match_titles(index, (TitleHint("Heat", None),)), [1])

    def test_match_titles_film_without_year_matches_any_hint_year(self):
        index = text.build_title_index([(1, "Heat", None)])
        self.assertEqual(text.match_titles(index, (TitleHint("Heat", 1995),)), [1])


class FusionTests(SimpleTestCase):
    def test_rrf_scores_sum_reciprocal_ranks(self):
        scores = text.rrf_scores([[10, 20], [20, 30]], k=60)
        self.assertAlmostEqual(scores[10], 1 / 61)
        self.assertAlmostEqual(scores[20], 1 / 62 + 1 / 61)
        self.assertAlmostEqual(scores[30], 1 / 62)

    def test_top_ranked_sorts_by_score_and_keeps_input_order_on_ties(self):
        ids = np.array([5, 6, 7, 8])
        scores = np.array([0.5, 0.9, 0.5, 0.1])
        self.assertEqual(text.top_ranked(ids, scores, 3).tolist(), [6, 5, 7])
        empty = np.array([], dtype=np.int64)
        self.assertEqual(text.top_ranked(empty, np.array([]), 3).tolist(), [])

    def test_fuse_drops_short_plots_unless_suggested(self):
        sources = {"dense": [1, 2, 3], "bma": [3, 2], "g": [2]}
        lengths = {1: 500, 2: 100, 3: 500}
        ranked, _ = text.fuse(
            sources, ("dense", "bma", "g"), lengths, suggested=[2], rrf_k=60, min_plot_chars=300
        )
        self.assertEqual(set(ranked), {1, 2, 3})
        self.assertEqual(ranked[0], 2)  # kısa ama önerilen: elenmez, üç listede de var
        ranked, scores = text.fuse(
            {"dense": [1, 2, 3]}, ("dense",), lengths, suggested=[], rrf_k=60, min_plot_chars=300
        )
        self.assertNotIn(2, scores)
        self.assertEqual(ranked, [1, 3])

    def test_fuse_orders_ties_by_film_id_and_skips_empty_sources(self):
        ranked, _ = text.fuse(
            {"dense": [9], "hyde": [4], "g": []},
            ("dense", "hyde", "g"),
            {9: 400, 4: 400},
            suggested=[],
            rrf_k=60,
            min_plot_chars=300,
        )
        # İki film de kendi listesinde 1. sırada: aynı puan, küçük kimlik önde.
        self.assertEqual(ranked, [4, 9])


class DocumentTests(SimpleTestCase):
    PROFILE = {
        "themes": ["grief", "memory"],
        "moods": ["tense", "tragic"],
        "tone": "A somber thriller.",
        "pacing": "slow",
        "setting_place": "Paris",
        "setting_period": "unknown",
        "narrative": ["nonlinear"],
        "for_viewers": "For viewers looking for a puzzle.",
    }

    def test_profile_text_builds_labelled_sentences(self):
        self.assertEqual(
            text.profile_text(**self.PROFILE),
            "Themes: grief; memory. Mood: tense, tragic. Tone: A somber thriller. Pacing: slow. "
            "Setting: Paris. Narrative: nonlinear. For viewers looking for a puzzle.",
        )

    def test_profile_text_skips_unknown_and_empty_parts(self):
        empty = dict.fromkeys(self.PROFILE, "")
        empty.update(themes=[], moods=[], narrative=[], pacing="unknown", setting_place="unknown")
        self.assertEqual(text.profile_text(**empty), "")

    def test_profile_text_adds_viewer_prefix_once(self):
        profile = {**self.PROFILE, "for_viewers": "a quiet drama."}
        self.assertTrue(
            text.profile_text(**profile).endswith("For viewers looking for a quiet drama.")
        )

    def test_usable_profile_text_needs_more_than_twenty_characters(self):
        self.assertEqual(text.usable_profile_text("x" * 20), "")
        self.assertEqual(text.usable_profile_text("x" * 21), "x" * 21)

    def test_rerank_document_modes(self):
        args = ("Overview.", "Plot.", "Profile.")
        self.assertEqual(text.rerank_document("A", *args), "Overview. Plot.")
        self.assertEqual(text.rerank_document("A", "", "Plot.", "Profile."), "Plot.")
        self.assertEqual(text.rerank_document("B", *args), "Profile. Overview. Plot.")
        self.assertEqual(text.rerank_document("B_end", *args), "Overview. Plot. Profile.")
        self.assertEqual(text.rerank_document("B", "", "Plot.", ""), "Plot.")

    def test_rerank_document_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            text.rerank_document("C", "", "", "")


class BlendTests(SimpleTestCase):
    IDS = [10, 20, 30, 40]  # RRF sırası
    SCORES = [0.1, 0.9, 0.5, 0.7]  # yeniden sıralama sırası: 20, 40, 30, 10

    def test_zero_blend_is_pure_rerank_order(self):
        self.assertEqual(text.blended_order(self.IDS, self.SCORES, 0.0), [20, 40, 30, 10])

    def test_full_blend_is_pure_rrf_order(self):
        self.assertEqual(text.blended_order(self.IDS, self.SCORES, 1.0), [10, 20, 30, 40])

    def test_half_blend_weights_both_ranks(self):
        # (RRF sırası, yeniden sıralama sırası): 10 -> (1, 4), 20 -> (2, 1), 30 -> (3, 3),
        # 40 -> (4, 2).
        # Puan = 0,5/(60+a) + 0,5/(60+b); elle hesaplanan sıra: 20, 10, 40, 30.
        self.assertEqual(text.blended_order(self.IDS, self.SCORES, 0.5), [20, 10, 40, 30])

    def test_blend_of_empty_list(self):
        self.assertEqual(text.blended_order([], [], 0.3), [])
