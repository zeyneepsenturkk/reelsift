"""Yetki taraması: uç listesi OpenAPI şemasından okunur, yeni eklenen uç da otomatik kapsanır."""

import re

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import URLPattern, URLResolver, resolve

from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user
from config.api import api, api_not_found
from config.urls import urlpatterns

# Sözleşmedeki girişsiz dört uç ve sağlık kontrolü; listede olmayan her uç (ninja ya da düz Django
# view'ı) girişsiz 401 vermelidir.
PUBLIC = {
    ("get", "/api/health"),
    ("get", "/api/auth/me"),
    ("post", "/api/auth/login"),
    ("post", "/api/auth/logout"),
    ("get", "/api/share/{token}"),
}
WRITE_METHODS = {"post", "patch", "put", "delete"}
PROBE_METHODS = ("get", "post", "put", "patch", "delete")
PARAM = re.compile(r"\{(\w+)\}")
URL_PARAM = re.compile(r"<(?:\w+:)?(\w+)>")


def plain_api_paths() -> list[str]:
    """`/api/` altındaki ninja DIŞI yollar (akan cevap gibi düz Django view'ları), URL ağacından.

    Ninja uçları OpenAPI şemasından okunur; hiçbir yola uymayan istekler için konan 404 görünümü
    (`api_not_found`) taranmaz. Yol, gerçekten hangi görünüme çözüldüğüne bakılarak elenir.
    """
    found: list[str] = []

    def walk(patterns, prefix: str) -> None:
        for pattern in patterns:
            route = prefix + str(pattern.pattern)
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, route)
            elif isinstance(pattern, URLPattern) and route.startswith("/api/"):
                template = URL_PARAM.sub(lambda match: "{" + match.group(1) + "}", route)
                served = resolve(PARAM.sub("1", template)).func
                if served is not api_not_found and not served.__module__.startswith("ninja"):
                    found.append(template)

    walk(urlpatterns, "/")
    return found


def operations() -> list[tuple[str, str, bool]]:
    """(yöntem, yol, korumalı mı) üçlüleri."""
    found = []
    for path, methods in api.get_openapi_schema()["paths"].items():
        for method, operation in methods.items():
            found.append((method, path, "security" in operation))
    # Düz view'ların yöntemleri bilinmez: girişsiz denemede 405 dönmeyen yöntem desteklenir sayılır.
    probe = Client()
    for path in plain_api_paths():
        for method in PROBE_METHODS:
            if send(probe, method, PARAM.sub("1", path)).status_code != 405:
                found.append((method, path, (method, path) not in PUBLIC))
    return found


def plain_paths() -> set[str]:
    return set(plain_api_paths())


def protected() -> list[tuple[str, str]]:
    return [(method, path) for method, path, secured in operations() if secured]


def fill(path: str, **values) -> str:
    return PARAM.sub(lambda match: str(values[match.group(1)]), path)


def send(client, method: str, path: str, **extra):
    body = '{"title": "Değişti"}' if method in WRITE_METHODS else None
    if body is None:
        return getattr(client, method)(path, **extra)
    return getattr(client, method)(path, data=body, content_type="application/json", **extra)


class AccessTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.victim = make_user("kurban")
        self.attacker = make_user("saldirgan")
        self.chat = make_chat(self.victim, title="Kurbanın sohbeti")
        self.film = make_story_film(1)
        self.collection = make_collection(self.victim, self.chat, films=[self.film])

    def own_ids(self) -> dict:
        return {
            "chat_id": self.chat.pk,
            "collection_id": self.collection.pk,
            "film_id": self.film.pk,
            "token": "x",
        }


class PublicSurfaceTests(AccessTestCase):
    def test_only_the_documented_endpoints_are_public(self):
        public = {(method, path) for method, path, secured in operations() if not secured}

        self.assertEqual(public, PUBLIC)

    def test_url_scan_finds_the_plain_stream_view(self):
        self.assertEqual(plain_api_paths(), ["/api/chats/{chat_id}/messages/stream"])

    def test_schema_and_docs_pages_are_not_served(self):
        client = Client()
        for path in ("/api/", "/api/openapi.json", "/api/docs"):
            with self.subTest(path=path):
                response = client.get(path)

                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Bulunamadı.", "code": "not_found"})

    def test_every_protected_endpoint_rejects_anonymous_with_401(self):
        client = Client()
        for method, path in protected():
            with self.subTest(endpoint=f"{method} {path}"):
                response = send(client, method, fill(path, **self.own_ids()))

                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["code"], "not_authenticated")


class OwnershipTests(AccessTestCase):
    def test_other_users_chat_and_collection_are_404_on_every_endpoint(self):
        client = Client()
        client.force_login(self.attacker)
        with_ids = [
            (method, path) for method, path in protected() if PARAM.search(path) is not None
        ]
        self.assertTrue(with_ids)

        for method, path in with_ids:
            with self.subTest(endpoint=f"{method} {path}"):
                response = send(client, method, fill(path, **self.own_ids()))

                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["code"], "not_found")

    def test_failed_attempts_leave_the_victims_data_untouched(self):
        client = Client()
        client.force_login(self.attacker)
        for method, path in protected():
            if PARAM.search(path):
                send(client, method, fill(path, **self.own_ids()))

        self.collection.refresh_from_db()
        self.assertEqual(self.collection.title, "Karlı kasabalar")
        self.assertEqual(self.collection.status, "draft")
        self.assertIsNone(self.collection.share_token)
        self.assertEqual(self.collection.films.count(), 1)

    def test_owner_is_not_blocked_by_the_same_calls(self):
        client = Client()
        client.force_login(self.victim)

        response = client.get(f"/api/collections/{self.collection.pk}")

        self.assertEqual(response.status_code, 200)


class CsrfTests(AccessTestCase):
    def logged_in_client(self) -> Client:
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.victim)
        return client

    def test_writing_endpoints_reject_requests_without_csrf_header(self):
        client = self.logged_in_client()
        client.get("/api/auth/me")
        writes = [(method, path) for method, path in protected() if method in WRITE_METHODS]
        self.assertTrue(writes)

        for method, path in writes:
            with self.subTest(endpoint=f"{method} {path}"):
                response = send(client, method, fill(path, **self.own_ids()))

                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["code"], "forbidden")

        self.collection.refresh_from_db()
        self.assertEqual(self.collection.status, "draft")
        self.assertEqual(self.collection.title, "Karlı kasabalar")

    def test_ninja_writing_endpoints_accept_the_header(self):
        client = self.logged_in_client()
        client.get("/api/auth/me")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        ids = {**self.own_ids(), "chat_id": 999999, "collection_id": 999999}
        writes = [
            (method, path)
            for method, path in protected()
            if method in WRITE_METHODS and path not in plain_paths()
        ]

        for method, path in writes:
            with self.subTest(endpoint=f"{method} {path}"):
                response = send(client, method, fill(path, **ids), **headers)

                self.assertNotEqual(response.status_code, 403)

    def test_get_endpoints_need_no_csrf_header(self):
        client = self.logged_in_client()

        self.assertEqual(client.get("/api/chats").status_code, 200)
        self.assertEqual(client.get("/api/collections").status_code, 200)
