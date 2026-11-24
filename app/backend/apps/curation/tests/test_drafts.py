from django.test import TestCase

from apps.core.exceptions import ServiceError
from apps.curation.models import Collection, CollectionFilm
from apps.curation.services.drafts import KeptFilm, NewFilm, save_draft
from apps.curation.tests.base import (
    PLOT_QUOTE,
    make_chat,
    make_collection,
    make_story_film,
    make_user,
)


def new_film(film, quote=PLOT_QUOTE, kind="plot", rationale="Karlı bir kasaba."):
    return NewFilm(film_id=film.pk, rationale=rationale, source_quote=quote, source_kind=kind)


class SaveDraftTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.chat = make_chat(self.user)
        self.films = [make_story_film(n) for n in (1, 2, 3)]

    def save(self, entries, **kwargs):
        return save_draft(
            owner=self.user,
            chat=self.chat,
            request={"en_query": "snow"},
            title="Başlık",
            description="Açıklama",
            entries=entries,
            **kwargs,
        )

    def test_creates_collection_with_verified_rows_in_order(self):
        collection_id = self.save([new_film(self.films[1]), new_film(self.films[0])])

        rows = list(CollectionFilm.objects.filter(collection_id=collection_id))
        self.assertEqual([row.film_id for row in rows], [self.films[1].pk, self.films[0].pk])
        self.assertEqual([row.position for row in rows], [1, 2])
        self.assertEqual(rows[0].source_url, self.films[1].wikipedia_url)
        collection = Collection.objects.get(pk=collection_id)
        self.assertEqual(collection.status, "draft")
        self.assertEqual(collection.version, 1)
        self.assertEqual(collection.request, {"en_query": "snow"})

    def test_unverified_quote_is_rejected_and_nothing_is_written(self):
        entries = [new_film(self.films[0]), new_film(self.films[1], quote="Made up sentence here.")]

        with self.assertRaises(ServiceError) as ctx:
            self.save(entries)

        self.assertEqual(ctx.exception.code, "quote_unverified")
        self.assertEqual(Collection.objects.count(), 0)
        self.assertEqual(CollectionFilm.objects.count(), 0)

    def test_empty_and_duplicate_entries_are_rejected(self):
        with self.assertRaises(ServiceError) as ctx:
            self.save([])
        self.assertEqual(ctx.exception.code, "empty_collection")
        with self.assertRaises(ServiceError):
            self.save([new_film(self.films[0]), new_film(self.films[0])])

    def test_empty_rationale_is_rejected(self):
        with self.assertRaises(ServiceError):
            self.save([new_film(self.films[0], rationale="  ")])

    def test_update_keeps_kept_row_untouched_and_bumps_version(self):
        base = make_collection(self.user, self.chat, films=self.films[:2])
        kept_before = CollectionFilm.objects.get(collection=base, film=self.films[0])

        self.save(
            [KeptFilm(self.films[0].pk), new_film(self.films[2], rationale="Yeni gerekçe.")],
            base=base,
        )

        base.refresh_from_db()
        self.assertEqual(base.version, 2)
        rows = list(CollectionFilm.objects.filter(collection=base))
        self.assertEqual([row.film_id for row in rows], [self.films[0].pk, self.films[2].pk])
        kept_after = rows[0]
        self.assertEqual(kept_after.rationale, kept_before.rationale)
        self.assertEqual(kept_after.source_quote, kept_before.source_quote)
        self.assertEqual(rows[1].rationale, "Yeni gerekçe.")
        self.assertFalse(CollectionFilm.objects.filter(film=self.films[1]).exists())

    def test_kept_film_missing_from_base_is_rejected(self):
        base = make_collection(self.user, self.chat, films=self.films[:1])

        with self.assertRaises(ServiceError):
            self.save([KeptFilm(self.films[2].pk)], base=base)

    def test_approved_base_is_locked(self):
        base = make_collection(self.user, self.chat, films=self.films[:1], status="approved")

        with self.assertRaises(ServiceError) as ctx:
            self.save([KeptFilm(self.films[0].pk)], base=base)

        self.assertEqual(ctx.exception.code, "collection_locked")
