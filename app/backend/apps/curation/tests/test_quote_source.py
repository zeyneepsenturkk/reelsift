"""Sözleşme 1.4: `CollectionFilm.quote_source` (alıntının alındığı kaynak)."""

from apps.curation.models import CollectionFilm
from apps.curation.tests.base import make_collection, make_story_film
from apps.curation.tests.test_collections_api import CollectionApiTestCase


class QuoteSourceTests(CollectionApiTestCase):
    def quote_sources(self, collection):
        body = self.client.get(self.url(pk=collection.pk)).json()
        return [film["quote_source"] for film in body["films"]]

    def make(self, *rows):
        """Her satır `(source_kind, source_url, source_quote)`; film başına bir satır."""
        films = [make_story_film(40 + n) for n in range(len(rows))]
        collection = make_collection(self.user, self.chat, films=films)
        for film, (kind, url, quote) in zip(films, rows, strict=True):
            CollectionFilm.objects.filter(collection=collection, film=film).update(
                source_kind=kind, source_url=url, source_quote=quote
            )
        return collection

    def test_the_three_kinds_get_their_labels(self):
        collection = self.make(
            ("plot", "https://en.wikipedia.org/wiki/A", "Alıntı bir."),
            ("overview", "https://www.themoviedb.org/movie/2", "Alıntı iki."),
            ("review", "https://example.test/review/3", "Alıntı üç."),
        )

        self.assertEqual(
            self.quote_sources(collection),
            [
                {
                    "kind": "plot",
                    "label": "Wikipedia · hikâye",
                    "url": "https://en.wikipedia.org/wiki/A",
                },
                {
                    "kind": "overview",
                    "label": "TMDB · tanıtım",
                    "url": "https://www.themoviedb.org/movie/2",
                },
                {
                    "kind": "review",
                    "label": "izleyici incelemesi",
                    "url": "https://example.test/review/3",
                },
            ],
        )

    def test_an_empty_url_gives_a_null_url(self):
        collection = self.make(("overview", "", "Alıntı."))

        self.assertEqual(
            self.quote_sources(collection),
            [{"kind": "overview", "label": "TMDB · tanıtım", "url": None}],
        )

    def test_without_a_quote_or_a_kind_quote_source_is_null(self):
        collection = self.make(
            ("plot", "https://en.wikipedia.org/wiki/A", ""),
            ("", "", "Alıntı var ama tür kayıtlı değil."),
        )

        self.assertEqual(self.quote_sources(collection), [None, None])

    def test_the_field_comes_with_the_get_endpoint(self):
        body = self.client.get(self.url()).json()

        self.assertEqual(
            body["films"][0]["quote_source"],
            {
                "kind": "plot",
                "label": "Wikipedia · hikâye",
                "url": self.films[0].wikipedia_url,
            },
        )
