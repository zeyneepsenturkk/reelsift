from django.test import SimpleTestCase

from apps.curation.services.countries import ordered_countries


class OrderedCountriesTests(SimpleTestCase):
    def test_the_country_of_the_original_language_comes_first(self):
        countries = ["Bosnia and Herzegovina", "Bulgaria", "France", "Turkey"]

        self.assertEqual(
            ordered_countries(countries, "tr"),
            ["Turkey", "Bosnia and Herzegovina", "Bulgaria", "France"],
        )
        self.assertEqual(
            ordered_countries(["France", "South Korea"], "ko"), ["South Korea", "France"]
        )

    def test_the_list_is_unchanged_when_the_language_does_not_name_a_listed_country(self):
        self.assertEqual(ordered_countries(["France", "Germany"], "tr"), ["France", "Germany"])
        self.assertEqual(ordered_countries(["France", "Spain"], "es"), ["France", "Spain"])
        self.assertEqual(ordered_countries(["Turkey", "France"], ""), ["Turkey", "France"])
        self.assertEqual(ordered_countries([], "tr"), [])

    def test_the_input_list_is_not_modified(self):
        countries = ["Greece", "Turkey"]

        ordered_countries(countries, "tr")

        self.assertEqual(countries, ["Greece", "Turkey"])
