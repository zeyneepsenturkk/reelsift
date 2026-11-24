from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase, TestCase

from apps.core.exceptions import ServiceError
from apps.films.models import Film, FilmChunk
from apps.films.services import embedding, film_records, loading, sources
from apps.films.services.recipes import chunk_text
from apps.films.tests.base import (
    assert_vectors_equal,
    extra_record,
    fake_embedder,
    fake_vector,
    long_plot,
    make_archive_root,
    make_chunk,
    make_film,
)


class CosineTests(SimpleTestCase):
    def test_identical_vectors_have_cosine_one(self):
        vectors = np.stack([fake_vector("a"), fake_vector("b")])

        np.testing.assert_allclose(embedding.cosine_similarities(vectors, vectors), 1.0, atol=1e-3)

    def test_different_vectors_have_low_cosine(self):
        result = embedding.cosine_similarities(
            np.stack([fake_vector("a")]), np.stack([fake_vector("b")])
        )

        self.assertLess(result[0], 0.5)


class EmbedderTests(SimpleTestCase):
    def test_gpu_missing_raises_service_error_instead_of_running_on_cpu(self):
        embedding._load_model.cache_clear()
        with patch("torch.cuda.is_available", return_value=False):
            with self.assertRaises(ServiceError) as ctx:
                embedding.make_embedder()(["metin"], 512)

        self.assertEqual(ctx.exception.code, "gpu_unavailable")


class ProofTestCase(TestCase):
    def setUp(self):
        self.temp, self.root, self.info = make_archive_root()
        self.addCleanup(self.temp.cleanup)
        self.row = self.info["rows"][0]  # Q1: veri seti satırı, önek buradan kurulur

    def make_dataset_chunk(self, embedding_text=None):
        film = make_film("Q1", plot_source=Film.PlotSource.DATASET)
        text = "Chunk text."
        prefix = embedding.dataset_prefix(self.row)
        return make_chunk(film, 0, text, fake_vector(embedding_text or prefix + text))


class VerifyChunkRecipeTests(ProofTestCase):
    def test_matching_recipe_passes_with_cosine_close_to_one(self):
        self.make_dataset_chunk()

        proof = embedding.verify_chunk_recipe(self.root, fake_embedder, 20)

        self.assertEqual(proof.sample, 1)
        self.assertGreaterEqual(proof.min_cosine, embedding.PROOF_MIN_COSINE)

    def test_recipe_that_does_not_reproduce_the_vector_raises(self):
        self.make_dataset_chunk(embedding_text="başka bir metin")

        with self.assertRaises(ServiceError) as ctx:
            embedding.verify_chunk_recipe(self.root, fake_embedder, 20)

        self.assertEqual(ctx.exception.code, "recipe_mismatch")

    def test_without_ready_chunks_raises(self):
        with self.assertRaises(ServiceError) as ctx:
            embedding.verify_chunk_recipe(self.root, fake_embedder, 20)

        self.assertEqual(ctx.exception.code, "proof_no_sample")

    def test_sample_is_limited_to_the_requested_size(self):
        film = make_film("Q1", plot_source=Film.PlotSource.DATASET)
        prefix = embedding.dataset_prefix(self.row)
        for position in range(5):
            text = f"Chunk {position}."
            make_chunk(film, position, text, fake_vector(prefix + text))

        proof = embedding.verify_chunk_recipe(self.root, fake_embedder, 3)

        self.assertEqual(proof.sample, 3)


CARD_TEXT_101 = (
    "TMDB 101 (1999). A tagline. Overview of 101. Keywords: kw one, kw two. "
    "Genres: Drama, War. Country: United States of America."
)


