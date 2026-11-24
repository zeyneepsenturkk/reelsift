import json

from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user

TOKEN = "gercek-paylasim-anahtari"
# Yalnız koleksiyon + filmler (oturum ve kullanıcı sorgusu yok); owner `select_related` ile gelir.
EXPECTED_QUERIES = 2


class ShareTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.owner = make_user(
            "gizli_kullanici", first_name="Zeynep", last_name="Şentürk", email="gizli@example.test"
        )
        self.chat = make_chat(self.owner)
        self.films = [make_story_film(n) for n in (1, 2, 3)]
        self.collection = make_collection(
            self.owner,
            self.chat,
            films=self.films,
            status="approved",
            share_token=TOKEN,
            approved_at=timezone.now(),
        )
        self.anon = Client(enforce_csrf_checks=True)

    def share(self, token=TOKEN, client=None):
        return (client or self.anon).get(f"/api/share/{token}")


class SharedCollectionTests(ShareTestCase):
    def test_anonymous_gets_contract_shape(self):
        response = self.share()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body),
            {"title", "description", "films", "stats", "owner_display_name", "approved_at"},
        )
        self.assertEqual(body["title"], "Karlı kasabalar")
        self.assertEqual(body["owner_display_name"], "Zeynep Şentürk")
        self.assertEqual([film["position"] for film in body["films"]], [1, 2, 3])
        self.assertEqual(body["stats"]["film_count"], 3)
        self.assertEqual(body["films"][0]["countries"], ["Finlandiya"])
        self.assertTrue(body["films"][0]["rationale"])
        self.assertEqual(body["films"][0]["directors"], ["Director 1"])
        self.assertEqual(body["films"][0]["actors"], [])

    def test_owner_without_full_name_falls_back_to_username_display(self):
        owner = make_user("takma_ad")
        make_collection(
            owner,
            make_chat(owner),
            films=self.films[:1],
            status="approved",
            share_token="baska",
            approved_at=timezone.now(),
        )

        self.assertEqual(self.share("baska").json()["owner_display_name"], "takma_ad")

    def test_response_never_carries_identity(self):
        response = self.share()

        text = response.content.decode()
        for secret in ("gizli_kullanici", "gizli@example.test", TOKEN):
            self.assertNotIn(secret, text)
        body = response.json()
        for key in ("id", "chat_id", "share_url", "status", "version", "owner", "username"):
            self.assertNotIn(key, body)
        self.assertEqual(len(response.cookies), 0)

    def test_logged_in_user_gets_the_same_page(self):
        client = Client()
        client.force_login(make_user("baska"))

        self.assertEqual(self.share(client=client).json(), self.share().json())

    def test_rejected_tokens_all_return_the_same_404(self):
        draft = make_collection(
            self.owner, self.chat, films=self.films, share_token="taslak-anahtar"
        )
        self.assertEqual(draft.status, "draft")
        no_token = make_collection(self.owner, self.chat, films=self.films, status="approved")
        self.assertIsNone(no_token.share_token)

        responses = [
            self.share("taslak-anahtar"),
            self.share("yanlis-anahtar"),
            self.share("None"),
            self.share("x" * 500),
            self.share(""),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 404)
        self.assertEqual(responses[0].json(), {"detail": "Bulunamadı.", "code": "not_found"})
        self.assertEqual(len({response.content for response in responses}), 1)

    def test_query_count_is_constant(self):
        with self.assertNumQueries(EXPECTED_QUERIES):
            self.share()

        more = [make_story_film(n) for n in range(10, 20)]
        for index, film in enumerate(more):
            self.collection.films.create(
                film=film, position=10 + index, rationale="Gerekçe.", source_quote=""
            )

        with self.assertNumQueries(EXPECTED_QUERIES):
            response = self.share()
        self.assertEqual(len(response.json()["films"]), 13)

    def test_share_is_limited_to_60_requests_per_minute(self):
        statuses = [self.share("yok").status_code for _ in range(60)]
        blocked = self.share()

        self.assertEqual(set(statuses), {404})
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["code"], "rate_limited")

    def test_login_attempts_do_not_consume_the_share_counter(self):
        for _ in range(10):
            self.anon.post(
                "/api/auth/login",
                data=json.dumps({"username": "x", "password": "y"}),
                content_type="application/json",
            )

        self.assertEqual(self.share().status_code, 200)
