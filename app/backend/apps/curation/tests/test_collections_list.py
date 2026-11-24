from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user

LIST_URL = "/api/collections"
# Oturum + kullanıcı + koleksiyonlar + filmler. Koleksiyon sayısından bağımsız olmalı.
EXPECTED_QUERIES = 4


class ListCollectionsTests(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.other = make_user("other")
        self.chat = make_chat(self.user)
        self.films = [make_story_film(n) for n in range(1, 9)]
        self.now = timezone.now()
        self.client.force_login(self.user)

    def approved(self, owner=None, films=(), age_days=0, **overrides):
        stamp = self.now - timedelta(days=age_days)
        return make_collection(
            owner or self.user,
            make_chat(owner or self.user),
            films=films,
            status="approved",
            share_token=f"tok-{owner.pk if owner else self.user.pk}-{age_days}-{len(overrides)}",
            approved_at=stamp,
            **overrides,
        )

    def test_anonymous_gets_401(self):
        self.client.logout()

        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "not_authenticated")

    def test_empty_list(self):
        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_only_own_approved_collections_newest_first(self):
        old = self.approved(films=self.films[:2], age_days=5, title="Eski")
        new = self.approved(films=self.films[:3], age_days=1, title="Yeni")
        make_collection(self.user, self.chat, films=self.films[:2], title="Taslak")
        self.approved(owner=self.other, films=self.films[:2], title="Başkasının")

        body = self.client.get(LIST_URL).json()

        self.assertEqual([item["id"] for item in body], [new.pk, old.pk])
        self.assertEqual([item["title"] for item in body], ["Yeni", "Eski"])

    def test_summary_matches_contract_shape(self):
        collection = self.approved(films=self.films[:3], title="Karlı")

        item = self.client.get(LIST_URL).json()[0]

        self.assertEqual(
            set(item),
            {
                "id",
                "title",
                "status",
                "film_count",
                "poster_urls",
                "share_url",
                "approved_at",
                "updated_at",
            },
        )
        self.assertEqual(item["status"], "approved")
        self.assertEqual(item["film_count"], 3)
        self.assertEqual(item["share_url"], f"/k/{collection.share_token}")
        self.assertTrue(item["approved_at"])
        self.assertEqual(
            item["poster_urls"],
            [f"https://image.tmdb.org/t/p/w342/poster{n}.jpg" for n in (1, 2, 3)],
        )

    def test_poster_urls_follow_position_skip_missing_and_stop_at_six(self):
        films = [
            make_story_film(20 + n, poster_path="" if n == 1 else f"/p{n}.jpg") for n in range(9)
        ]
        self.approved(films=films)

        item = self.client.get(LIST_URL).json()[0]

        self.assertEqual(item["film_count"], 9)
        self.assertEqual(
            item["poster_urls"],
            [f"https://image.tmdb.org/t/p/w342/p{n}.jpg" for n in (0, 2, 3, 4, 5, 6)],
        )

    def test_query_count_does_not_grow_with_collection_count(self):
        self.approved(films=self.films[:3], age_days=1)
        with self.assertNumQueries(EXPECTED_QUERIES):
            self.client.get(LIST_URL)

        for age in range(2, 7):
            self.approved(films=self.films[:5], age_days=age)

        with self.assertNumQueries(EXPECTED_QUERIES):
            response = self.client.get(LIST_URL)
        self.assertEqual(len(response.json()), 6)
