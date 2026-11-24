import json

from django.test import Client, TestCase

from apps.curation.models import Collection
from apps.curation.services.approval import approve_collection
from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user


class CollectionApiTestCase(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.other = make_user("other")
        self.chat = make_chat(self.user)
        self.films = [make_story_film(n, vote_count=100 * n) for n in (1, 2, 3)]
        self.collection = make_collection(self.user, self.chat, films=self.films)
        self.client.force_login(self.user)

    def url(self, suffix="", pk=None):
        return f"/api/collections/{pk or self.collection.pk}{suffix}"

    def patch(self, payload, **kwargs):
        return self.client.patch(
            self.url(), data=json.dumps(payload), content_type="application/json", **kwargs
        )


class GetCollectionTests(CollectionApiTestCase):
    def test_returns_collection_in_contract_shape(self):
        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], self.collection.pk)
        self.assertEqual(body["chat_id"], self.chat.pk)
        self.assertEqual(body["status"], "draft")
        self.assertEqual(body["version"], 1)
        self.assertIsNone(body["share_url"])
        self.assertEqual([film["position"] for film in body["films"]], [1, 2, 3])
        first = body["films"][0]
        self.assertEqual(first["film_id"], self.films[0].pk)
        self.assertEqual(first["title"], "Snow Town 1")
        self.assertIsNone(first["title_tr"])
        self.assertEqual(first["countries"], ["Finlandiya"])
        self.assertEqual(first["poster_url"], "https://image.tmdb.org/t/p/w342/poster1.jpg")
        self.assertEqual([source["kind"] for source in first["sources"]], ["wikipedia", "tmdb"])
        self.assertEqual(
            body["stats"],
            {
                "film_count": 3,
                "year_min": 2001,
                "year_max": 2003,
                "country_count": 1,
                "avg_vote_count": 200.0,
            },
        )

    def test_film_without_story_has_no_wikipedia_source(self):
        film = make_story_film(8, plot="", plot_source="")
        collection = make_collection(self.user, self.chat, films=[film])

        body = self.client.get(self.url(pk=collection.pk)).json()

        self.assertEqual([source["kind"] for source in body["films"][0]["sources"]], ["tmdb"])

    def test_turkish_country_names_and_missing_poster(self):
        film = make_story_film(9, countries=["United States", "Atlantis"], poster_path="")
        collection = make_collection(self.user, self.chat, films=[film])

        body = self.client.get(self.url(pk=collection.pk)).json()

        self.assertEqual(body["films"][0]["countries"], ["ABD", "Atlantis"])
        self.assertIsNone(body["films"][0]["poster_url"])

    def test_directors_and_actors_come_with_limits(self):
        film = make_story_film(
            10,
            directors=["D1", "D2", "D3", "D4"],
            actors=["A1", "A2", "A3", "A4", "A5", "A6", "A7"],
        )
        collection = make_collection(self.user, self.chat, films=[film])

        body = self.client.get(self.url(pk=collection.pk)).json()

        self.assertEqual(body["films"][0]["directors"], ["D1", "D2", "D3"])
        self.assertEqual(body["films"][0]["actors"], ["A1", "A2", "A3", "A4", "A5", "A6"])

    def test_missing_directors_and_actors_are_empty_lists(self):
        film = make_story_film(11, directors=[], actors=[])
        collection = make_collection(self.user, self.chat, films=[film])

        body = self.client.get(self.url(pk=collection.pk)).json()

        self.assertEqual(body["films"][0]["directors"], [])
        self.assertEqual(body["films"][0]["actors"], [])

    def test_query_count_does_not_grow_with_film_count(self):
        with self.assertNumQueries(4):  # oturum, kullanıcı, koleksiyon, filmler
            self.client.get(self.url())

    def test_other_users_collection_is_404(self):
        self.client.force_login(self.other)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not_found")

    def test_unauthenticated_is_401(self):
        self.client.logout()

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "not_authenticated")


class PatchCollectionTests(CollectionApiTestCase):
    def test_updates_title_and_description_and_bumps_version(self):
        response = self.patch({"title": "  Yeni başlık ", "description": "Yeni açıklama"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["title"], "Yeni başlık")
        self.assertEqual(body["description"], "Yeni açıklama")
        self.assertEqual(body["version"], 2)

    def test_empty_body_and_blank_title_are_422(self):
        self.assertEqual(self.patch({}).status_code, 422)
        blank = self.patch({"title": "   "})
        self.assertEqual(blank.status_code, 422)
        self.assertEqual(blank.json()["code"], "validation_error")

    def test_too_long_title_is_422(self):
        self.assertEqual(self.patch({"title": "x" * 201}).status_code, 422)

    def test_approved_collection_is_locked(self):
        approve_collection(self.collection, self.user)

        response = self.patch({"title": "Değişmesin"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "collection_locked")

    def test_other_users_collection_is_404(self):
        self.client.force_login(self.other)

        self.assertEqual(self.patch({"title": "Hack"}).status_code, 404)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.title, "Karlı kasabalar")

    def test_csrf_token_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.patch(
            self.url(), data=json.dumps({"title": "X"}), content_type="application/json"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "forbidden")


class DeleteFilmTests(CollectionApiTestCase):
    def test_removes_film_and_renumbers(self):
        response = self.client.delete(self.url(f"/films/{self.films[0].pk}"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [film["film_id"] for film in body["films"]], [self.films[1].pk, self.films[2].pk]
        )
        self.assertEqual([film["position"] for film in body["films"]], [1, 2])
        self.assertEqual(body["version"], 2)
        self.assertEqual(body["stats"]["film_count"], 2)

    def test_unknown_film_is_404(self):
        response = self.client.delete(self.url("/films/999999"))

        self.assertEqual(response.status_code, 404)

    def test_approved_collection_is_locked(self):
        approve_collection(self.collection, self.user)

        response = self.client.delete(self.url(f"/films/{self.films[0].pk}"))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "collection_locked")
        self.assertEqual(self.collection.films.count(), 3)

    def test_other_users_collection_is_404(self):
        self.client.force_login(self.other)

        response = self.client.delete(self.url(f"/films/{self.films[0].pk}"))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.collection.films.count(), 3)


class ApproveTests(CollectionApiTestCase):
    def test_owner_approves_and_gets_share_url(self):
        response = self.client.post(self.url("/approve"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "approved")
        self.assertTrue(body["share_url"].startswith("/k/"))
        self.assertIsNotNone(body["approved_at"])
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.status, Collection.Status.APPROVED)
        self.assertEqual(body["share_url"], f"/k/{self.collection.share_token}")

    def test_other_users_collection_is_404_and_stays_draft(self):
        self.client.force_login(self.other)

        response = self.client.post(self.url("/approve"))

        self.assertEqual(response.status_code, 404)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.status, Collection.Status.DRAFT)

    def test_collection_without_films_is_422(self):
        empty = make_collection(self.user, self.chat)

        response = self.client.post(self.url("/approve", pk=empty.pk))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "empty_collection")

    def test_second_approval_is_409(self):
        self.client.post(self.url("/approve"))

        response = self.client.post(self.url("/approve"))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "already_approved")

    def test_unauthenticated_is_401(self):
        self.client.logout()

        self.assertEqual(self.client.post(self.url("/approve")).status_code, 401)

    def test_share_tokens_are_unique_per_collection(self):
        other = make_collection(self.user, self.chat, films=self.films[:1])

        first = approve_collection(self.collection, self.user)
        second = approve_collection(other, self.user)

        self.assertNotEqual(first.share_token, second.share_token)
