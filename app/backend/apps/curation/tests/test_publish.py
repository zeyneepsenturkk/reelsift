import json
import os
from datetime import datetime
from unittest import mock

import httpx2
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.exceptions import ServiceError
from apps.curation.models import Collection
from apps.curation.services import publishing
from apps.curation.services.publish_config import publish_enabled
from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user

SITE = "https://site.test"
KEY = "sahte-test-anahtari"
PAGE = "https://site.test/s/karli-kasabalar/"

COLLECTION_KEYS = {"source_id", "title", "description", "approved_at", "films"}
FILM_KEYS = {
    "position",
    "title",
    "title_tr",
    "year",
    "countries",
    "directors",
    "actors",
    "poster_url",
    "rationale",
    "source_quote",
    "quote_source",
    "sources",
}


class FakeSite:
    """Sitenin yerine geçen taşıyıcı: istekleri kaydeder, verilen cevabı (ya da hatayı) döndürür."""

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else self.created()
        self.error = error
        self.requests: list[httpx2.Request] = []

    @staticmethod
    def created(url=PAGE, status=201):
        return httpx2.Response(status, json={"url": url, "created": status == 201})

    def __call__(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response

    def body(self, index=0):
        return json.loads(self.requests[index].content)


class PublishTestCase(TestCase):
    def setUp(self):
        self.owner = make_user("editor")
        self.other = make_user("baska")
        self.chat = make_chat(self.owner)
        self.films = [
            make_story_film(
                1,
                directors=["Bir", "İki", "Üç", "Dört", "Beş"],
                actors=[f"Oyuncu {n}" for n in range(1, 9)],
            ),
            make_story_film(2),
            make_story_film(3, poster_path="", year=None, wikipedia_url="", tmdb_id=None),
        ]
        self.collection = make_collection(
            self.owner,
            self.chat,
            films=self.films,
            status="approved",
            share_token="paylasim-anahtari",
            approved_at=timezone.now(),
        )
        env = mock.patch.dict(os.environ, {"VITRIN_API_KEY": KEY})
        env.start()
        self.addCleanup(env.stop)
        settings = override_settings(VITRIN_URL=SITE + "/")
        settings.enable()
        self.addCleanup(settings.disable)
        self.client.force_login(self.owner)

    def use_site(self, site: FakeSite) -> FakeSite:
        patch = mock.patch.object(publishing, "TRANSPORT", httpx2.MockTransport(site))
        patch.start()
        self.addCleanup(patch.stop)
        return site

    def publish(self, pk=None):
        return self.client.post(f"/api/collections/{pk or self.collection.pk}/publish")

    def reload(self) -> Collection:
        return Collection.objects.get(pk=self.collection.pk)


class PayloadTests(PublishTestCase):
    def test_request_follows_the_contract(self):
        site = self.use_site(FakeSite())

        response = self.publish()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(site.requests), 1)
        request = site.requests[0]
        self.assertEqual(request.method, "POST")
        # Adresin sonundaki `/` kırpılır.
        self.assertEqual(str(request.url), f"{SITE}/api/v1/collections")
        self.assertEqual(request.headers["authorization"], f"Bearer {KEY}")
        self.assertEqual(request.headers["content-type"], "application/json")
        body = site.body()
        self.assertEqual(set(body), COLLECTION_KEYS)
        self.assertEqual(body["source_id"], self.collection.pk)
        self.assertEqual(body["title"], "Karlı kasabalar")
        self.assertEqual(body["description"], "Ağır tempolu polisiyeler.")
        self.assertEqual(datetime.fromisoformat(body["approved_at"]), self.reload().approved_at)
        self.assertEqual([film["position"] for film in body["films"]], [1, 2, 3])
        for film in body["films"]:
            self.assertEqual(set(film), FILM_KEYS)

    def test_film_fields_have_contract_values(self):
        site = self.use_site(FakeSite())

        self.publish()

        first = site.body()["films"][0]
        self.assertEqual(first["title"], "Snow Town 1")
        self.assertEqual(first["year"], 2001)
        self.assertEqual(first["countries"], ["Finlandiya"])
        self.assertEqual(first["poster_url"], "https://image.tmdb.org/t/p/w342/poster1.jpg")
        self.assertEqual(first["rationale"], "Snow Town 1 için gerekçe.")
        self.assertEqual(first["quote_source"]["kind"], "plot")
        self.assertEqual(first["quote_source"]["url"], self.films[0].wikipedia_url)
        self.assertEqual([source["kind"] for source in first["sources"]], ["wikipedia", "tmdb"])

    def test_identity_and_internal_fields_are_not_sent(self):
        site = self.use_site(FakeSite())

        self.publish()

        text = site.requests[0].content.decode()
        for name in ("film_id", "vote_count", "stats", "owner_display_name", "share_token"):
            self.assertNotIn(name, text)
        for secret in ("editor", "paylasim-anahtari"):
            self.assertNotIn(secret, text)

    def test_lists_are_clipped_to_contract_limits(self):
        site = self.use_site(FakeSite())

        self.publish()

        first = site.body()["films"][0]
        self.assertEqual(first["directors"], ["Bir", "İki", "Üç"])
        self.assertEqual(first["actors"], [f"Oyuncu {n}" for n in range(1, 7)])

    def test_missing_values_use_null_and_empty_forms(self):
        site = self.use_site(FakeSite())
        # Alıntısız satır: alıntı metni null değil boş, kaynağı null.
        row = self.collection.films.get(position=3)
        row.source_quote = ""
        row.source_kind = ""
        row.source_url = ""
        row.save()

        self.publish()

        third = site.body()["films"][2]
        self.assertEqual(third["source_quote"], "")
        self.assertIsNone(third["quote_source"])
        self.assertIsNone(third["title_tr"])
        self.assertIsNone(third["year"])
        self.assertIsNone(third["poster_url"])
        self.assertEqual(third["sources"], [])
        self.assertEqual(third["actors"], [])

    def test_text_is_cleaned_and_clipped(self):
        site = self.use_site(FakeSite())
        self.collection.title = "  Başlık\x07 sorunlu  "
        self.collection.description = "d" * 2500
        self.collection.save()
        row = self.collection.films.get(position=1)
        row.rationale = "g" * 2100
        row.save()

        self.publish()

        body = site.body()
        self.assertEqual(body["title"], "Başlık sorunlu")
        self.assertEqual(len(body["description"]), 2000)
        self.assertEqual(len(body["films"][0]["rationale"]), 2000)

    def test_poster_and_source_urls_outside_the_contract_are_dropped(self):
        site = self.use_site(FakeSite())
        self.films[0].poster_path = "/a b.jpg"
        self.films[0].wikipedia_url = "http://en.wikipedia.org/wiki/X"
        self.films[0].save()
        row = self.collection.films.get(position=1)
        row.source_url = "http://eski.example/x"
        row.save()

        self.publish()

        first = site.body()["films"][0]
        self.assertIsNone(first["poster_url"])
        self.assertIsNone(first["quote_source"]["url"])
        self.assertEqual([source["kind"] for source in first["sources"]], ["tmdb"])