class VerifyCardRecipeTests(TestCase):
    def setUp(self):
        self.temp, self.root, self.info = make_archive_root()
        self.addCleanup(self.temp.cleanup)

    def make_card_film(self, card_text=CARD_TEXT_101):
        film = make_film("Q1", tmdb_id=101, year=1999, overview="Overview of 101.")
        film.card_embedding = fake_vector(card_text)
        film.save()
        return film

    def test_matching_recipe_passes(self):
        self.make_card_film()

        proof = embedding.verify_card_recipe(self.root, fake_embedder, 20)

        self.assertGreaterEqual(proof.min_cosine, embedding.PROOF_MIN_COSINE)

    def test_text_comes_from_tmdb_record_not_from_merged_film_fields(self):
        film = self.make_card_film()
        # Birleştirilmiş alan veri seti değeriyle farklılaşsa da kanıt TMDB kaydını kullanır.
        Film.objects.filter(pk=film.pk).update(countries=["India"], genres=["drama film"])

        proof = embedding.verify_card_recipe(self.root, fake_embedder, 20)

        self.assertGreaterEqual(proof.min_cosine, embedding.PROOF_MIN_COSINE)

    def test_recipe_that_does_not_reproduce_the_vector_raises(self):
        self.make_card_film(card_text="başka kart")

        with self.assertRaises(ServiceError) as ctx:
            embedding.verify_card_recipe(self.root, fake_embedder, 20)

        self.assertEqual(ctx.exception.code, "recipe_mismatch")

    def test_films_without_tmdb_text_are_not_sampled(self):
        film = make_film("Q1")
        film.card_embedding = fake_vector("x")
        film.save()

        with self.assertRaises(ServiceError) as ctx:
            embedding.verify_card_recipe(self.root, fake_embedder, 20)

        self.assertEqual(ctx.exception.code, "proof_no_sample")


class EmbedMissingChunksTests(ProofTestCase):
    def test_renewed_film_uses_dataset_prefix_and_extra_film_uses_tmdb_prefix(self):
        renewed = make_film(
            "Q1", plot=long_plot(40), plot_source=Film.PlotSource.WIKIPEDIA_RENEWED, title="Tmdb Ad"
        )
        extra = make_film(
            "Q100",
            plot="An extra plot. Short.",
            plot_source=Film.PlotSource.WIKIPEDIA_ADDED,
            title="Extra",
            year=2010,
            genres=["Drama"],
            countries=["France"],
        )
        summary = embedding.EmbedSummary()

        embedding.embed_missing_chunks(self.root, fake_embedder, [renewed, extra], summary)

        pieces = chunk_text(long_plot(40))
        self.assertEqual(summary.chunks, len(pieces) + 1)
        stored = FilmChunk.objects.get(film=renewed, position=0)
        self.assertEqual(stored.text, pieces[0])  # önek metne yazılmaz
        prefix = embedding.dataset_prefix(self.row)
        assert_vectors_equal(stored.embedding, fake_vector(prefix + pieces[0]))
        extra_chunk = FilmChunk.objects.get(film=extra)
        expected = "Title: Extra (2010). Genres: Drama. Country: France. An extra plot. Short."
        assert_vectors_equal(extra_chunk.embedding, fake_vector(expected))

    def test_rerun_replaces_old_chunks_without_duplicating(self):
        film = make_film("Q100", plot="A plot. Short.", plot_source=Film.PlotSource.WIKIPEDIA_ADDED)
        make_chunk(film, 0, "eski")
        make_chunk(film, 1, "eski ikinci")

        embedding.embed_missing_chunks(self.root, fake_embedder, [film], embedding.EmbedSummary())

        self.assertEqual(
            list(FilmChunk.objects.filter(film=film).values_list("text", flat=True)),
            ["A plot. Short."],
        )


class EmbedMissingCardsTests(TestCase):
    def test_creates_card_vectors_and_skips_films_without_tmdb_text(self):
        with_text = make_film("Q1", overview="Overview.", genres=["Drama"])
        without_text = make_film("Q2")
        summary = embedding.EmbedSummary()

        embedding.embed_missing_cards(fake_embedder, [with_text, without_text], summary)

        with_text.refresh_from_db()
        without_text.refresh_from_db()
        self.assertEqual(summary.cards, 1)
        self.assertEqual(summary.skipped["kart_tmdb_metni_yok"], 1)
        assert_vectors_equal(
            with_text.card_embedding, fake_vector(embedding.film_card_text(with_text))
        )
        self.assertIsNone(without_text.card_embedding)


