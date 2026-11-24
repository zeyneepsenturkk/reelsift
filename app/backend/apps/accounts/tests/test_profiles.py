from django.test import TestCase

from apps.accounts.services.profiles import display_name, initials, serialize_user
from apps.accounts.tests.base import make_user


class ProfileTests(TestCase):
    def test_full_name_is_used_when_present(self):
        user = make_user("zs", first_name="Zeynep", last_name="Şentürk")

        self.assertEqual(display_name(user), "Zeynep Şentürk")
        self.assertEqual(initials(user), "ZŞ")

    def test_username_is_used_when_name_is_empty(self):
        user = make_user("zeynep.senturk")

        self.assertEqual(display_name(user), "zeynep.senturk")
        self.assertEqual(initials(user), "ZS")

    def test_single_word_gives_single_initial(self):
        self.assertEqual(initials(make_user("editor")), "E")

    def test_turkish_dotted_capital_i(self):
        self.assertEqual(initials(make_user("a", first_name="ilknur", last_name="ışık")), "İI")
        self.assertEqual(initials(make_user("b", first_name="Işıl")), "I")

    def test_at_most_two_initials_with_many_words(self):
        user = make_user("c", first_name="Ayşe Fatma", last_name="Yılmaz")

        self.assertEqual(initials(user), "AY")

    def test_symbol_only_word_is_skipped_safely(self):
        self.assertEqual(initials(make_user("d", first_name="(x)", last_name="--")), "X")

    def test_serialize_user_has_contract_fields_only(self):
        user = make_user("editor", email="e@example.test")

        data = serialize_user(user).model_dump()

        self.assertEqual(set(data), {"id", "username", "display_name", "initials"})
        self.assertEqual(data["id"], user.pk)
