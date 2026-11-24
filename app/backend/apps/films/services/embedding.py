"""Eksik vektörlerin üretimi: bge-m3 ile, hazır vektörlerle aynı tarifle (bkz. recipes.py)."""

import logging
import random
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from django.db import reset_queries, transaction
from django.utils import timezone

from apps.core.exceptions import ServiceError
from apps.films.models import Film, FilmChunk
from apps.films.services import film_records, sources
from apps.films.services.recipes import card_text, chunk_text, film_prefix
from apps.films.services.vector_indexes import (
    bulk_write_window,
    ensure_vector_indexes,
    films_write_lock,
)

logger = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-m3"
CHUNK_MAX_SEQ_LENGTH = 512
CARD_MAX_SEQ_LENGTH = 256
DEFAULT_BATCH_SIZE = 64

PROOF_SAMPLE_SIZE = 20
PROOF_SEED = 20261116
PROOF_MIN_COSINE = 0.999

CHUNK_FILMS_PER_WRITE = 100
CARD_FILMS_PER_WRITE = 500

# (metinler, en fazla belirteç uzunluğu) -> float16 normalize vektörler; testte sahtesi verilir.
Embedder = Callable[[list[str], int], np.ndarray]


@dataclass
class ProofResult:
    kind: str
    sample: int
    min_cosine: float
    mean_cosine: float


@dataclass
class EmbedSummary:
    chunk_films: int = 0
    chunks: int = 0
    cards: int = 0
    proofs: list[ProofResult] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    seconds: dict[str, float] = field(default_factory=dict)

    def describe(self) -> str:
        proofs = "; ".join(
            f"{p.kind}: örnek={p.sample}, en düşük kosinüs={p.min_cosine:.5f}, "
            f"ortalama={p.mean_cosine:.5f}"
            for p in self.proofs
        )
        skipped = ", ".join(f"{reason}={count}" for reason, count in sorted(self.skipped.items()))
        return (
            f"Vektör üretimi: film={self.chunk_films}, parça={self.chunks}, kart={self.cards}; "
            f"tarif kanıtı: {proofs or 'gerekmedi (eksik yok)'}; atlananlar: {skipped or 'yok'}"
        )


@lru_cache(maxsize=1)
def _load_model():
    import torch
    from sentence_transformers import SentenceTransformer

    if not torch.cuda.is_available():
        raise ServiceError(
            "Ekran kartı görünmüyor; vektör üretimi CPU'da çalıştırılmaz.", "gpu_unavailable", 503
        )
    # Model /models önbelleğinde hazırdır; ağdan indirme denenmez.
    model = SentenceTransformer(MODEL_NAME, device="cuda", local_files_only=True)
    model.half()
    return model


def make_embedder(batch_size: int = DEFAULT_BATCH_SIZE) -> Embedder:
    def embed(texts: list[str], max_seq_length: int) -> np.ndarray:
        import torch

        model = _load_model()
        model.max_seq_length = max_seq_length
        try:
            vectors = model.encode(
                texts, batch_size=batch_size, normalize_embeddings=True, convert_to_numpy=True
            )
        except torch.cuda.OutOfMemoryError as exc:
            raise ServiceError(
                "Ekran kartı belleği yetmedi; --batch-size değerini küçültün ya da ekran kartını "
                "kullanan diğer işin bitmesini bekleyin.",
                "gpu_out_of_memory",
                503,
            ) from exc
        return vectors.astype(np.float16)

    return embed


