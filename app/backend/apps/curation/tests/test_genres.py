from django.test import SimpleTestCase

from apps.curation.services.genres import GENRE_NAMES_TR, genre_name_tr


class GenreNameTests(SimpleTestCase):
    def test_known_genres_get_their_turkish_name(self):
        self.assertEqual(genre_name_tr("Comedy"), "komedi")
        self.assertEqual(genre_name_tr("Science Fiction"), "bilim kurgu")
        self.assertEqual(genre_name_tr("TV Movie"), "TV filmi")
        self.assertEqual(genre_name_tr("sci-fi"), "bilim kurgu")
        self.assertEqual(genre_name_tr("film noir"), "kara film")
        self.assertEqual(genre_name_tr("Political Thriller"), "siyasi gerilim")
        self.assertEqual(genre_name_tr("psychological"), "psikolojik")

    def test_lookup_ignores_case_and_surrounding_spaces(self):
        self.assertEqual(genre_name_tr("  CRIME "), "suç")
        self.assertEqual(genre_name_tr("sCiEnCe fIcTiOn"), "bilim kurgu")

    def test_unknown_name_stays_as_it_is(self):
        self.assertEqual(genre_name_tr("Space Opera"), "Space Opera")

    def test_turkish_names_are_lowercase(self):
        for turkish in GENRE_NAMES_TR.values():
            if turkish != "TV filmi":
                self.assertEqual(turkish, turkish.lower())
