from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.films.tests.base import fake_vector, make_chunk, make_film


class FilmAdminTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            "admin", "admin@example.com", "pw-for-test"
        )
        self.client.force_login(user)
        self.film = make_film("Q1", title="Alpha")
        self.film.card_embedding = fake_vector("kart")
        self.film.save()
        self.chunk = make_chunk(self.film)

    def test_changelists_render_for_all_four_models(self):
        for model in ("film", "filmchunk", "filmprofile", "filmreview"):
            response = self.client.get(reverse(f"admin:films_{model}_changelist"))

            self.assertEqual(response.status_code, 200, model)

    def test_film_search_finds_by_title(self):
        response = self.client.get(reverse("admin:films_film_changelist"), {"q": "Alp"})

        self.assertContains(response, "Alpha")

    def test_detail_page_hides_vector_fields(self):
        film_page = self.client.get(reverse("admin:films_film_change", args=[self.film.pk]))
        chunk_page = self.client.get(reverse("admin:films_filmchunk_change", args=[self.chunk.pk]))

        self.assertNotContains(film_page, "card_embedding")
        self.assertNotContains(chunk_page, "id_embedding")

    def test_models_are_read_only(self):
        response = self.client.get(reverse("admin:films_film_add"))

        self.assertEqual(response.status_code, 403)
