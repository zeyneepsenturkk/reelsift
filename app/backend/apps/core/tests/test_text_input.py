import json

from django.test import Client, SimpleTestCase, TestCase, override_settings

from apps.chats.models import Message
from apps.core.text import is_db_unsafe
from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user

# Kaçışlı JSON metni: geçerli JSON'dur, ayrıştırılınca NUL / eşleşmemiş vekil karakter çıkar.
NUL_JSON = '"a\\u0000b"'
SURROGATE_JSON = '"a\\ud800b"'
INVALID = {"nul": NUL_JSON, "eşleşmemiş vekil": SURROGATE_JSON}


class UnsafeTextTests(SimpleTestCase):
    def test_nul_and_lone_surrogate_are_unsafe(self):
        self.assertTrue(is_db_unsafe("a\x00b"))
        self.assertTrue(is_db_unsafe("a\ud800b"))

    def test_ordinary_text_is_safe(self):
        for text in ("", "Karlı kasabalar", "İıÖöŞşĞğ", "日本語", "emoji 🎬", "satır\nsonu\ttab"):
            with self.subTest(text=text):
                self.assertFalse(is_db_unsafe(text))

    def test_the_json_samples_really_decode_to_unsafe_text(self):
        for raw in INVALID.values():
            self.assertTrue(is_db_unsafe(json.loads(raw)))


class TextInputTestCase(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.chat = make_chat(self.user)
        self.collection = make_collection(self.user, self.chat, films=[make_story_film(1)])
        self.client = Client()
        self.client.force_login(self.user)


class ShareTokenTests(TextInputTestCase):
    def test_nul_and_surrogate_tokens_get_the_same_404_as_a_wrong_token(self):
        anon = Client()
        wrong = anon.get("/api/share/yanlis-anahtar")

        responses = [anon.get("/api/share/%00"), anon.get("/api/share/ab%00cd")]
        responses.append(anon.get("/api/share/%ED%A0%80"))  # tek başına vekil: geçersiz UTF-8

        self.assertEqual(wrong.status_code, 404)
        for response in responses:
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.content, wrong.content)


class CollectionPatchTextTests(TextInputTestCase):
    def patch(self, field, raw):
        return self.client.patch(
            f"/api/collections/{self.collection.pk}",
            data=f'{{"{field}": {raw}}}',
            content_type="application/json",
        )

    def test_invalid_characters_in_title_and_description_are_422(self):
        for field in ("title", "description"):
            for name, raw in INVALID.items():
                with self.subTest(field=field, kind=name):
                    response = self.patch(field, raw)

                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(
                        response.json(), {"detail": "Geçersiz istek.", "code": "validation_error"}
                    )

        self.collection.refresh_from_db()
        self.assertEqual(self.collection.title, "Karlı kasabalar")
        self.assertEqual(self.collection.version, 1)

    def test_valid_text_still_updates(self):
        response = self.patch("title", json.dumps("Yeni başlık 🎬"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Yeni başlık 🎬")


class StreamTextTests(TextInputTestCase):
    def post(self, raw_text):
        return self.client.post(
            f"/api/chats/{self.chat.pk}/messages/stream",
            data=f'{{"text": {raw_text}}}',
            content_type="application/json",
        )

    def test_invalid_characters_in_message_text_are_422_and_nothing_is_saved(self):
        for name, raw in INVALID.items():
            with self.subTest(kind=name):
                response = self.post(raw)

                self.assertEqual(response.status_code, 422)
                self.assertEqual(response["Content-Type"], "application/json")
                self.assertEqual(response.json()["code"], "validation_error")
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 0)


class LoginTextTests(TextInputTestCase):
    def test_nul_and_surrogate_usernames_never_reach_the_database(self):
        for name, raw in INVALID.items():
            with self.subTest(kind=name):
                response = self.client.post(
                    "/api/auth/login",
                    data=f'{{"username": {raw}, "password": "x"}}',
                    content_type="application/json",
                )

                # NUL servis katmanında 401; vekil karakteri şema doğrulaması 422 ile eleyebilir.
                self.assertIn(response.status_code, (401, 422))
                self.assertIn(response.json()["code"], ("invalid_credentials", "validation_error"))


@override_settings(ROOT_URLCONF="apps.core.tests.urls_boom")
class UnexpectedErrorTests(SimpleTestCase):
    """Düz Django görünümündeki beklenmeyen hata: DEBUG açık ya da kapalı, `/api/` altı JSON 500."""

    def setUp(self):
        self.client = Client(raise_request_exception=False)

    def check_json_500(self, path):
        with self.assertLogs("apps.core.middleware", level="ERROR") as logs:
            response = self.client.get(path)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(
            response.json(), {"detail": "Beklenmeyen bir hata oluştu.", "code": "server_error"}
        )
        self.assertNotIn("gizli-ic-ayrinti", response.content.decode())
        self.assertIn("gizli-ic-ayrinti", "\n".join(logs.output))  # ayrıntı yalnız loga gider

    def test_sync_view_with_debug_on(self):
        with override_settings(DEBUG=True):
            self.check_json_500("/api/boom/")

    def test_sync_view_with_debug_off(self):
        with override_settings(DEBUG=False):
            self.check_json_500("/api/boom/")

    def test_async_view_with_debug_on_and_off(self):
        for debug in (True, False):
            with self.subTest(debug=debug), override_settings(DEBUG=debug):
                self.check_json_500("/api/boom-async/")

    def test_django_handled_404_is_not_turned_into_500(self):
        response = self.client.get("/api/missing/")

        self.assertEqual(response.status_code, 404)

    def test_paths_outside_api_are_left_alone(self):
        with override_settings(DEBUG=False):
            response = self.client.get("/disarida/")

        self.assertEqual(response.status_code, 500)
        self.assertNotEqual(response.get("Content-Type"), "application/json")