class SuccessTests(PublishTestCase):
    def test_success_stores_url_and_returns_collection(self):
        self.use_site(FakeSite())

        response = self.publish()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["published_url"], PAGE)
        self.assertTrue(body["publish_enabled"])
        self.assertEqual(self.reload().published_url, PAGE)

    def test_site_200_for_known_collection_is_also_success(self):
        self.use_site(FakeSite(FakeSite.created(status=200)))

        self.assertEqual(self.publish().json()["published_url"], PAGE)

    def test_second_call_does_not_reach_the_site(self):
        site = self.use_site(FakeSite())

        first = self.publish()
        second = self.publish()

        self.assertEqual(first.status_code, second.status_code)
        self.assertEqual(second.json()["published_url"], PAGE)
        self.assertEqual(len(site.requests), 1)

    def test_already_published_url_is_returned_without_request(self):
        site = self.use_site(FakeSite())
        self.collection.published_url = "https://eski.example/s/x/"
        self.collection.save()

        response = self.publish()

        self.assertEqual(response.json()["published_url"], "https://eski.example/s/x/")
        self.assertEqual(site.requests, [])

    def test_redirects_are_not_followed(self):
        site = self.use_site(
            FakeSite(httpx2.Response(302, headers={"location": "https://baska.example/"}))
        )

        response = self.publish()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "publish_failed")
        self.assertEqual(len(site.requests), 1)


class RejectionTests(PublishTestCase):
    def test_draft_is_not_published(self):
        site = self.use_site(FakeSite())
        draft = make_collection(self.owner, self.chat, films=self.films[:1])

        response = self.publish(draft.pk)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "not_approved")
        self.assertEqual(site.requests, [])

    def test_other_users_collection_is_404(self):
        site = self.use_site(FakeSite())
        self.client.force_login(self.other)

        response = self.publish()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(site.requests, [])
        self.assertEqual(self.reload().published_url, "")

    def test_service_rejects_non_owner(self):
        with self.assertRaises(ServiceError) as ctx:
            publishing.publish_collection(self.collection, self.other)

        self.assertEqual((ctx.exception.code, ctx.exception.status_code), ("not_found", 404))

    def test_unknown_collection_is_404(self):
        self.assertEqual(self.publish(999999).status_code, 404)

    def test_login_is_required(self):
        self.client.logout()

        self.assertEqual(self.publish().status_code, 401)

    def test_disabled_without_key(self):
        site = self.use_site(FakeSite())

        with mock.patch.dict(os.environ, {"VITRIN_API_KEY": ""}):
            response = self.publish()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "publish_disabled")
        self.assertEqual(site.requests, [])

    def test_disabled_without_url_or_with_bad_scheme(self):
        site = self.use_site(FakeSite())
        for url in ("", "livegundem.com", "ftp://site.test", "https://", "   "):
            with self.subTest(url=url), override_settings(VITRIN_URL=url):
                self.assertFalse(publish_enabled())
                response = self.publish()
                self.assertEqual(response.json()["code"], "publish_disabled")
        self.assertEqual(site.requests, [])


