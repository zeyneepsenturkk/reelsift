import importlib
import os
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase, override_settings
from ninja.errors import HttpError

from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user
from config.settings import base as base_settings


class ErrorBodyTests(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.chat = make_chat(self.user)
        self.collection = make_collection(self.user, self.chat, films=[make_story_film(1)])
        self.client = Client()
        self.client.force_login(self.user)

    def patch_collection(self, body):
        return self.client.patch(
            f"/api/collections/{self.collection.pk}", data=body, content_type="application/json"
        )

    def test_unparsable_json_is_422_validation_error_in_turkish(self):
        response = self.patch_collection("{bozuk json")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "Geçersiz istek.", "code": "validation_error"})

    def test_wrong_field_type_is_422_validation_error(self):
        response = self.patch_collection('{"title": ["liste"]}')

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")

    def test_unmapped_http_error_status_gets_generic_turkish_message(self):
        with patch("apps.curation.api.collections.update_collection") as fake:
            fake.side_effect = HttpError(418, "I'm a teapot internal text")

            response = self.patch_collection('{"title": "x"}')

        self.assertEqual(response.status_code, 418)
        self.assertEqual(response.json(), {"detail": "İstek işlenemedi.", "code": "http_error"})

    def test_unsupported_method_on_ninja_endpoint_gets_single_error_shape(self):
        response = self.client.put("/api/chats")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(
            response.json(),
            {"detail": "Bu yöntem desteklenmiyor.", "code": "method_not_allowed"},
        )
        self.assertIn("GET", response["Allow"])

    def test_unsupported_method_on_plain_stream_view_gets_single_error_shape(self):
        response = self.client.get(f"/api/chats/{self.chat.pk}/messages/stream")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(
            response.json(),
            {"detail": "Bu yöntem desteklenmiyor.", "code": "method_not_allowed"},
        )
        self.assertEqual(response["Allow"], "POST")

    def test_405_outside_api_is_left_alone(self):
        with override_settings(ROOT_URLCONF="apps.core.tests.urls_other"):
            response = self.client.post("/baska/")

        self.assertEqual(response.status_code, 405)
        self.assertNotEqual(response.get("Content-Type"), "application/json")

    def test_unknown_api_path_keeps_the_single_error_shape(self):
        response = self.client.get("/api/yok-boyle-bir-yol")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Bulunamadı.", "code": "not_found"})


class ModelSettingTests(SimpleTestCase):
    def reload_with(self, value):
        env = {} if value is None else {"ANTHROPIC_MODEL": value}
        with patch.dict(os.environ, env):
            if value is None:
                os.environ.pop("ANTHROPIC_MODEL", None)
            return importlib.reload(base_settings).ANTHROPIC_MODEL

    def tearDown(self):
        importlib.reload(base_settings)

    def test_empty_environment_value_falls_back_to_default(self):
        self.assertEqual(self.reload_with(""), "claude-haiku-5-5")

    def test_unset_environment_value_falls_back_to_default(self):
        self.assertEqual(self.reload_with(None), "claude-haiku-5-5")

    def test_explicit_value_is_kept(self):
        self.assertEqual(self.reload_with("baska-model"), "baska-model")
