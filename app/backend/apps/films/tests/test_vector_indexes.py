from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings

from apps.core.exceptions import ServiceError
from apps.films.models import Film, FilmChunk
from apps.films.services import embedding, loading
from apps.films.services import vector_indexes as vi
from apps.films.tests.base import fake_embedder, make_archive_root, make_chunk, make_film

CHUNK_INDEX = "films_filmchunk_hnsw"
CARD_INDEX = "films_film_card_hnsw"


def index_definition(name: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname = %s", [name])
        row = cursor.fetchone()
    return row[0] if row else None


class VectorIndexHelperTests(TestCase):
    def test_model_indexes_are_hnsw_with_expected_names(self):
        self.assertEqual([i.name for i in vi.hnsw_indexes(FilmChunk)], [CHUNK_INDEX])
        self.assertEqual([i.name for i in vi.hnsw_indexes(Film)], [CARD_INDEX])

    def test_drop_then_build_restores_the_identical_definition(self):
        before = index_definition(CHUNK_INDEX)

        vi.drop_indexes(FilmChunk)
        self.assertIsNone(index_definition(CHUNK_INDEX))
        self.assertEqual(vi.missing_indexes(FilmChunk)[0].name, CHUNK_INDEX)
        vi.build_missing_indexes(FilmChunk)

        self.assertEqual(index_definition(CHUNK_INDEX), before)
        self.assertIn("hnsw", before)
        self.assertIn("halfvec_cosine_ops", before)

    def test_build_is_a_no_op_when_nothing_is_missing(self):
        before = index_definition(CARD_INDEX)

        vi.build_missing_indexes(Film)

        self.assertEqual(index_definition(CARD_INDEX), before)

    def test_maintenance_work_mem_is_restored_after_build(self):
        with connection.cursor() as cursor:
            cursor.execute("SHOW maintenance_work_mem")
            original = cursor.fetchone()[0]
        vi.drop_indexes(Film)

        with override_settings(FILMS_INDEX_MAINTENANCE_WORK_MEM="256MB"):
            vi.build_missing_indexes(Film)

        with connection.cursor() as cursor:
            cursor.execute("SHOW maintenance_work_mem")
            self.assertEqual(cursor.fetchone()[0], original)

    def test_ensure_vector_indexes_recreates_indexes_left_missing(self):
        vi.drop_indexes(Film)
        vi.drop_indexes(FilmChunk)

        vi.ensure_vector_indexes()

        self.assertIsNotNone(index_definition(CARD_INDEX))
        self.assertIsNotNone(index_definition(CHUNK_INDEX))


class BulkWindowTests(TestCase):
    def test_empty_table_drops_and_rebuilds(self):
        before = index_definition(CHUNK_INDEX)
        with vi.bulk_write_window(FilmChunk, 10) as dropped:
            self.assertTrue(dropped)
            self.assertIsNone(index_definition(CHUNK_INDEX))

        self.assertEqual(index_definition(CHUNK_INDEX), before)

    def test_small_load_into_filled_table_leaves_index_alone(self):
        make_chunk(make_film("Q1"))

        with vi.bulk_write_window(FilmChunk, 5) as dropped:
            self.assertFalse(dropped)
            self.assertIsNotNone(index_definition(CHUNK_INDEX))

    @override_settings(FILMS_BULK_INDEX_THRESHOLD=3)
    def test_large_load_into_filled_table_drops_index(self):
        make_chunk(make_film("Q1"))

        with vi.bulk_write_window(FilmChunk, 3) as dropped:
            self.assertTrue(dropped)
            self.assertIsNone(index_definition(CHUNK_INDEX))

        self.assertIsNotNone(index_definition(CHUNK_INDEX))

    def test_nothing_incoming_never_drops(self):
        with vi.bulk_write_window(FilmChunk, 0) as dropped:
            self.assertFalse(dropped)

    def test_index_is_rebuilt_when_the_write_fails(self):
        with self.assertRaises(RuntimeError):
            with vi.bulk_write_window(FilmChunk, 10):
                self.assertIsNone(index_definition(CHUNK_INDEX))
                raise RuntimeError("yazım yarıda kesildi")

        self.assertIsNotNone(index_definition(CHUNK_INDEX))


class LoadArchiveIndexTests(TestCase):
    def setUp(self):
        self.temp, self.root, self.info = make_archive_root()
        self.addCleanup(self.temp.cleanup)

    def test_load_archive_leaves_both_indexes_in_place(self):
        before = (index_definition(CHUNK_INDEX), index_definition(CARD_INDEX))

        loading.load_archive(self.root)

        self.assertEqual((index_definition(CHUNK_INDEX), index_definition(CARD_INDEX)), before)

    def test_failed_load_does_not_leave_indexes_missing(self):
        with patch(
            "apps.films.services.loading._write_chunks", side_effect=RuntimeError("yarıda kesildi")
        ):
            with self.assertRaises(RuntimeError):
                loading.load_archive(self.root)

        self.assertIsNotNone(index_definition(CHUNK_INDEX))

    def test_load_archive_repairs_indexes_left_missing_by_an_earlier_crash(self):
        vi.drop_indexes(FilmChunk)

        loading.load_archive(self.root)

        self.assertIsNotNone(index_definition(CHUNK_INDEX))


class AdvisoryLockTests(TestCase):
    def setUp(self):
        self.temp, self.root, self.info = make_archive_root()
        self.addCleanup(self.temp.cleanup)
        # Kilidi başka bir bağlantı tutar (oturum düzeyi kilit işlemden bağımsızdır).
        self.other = connection.copy()
        self.other.ensure_connection()
        with self.other.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [vi.FILMS_WRITE_LOCK_KEY])
        self.addCleanup(self.other.close)

    def assert_locked_error(self, ctx):
        self.assertEqual(ctx.exception.code, "films_write_locked")
        self.assertIsNotNone(index_definition(CHUNK_INDEX))
        self.assertIsNotNone(index_definition(CARD_INDEX))

    def test_load_archive_fails_cleanly_while_lock_is_held(self):
        with self.assertRaises(ServiceError) as ctx:
            loading.load_archive(self.root)

        self.assert_locked_error(ctx)
        self.assertFalse(Film.objects.exists())

    def test_embed_missing_fails_cleanly_while_lock_is_held(self):
        with self.assertRaises(ServiceError) as ctx:
            embedding.embed_missing(self.root, embedder=fake_embedder)

        self.assert_locked_error(ctx)

    def test_index_window_refuses_while_lock_is_held(self):
        with self.assertRaises(ServiceError) as ctx:
            with vi.bulk_write_window(FilmChunk, 10):
                self.fail("pencere kilitliyken açılmamalı")

        self.assert_locked_error(ctx)

    def test_lock_is_reentrant_within_one_session_and_released_afterwards(self):
        with self.other.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [vi.FILMS_WRITE_LOCK_KEY])

        with vi.films_write_lock():
            with vi.bulk_write_window(FilmChunk, 10):
                pass

        with self.other.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [vi.FILMS_WRITE_LOCK_KEY])
            self.assertTrue(cursor.fetchone()[0])