class SiteFailureTests(PublishTestCase):
    def assert_failure(self, code, message_part=None):
        response = self.publish()

        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(body["code"], code)
        self.assertEqual(self.reload().published_url, "")
        for secret in (KEY, "gizli-site-cevabi"):
            self.assertNotIn(secret, response.content.decode())
        if message_part:
            self.assertIn(message_part, body["detail"])

    def test_unauthorized(self):
        self.use_site(FakeSite(httpx2.Response(401, json={"detail": "gizli-site-cevabi"})))

        self.assert_failure("publish_unauthorized", "anahtar")

    def test_rejected(self):
        self.use_site(FakeSite(httpx2.Response(422, json={"detail": ["gizli-site-cevabi"]})))

        self.assert_failure("publish_rejected")

    def test_other_status_codes_are_generic_failures(self):
        for status in (400, 413, 429, 500, 503):
            with self.subTest(status=status):
                self.use_site(FakeSite(httpx2.Response(status, text="gizli-site-cevabi")))
                self.assert_failure("publish_failed")

    def test_timeout_and_connection_errors_are_unreachable(self):
        request = httpx2.Request("POST", SITE)
        for error in (httpx2.ReadTimeout("t", request=request), httpx2.ConnectError("c")):
            with self.subTest(error=type(error).__name__):
                self.use_site(FakeSite(error=error))
                self.assert_failure("publish_unreachable", "Siteye ulaşılamadı")

    def test_broken_success_bodies_are_failures(self):
        bodies = {
            "json değil": httpx2.Response(201, text="<html>gizli-site-cevabi</html>"),
            "url yok": httpx2.Response(201, json={"created": True}),
            "liste": httpx2.Response(201, json=["x"]),
            "url metin değil": httpx2.Response(201, json={"url": 5}),
            "javascript": httpx2.Response(201, json={"url": "javascript:alert(1)"}),
            "mutlak değil": httpx2.Response(201, json={"url": "/s/x/"}),
            "ana makine yok": httpx2.Response(201, json={"url": "https:///s/x/"}),
            "çok uzun": httpx2.Response(201, json={"url": "https://site.test/" + "a" * 500}),
            "boşluklu": httpx2.Response(201, json={"url": "https://site.test/a b"}),
        }
        for name, response in bodies.items():
            with self.subTest(name):
                self.use_site(FakeSite(response))
                self.assert_failure("publish_failed")

    def test_key_is_never_logged(self):
        self.use_site(FakeSite(httpx2.Response(401, json={"detail": "gizli-site-cevabi"})))

        with self.assertLogs("apps.curation.services.publishing", level="WARNING") as logs:
            self.publish()

        joined = "\n".join(logs.output)
        self.assertNotIn(KEY, joined)
        self.assertNotIn("gizli-site-cevabi", joined)

    def test_failure_can_be_retried(self):
        self.use_site(FakeSite(httpx2.Response(500)))
        self.publish()
        site = self.use_site(FakeSite())

        response = self.publish()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["published_url"], PAGE)
        self.assertEqual(len(site.requests), 1)


class CollectionOutFieldsTests(PublishTestCase):
    def test_get_carries_publish_fields(self):
        body = self.client.get(f"/api/collections/{self.collection.pk}").json()

        self.assertIsNone(body["published_url"])
        self.assertTrue(body["publish_enabled"])

    def test_publish_enabled_follows_settings_not_status(self):
        draft = make_collection(self.owner, self.chat, films=self.films[:1])
        with override_settings(VITRIN_URL=""):
            body = self.client.get(f"/api/collections/{draft.pk}").json()
        self.assertFalse(body["publish_enabled"])

        body = self.client.get(f"/api/collections/{draft.pk}").json()
        self.assertEqual(body["status"], "draft")
        self.assertTrue(body["publish_enabled"])

    def test_published_url_survives_when_publishing_is_disabled(self):
        self.collection.published_url = PAGE
        self.collection.save()

        with override_settings(VITRIN_URL=""):
            body = self.client.get(f"/api/collections/{self.collection.pk}").json()

        self.assertEqual(body["published_url"], PAGE)
        self.assertFalse(body["publish_enabled"])

    def test_shared_page_is_unchanged(self):
        body = self.client.get("/api/share/paylasim-anahtari").json()

        self.assertEqual(
            set(body),
            {"title", "description", "films", "stats", "owner_display_name", "approved_at"},
        )