class ExtraCardTextTests(TestCase):
    def test_card_text_from_film_fields_equals_text_from_tmdb_style_record(self):
        extra = extra_record(1001, "Q100")
        film = Film(**film_records.build_extra_film(extra))

        self.assertEqual(
            embedding.film_card_text(film),
            embedding.tmdb_card_text(film_records.extra_as_tmdb(extra), film.year),
        )


class EmbedMissingTests(TestCase):
    def setUp(self):
        self.temp, self.root, self.info = make_archive_root()
        self.addCleanup(self.temp.cleanup)

    def load_with_matching_vectors(self):
        """Hazır vektörleri sahte modelin üreteceği değerlerle değiştirir (tarif kanıtı geçsin)."""
        loading.load_archive(self.root)
        rows = {row["movie_id"]: row for row in self.info["rows"]}
        for chunk in FilmChunk.objects.select_related("film"):
            prefix = embedding.dataset_prefix(rows[chunk.film.wikidata_id])
            chunk.embedding = fake_vector(prefix + chunk.text)
            chunk.save()
        tmdb_index = sources.load_tmdb_index(self.root)
        for film in Film.objects.filter(card_embedding__isnull=False).exclude(overview=""):
            record = tmdb_index.by_tmdb_id.get(film.tmdb_id)
            if record is None:
                continue  # ek kayıttan TMDB alanı alan arşiv filmi; kanıt örneğine girmez
            film.card_embedding = fake_vector(embedding.tmdb_card_text(record, film.year))
            film.save()

    def test_nothing_missing_is_a_no_op(self):
        make_film("Q1", plot="")
        film = Film.objects.get()
        film.card_embedding = fake_vector("var")
        film.save()

        summary = embedding.embed_missing(self.root, embedder=fail_if_called)

        self.assertEqual((summary.chunks, summary.cards, summary.proofs), (0, 0, []))

    def test_generates_missing_chunks_and_cards_after_proof(self):
        self.load_with_matching_vectors()

        summary = embedding.embed_missing(self.root, embedder=fake_embedder)

        self.assertEqual({p.kind for p in summary.proofs}, {"parça", "kart"})
        self.assertEqual(Film.objects.filter(chunks__isnull=True).exclude(plot="").count(), 0)
        self.assertEqual(Film.objects.filter(card_embedding__isnull=True).count(), 0)
        self.assertEqual(summary.chunk_films, 2)  # yenilenen Q3 + ek film Q100
        # İki ek film + ek kayıttan TMDB alanı alan, kartı bayat sayılan iki arşiv filmi (Q2, Q4).
        self.assertEqual(summary.cards, 4)
        self.assertEqual(summary.skipped["kart_tmdb_metni_yok"], 0)

    def test_second_run_finds_nothing_to_do(self):
        self.load_with_matching_vectors()
        embedding.embed_missing(self.root, embedder=fake_embedder)
        before = (
            FilmChunk.objects.count(),
            Film.objects.filter(card_embedding__isnull=False).count(),
        )

        summary = embedding.embed_missing(self.root, embedder=fail_if_called)

        self.assertEqual((summary.chunks, summary.cards), (0, 0))
        self.assertEqual(
            (FilmChunk.objects.count(), Film.objects.filter(card_embedding__isnull=False).count()),
            before,
        )

    def test_recipe_mismatch_stops_before_anything_is_written(self):
        loading.load_archive(self.root)  # yüklenen vektörler sahte modelin çıktısı değil
        chunks_before = FilmChunk.objects.count()

        with self.assertRaises(ServiceError) as ctx:
            embedding.embed_missing(self.root, embedder=fake_embedder)

        self.assertEqual(ctx.exception.code, "recipe_mismatch")
        self.assertEqual(FilmChunk.objects.count(), chunks_before)
        self.assertEqual(Film.objects.filter(card_embedding__isnull=True).count(), 4)


def fail_if_called(texts, max_seq_length):
    raise AssertionError("Eksik yokken model çağrılmamalı.")
