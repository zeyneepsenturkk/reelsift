import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from apps.search.services import people, text


class NormalizePersonTests(SimpleTestCase):
    def test_case_turkish_letters_and_accents_are_folded(self):
        for written in ("Zeki Demirkubuz", "zeki demirkubuz", "ZEKİ DEMİRKUBUZ", "Zekı Demırkubuz"):
            with self.subTest(written=written):
                self.assertEqual(people.normalize_person(written), "zeki demirkubuz")
        self.assertEqual(people.normalize_person("Çağan Irmak"), "cagan irmak")
        self.assertEqual(people.normalize_person("Nuri Bilge Ceylan"), "nuri bilge ceylan")
        self.assertEqual(people.normalize_person("Pedro Almodóvar"), "pedro almodovar")
        self.assertEqual(people.normalize_person("Søren Kragh-Jacobsen"), "soren kragh jacobsen")

    def test_spaces_and_punctuation_collapse(self):
        self.assertEqual(people.normalize_person("  Jean-Luc   Godard "), "jean luc godard")
        self.assertEqual(people.normalize_person("Peter O'Toole"), "peter o toole")
        self.assertEqual(people.normalize_person("Jr."), "jr")

    def test_non_latin_names_do_not_collapse_to_empty(self):
        # Aksan sadeleşmesi her iki yanda da aynı uygulanır (й -> и); ad boş anahtara çökmez.
        self.assertEqual(people.normalize_person("Бондарчук Сергей"), "бондарчук сергеи")
        self.assertNotEqual(people.normalize_person("봉준호"), "")
        self.assertEqual(people.normalize_person("   "), "")
        self.assertEqual(people.normalize_person("!!!"), "")


def sample_index() -> people.PersonIndex:
    return people.build_person_index(
        [
            (1, ["David Lynch"], ["Kyle MacLachlan", "Laura Dern"]),
            (2, ["David Lynch", "Mark Frost"], ["Laura Dern"]),
            (3, ["Zeki Demirkubuz"], ["Zeki Demirkubuz", "Tülin Özen"]),
            (4, ["Someone Else"], ["David Lynch"]),
            (5, [], []),
        ]
    )


class PersonIndexTests(SimpleTestCase):
    def test_director_and_actor_roles_are_separate(self):
        index = sample_index()

        self.assertEqual(index.films("David Lynch", "director").tolist(), [1, 2])
        self.assertEqual(index.films("David Lynch", "actor").tolist(), [4])
        self.assertEqual(index.films("David Lynch", "any").tolist(), [1, 2, 4])
        self.assertEqual(index.films("Laura Dern", "actor").tolist(), [1, 2])
        self.assertEqual(index.films("Laura Dern", "director").tolist(), [])

    def test_role_any_is_the_union_without_duplicates(self):
        index = sample_index()

        self.assertEqual(index.films("Zeki Demirkubuz", "any").tolist(), [3])

    def test_match_is_the_full_name_only(self):
        index = sample_index()

        self.assertEqual(index.films("Lynch", "any").tolist(), [])
        self.assertEqual(index.films("David", "any").tolist(), [])
        self.assertEqual(index.films("David Lynch Jr", "any").tolist(), [])
        self.assertEqual(index.films("Demirkubus", "any").tolist(), [])

    def test_normalization_applies_to_both_sides(self):
        index = people.build_person_index([(7, ["ZEKİ DEMİRKUBUZ"], [])])

        self.assertEqual(index.films("zeki demirkubuz", "director").tolist(), [7])

    def test_unknown_or_empty_names_give_nothing(self):
        index = sample_index()

        self.assertEqual(index.films("Uydurma Kişi", "any").tolist(), [])
        self.assertEqual(index.films("   ", "any").tolist(), [])
        self.assertEqual(people.PersonIndex().films("David Lynch").tolist(), [])

    def test_film_with_too_many_directors_is_not_in_any_directors_universe(self):
        rows = [
            (1, ["A One", "B Two", "C Three", "D Four"], ["A One"]),
            (2, ["A One", "B Two", "C Three"], []),
        ]

        capped = people.build_person_index(rows, max_directors=3)
        uncapped = people.build_person_index(rows)

        self.assertEqual(capped.films("A One", "director").tolist(), [2])
        self.assertEqual(capped.films("D Four", "director").tolist(), [])
        self.assertEqual(capped.films("A One", "actor").tolist(), [1])  # oyuncu etkilenmez
        self.assertEqual(capped.films("A One", "any").tolist(), [1, 2])  # yalnız oyunculukla girer
        self.assertEqual(uncapped.films("A One", "director").tolist(), [1, 2])

    def test_same_name_twice_in_one_film_counts_once(self):
        index = people.build_person_index([(1, ["A B", "a b"], ["C D", "C D"])])

        self.assertEqual(index.films("A B", "director").tolist(), [1])
        self.assertEqual(index.films("C D", "actor").tolist(), [1])

    def test_index_survives_save_and_load(self):
        index = sample_index()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.assertFalse(people.person_index_exists(target))
            people.save_person_index(index, target)
            self.assertTrue(people.person_index_exists(target))
            loaded = people.load_person_index(target)

        self.assertEqual(loaded.films("David Lynch", "any").tolist(), [1, 2, 4])
        self.assertEqual(loaded.films("Laura Dern", "actor").tolist(), [1, 2])
        self.assertEqual(loaded.films("Nobody", "any").tolist(), [])