def cosine_similarities(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    left = np.asarray(left, dtype=np.float32)
    right = np.asarray(right, dtype=np.float32)
    norms = np.linalg.norm(left, axis=1) * np.linalg.norm(right, axis=1)
    return np.einsum("ij,ij->i", left, right) / norms


def _check_proof(kind: str, generated: np.ndarray, stored: list[list[float]]) -> ProofResult:
    cosines = cosine_similarities(generated, np.array(stored))
    proof = ProofResult(kind, len(cosines), float(cosines.min()), float(cosines.mean()))
    logger.info(
        "Tarif kanıtı (%s): örnek=%s, en düşük kosinüs=%.5f", kind, proof.sample, proof.min_cosine
    )
    if proof.min_cosine < PROOF_MIN_COSINE:
        raise ServiceError(
            f"Vektör tarifi tutmuyor ({kind}): en düşük kosinüs {proof.min_cosine:.5f} "
            f"< {PROOF_MIN_COSINE}. Üretim durduruldu.",
            "recipe_mismatch",
            500,
        )
    return proof


def _sample_pks(queryset, size: int) -> list[int]:
    pks = list(queryset.values_list("pk", flat=True))
    return random.Random(PROOF_SEED).sample(pks, min(size, len(pks)))


def dataset_prefix(row: dict) -> str:
    return film_prefix(
        row["title"], film_records.parse_int(row["year"]), row["genre"], row["country"]
    )


def verify_chunk_recipe(root: Path, embedder: Embedder, sample_size: int) -> ProofResult:
    """Hazır vektörlü parçalardan örnek alır, aynı tarifle yeniden üretir, kosinüsü ölçer."""
    pks = _sample_pks(
        FilmChunk.objects.filter(film__plot_source=Film.PlotSource.DATASET), sample_size
    )
    if not pks:
        raise ServiceError("Tarif kanıtı için hazır vektörlü parça yok.", "proof_no_sample", 500)
    # Önek için film adı gerekir; parti başına tek sorguda birleştirilir.
    chunks = list(FilmChunk.objects.filter(pk__in=pks).select_related("film").order_by("pk"))
    rows = sources.read_dataset_rows_by_id(root, {chunk.film.wikidata_id for chunk in chunks})
    texts = [dataset_prefix(rows[chunk.film.wikidata_id]) + chunk.text for chunk in chunks]
    generated = embedder(texts, CHUNK_MAX_SEQ_LENGTH)
    return _check_proof("parça", generated, [chunk.embedding for chunk in chunks])


def film_card_text(film: Film) -> str:
    return card_text(
        film.title,
        film.year,
        film.tagline,
        film.overview or film.tr_overview,
        film.keywords,
        film.genres,
        film.countries,
    )


def tmdb_card_text(record: dict, year: int | None) -> str:
    """Kart metni TMDB kaydından kurulur (hazır kartlar da böyle üretildi); birleştirilmiş `Film`
    alanlarından kurulmaz, çünkü o alanlar TMDB'de boş olunca veri setindeki değeri taşır."""
    return card_text(
        record["title"],
        year,
        record["tagline"],
        record["overview"],
        record["keywords"],
        record["genres"],
        record["countries"],
    )


def verify_card_recipe(root: Path, embedder: Embedder, sample_size: int) -> ProofResult:
    """Hazır kart vektörlü (TMDB metni olan) filmlerden örnek alıp aynı tarifle yeniden üretir."""
    tmdb_index = sources.load_tmdb_index(root)
    # Ek kayıttan TMDB alanı alan arşiv filmlerinin kartı TMDB kaydı olmadan üretildi; girmez.
    candidates = [
        pk
        for pk, tmdb_id in Film.objects.filter(card_embedding__isnull=False)
        .exclude(overview="")
        .values_list("pk", "tmdb_id")
        if tmdb_id in tmdb_index.by_tmdb_id
    ]
    pks = random.Random(PROOF_SEED).sample(candidates, min(sample_size, len(candidates)))
    if not pks:
        raise ServiceError("Tarif kanıtı için hazır kart vektörü yok.", "proof_no_sample", 500)
    films = list(Film.objects.filter(pk__in=pks).order_by("pk"))
    texts = [tmdb_card_text(tmdb_index.by_tmdb_id[film.tmdb_id], film.year) for film in films]
    generated = embedder(texts, CARD_MAX_SEQ_LENGTH)
    return _check_proof("kart", generated, [film.card_embedding for film in films])


def _chunk_prefix(film: Film, dataset_rows: dict[str, dict]) -> str:
    """Yenilenen filmler veri setindeki ad/tür/ülke yazımıyla (hazır vektörlerle aynı), ek filmler
    TMDB alanlarıyla önek alır."""
    row = dataset_rows.get(film.wikidata_id)
    if row:
        return dataset_prefix(row)
    return film_prefix(film.title, film.year, ", ".join(film.genres), ", ".join(film.countries))


def embed_missing_chunks(
    root: Path, embedder: Embedder, films: list[Film], summary: EmbedSummary
) -> None:
    renewed_ids = {
        f.wikidata_id for f in films if f.plot_source == Film.PlotSource.WIKIPEDIA_RENEWED
    }
    dataset_rows = sources.read_dataset_rows_by_id(root, renewed_ids)
    incoming = sum(len([t for t in chunk_text(film.plot) if t]) for film in films)
    with bulk_write_window(FilmChunk, incoming):
        for start in range(0, len(films), CHUNK_FILMS_PER_WRITE):
            group = films[start : start + CHUNK_FILMS_PER_WRITE]
            pieces: list[tuple[Film, int, str]] = []
            vector_texts: list[str] = []
            for film in group:
                prefix = _chunk_prefix(film, dataset_rows)
                for position, text in enumerate(t for t in chunk_text(film.plot) if t):
                    pieces.append((film, position, text))
                    # Önek yalnız vektör içindir; parça metni öneksiz saklanır.
                    vector_texts.append(prefix + text)
            vectors = embedder(vector_texts, CHUNK_MAX_SEQ_LENGTH)
            rows = [
                FilmChunk(film=film, position=position, text=text, embedding=vector)
                for (film, position, text), vector in zip(pieces, vectors, strict=True)
            ]
            with transaction.atomic():
                FilmChunk.objects.filter(film__in=group).delete()
                FilmChunk.objects.bulk_create(rows, batch_size=500)
            summary.chunk_films += len(group)
            summary.chunks += len(rows)
            reset_queries()  # DEBUG açıkken sorgu günlüğü vektör metinleriyle belleği doldurur
            logger.info(
                "Üretilen parça vektörleri: %s (%s film)", summary.chunks, summary.chunk_films
            )


def embed_missing_cards(embedder: Embedder, films: list[Film], summary: EmbedSummary) -> None:
    usable = []
    for film in films:
        if not (film.overview or film.tr_overview or film.tagline or film.keywords):
            summary.skipped["kart_tmdb_metni_yok"] += 1
            continue
        usable.append(film)
    with bulk_write_window(Film, len(usable)):
        for start in range(0, len(usable), CARD_FILMS_PER_WRITE):
            group = usable[start : start + CARD_FILMS_PER_WRITE]
            vectors = embedder([film_card_text(film) for film in group], CARD_MAX_SEQ_LENGTH)
            now = timezone.now()
            for film, vector in zip(group, vectors, strict=True):
                film.card_embedding = vector
                film.updated_at = now
            Film.objects.bulk_update(group, ["card_embedding", "updated_at"], batch_size=500)
            summary.cards += len(group)
            reset_queries()  # DEBUG açıkken sorgu günlüğü vektör metinleriyle belleği doldurur
            logger.info("Üretilen kart vektörleri: %s", summary.cards)


def embed_missing(
    root: Path = sources.DEFAULT_DATA_ROOT,
    embedder: Embedder | None = None,
    proof_sample_size: int = PROOF_SAMPLE_SIZE,
) -> EmbedSummary:
    """Hikâyesi olup parçası olmayan filmleri ve kart vektörü olmayan filmleri vektöre çevirir."""
    with films_write_lock():
        return _run_embed_missing(root, embedder, proof_sample_size)


def _run_embed_missing(
    root: Path, embedder: Embedder | None, proof_sample_size: int
) -> EmbedSummary:
    summary = EmbedSummary()
    ensure_vector_indexes()
    films_without_chunks = list(Film.objects.filter(chunks__isnull=True).exclude(plot=""))
    films_without_card = list(Film.objects.filter(card_embedding__isnull=True))
    if not films_without_chunks and not films_without_card:
        logger.info("Eksik vektör yok.")
        return summary

    embedder = embedder or make_embedder()
    started = time.monotonic()
    # Üretimden önce tarif kanıtı: hazır vektörler yeniden üretilemiyorsa yeni vektör üretilmez.
    if films_without_chunks:
        summary.proofs.append(verify_chunk_recipe(root, embedder, proof_sample_size))
    if films_without_card:
        summary.proofs.append(verify_card_recipe(root, embedder, proof_sample_size))
    summary.seconds["tarif_kaniti"] = round(time.monotonic() - started, 1)

    started = time.monotonic()
    embed_missing_chunks(root, embedder, films_without_chunks, summary)
    summary.seconds["parca_uretimi"] = round(time.monotonic() - started, 1)

    started = time.monotonic()
    embed_missing_cards(embedder, films_without_card, summary)
    summary.seconds["kart_uretimi"] = round(time.monotonic() - started, 1)
    logger.info(summary.describe())
    return summary