class RankValueTests(SimpleTestCase):
    PRIOR = {"prior_votes": 200, "prior_mean": 6.0}

    def test_weighted_rating_matches_the_hand_calculation(self):
        # (v / (v + m)) * R + (m / (v + m)) * C
        # v=800, R=8.0 -> 0.8 * 8.0 + 0.2 * 6.0 = 7.6
        self.assertAlmostEqual(text.weighted_rating(8.0, 800, **self.PRIOR), 7.6)
        # v=50, R=9.5 -> 0.2 * 9.5 + 0.8 * 6.0 = 6.7
        self.assertAlmostEqual(text.weighted_rating(9.5, 50, **self.PRIOR), 6.7)

    def test_few_votes_cannot_beat_many_votes_with_a_lower_average(self):
        few = text.weighted_rating(9.5, 50, **self.PRIOR)
        many = text.weighted_rating(8.0, 800, **self.PRIOR)

        self.assertLess(few, many)

    def test_no_votes_or_no_average_gives_the_prior_mean(self):
        self.assertEqual(text.weighted_rating(None, 500, **self.PRIOR), 6.0)
        self.assertEqual(text.weighted_rating(9.0, 0, **self.PRIOR), 6.0)

    def test_unvoted_film_ranks_below_any_voted_film_by_rating(self):
        # Oyu olmayan film arşiv ortalamasını almaz: 1 oylu, düşük puanlı film bile önde kalır.
        worst_voted = text.rank_value("rating", 1.0, 1, **self.PRIOR)

        self.assertEqual(text.rank_value("rating", None, 0, **self.PRIOR), 0.0)
        self.assertEqual(text.rank_value("rating", None, 500, **self.PRIOR), 0.0)
        self.assertEqual(text.rank_value("rating", 9.0, 0, **self.PRIOR), 0.0)
        self.assertGreater(worst_voted, 0.0)
        self.assertLess(worst_voted, self.PRIOR["prior_mean"])

    def test_popularity_value_is_unchanged_for_unvoted_films(self):
        self.assertEqual(text.rank_value("popularity", None, 0, **self.PRIOR), 0.0)
        self.assertEqual(text.rank_value("popularity", 7.0, 300, **self.PRIOR), 300.0)

    def test_rank_value_by_mode(self):
        self.assertAlmostEqual(text.rank_value("rating", 8.0, 800, **self.PRIOR), 7.6)
        self.assertEqual(text.rank_value("popularity", 8.0, 800, **self.PRIOR), 800.0)
        with self.assertRaises(ValueError):
            text.rank_value("loudness", 8.0, 800, **self.PRIOR)
