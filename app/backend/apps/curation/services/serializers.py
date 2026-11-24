from django.db.models import F, Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404

from apps.accounts.services.profiles import display_name
from apps.core.text import is_db_unsafe
from apps.curation.models import Collection, CollectionFilm
from apps.curation.schemas import (
    CollectionFilmOut,
    CollectionOut,
    CollectionStatsOut,
    CollectionSummaryOut,
    QuoteSourceOut,
    SharedCollectionOut,
    SourceOut,
)
from apps.curation.services.countries import country_name_tr, ordered_countries
from apps.curation.services.publish_config import publish_enabled
from apps.curation.services.sources import poster_url, tmdb_url


def collection_queryset():
    """Koleksiyon + filmleri tek sorguda (iki sorgu: koleksiyon, filmler+film kayıtları).

    Liste/kart görünümünde gerekmeyen büyük alanlar (hikâye, vektör) getirilmez.
    """
    films = CollectionFilm.objects.select_related("film").defer(
        "film__card_embedding", "film__plot", "film__tr_overview", "film__overview"
    )
    return Collection.objects.prefetch_related(Prefetch("films", queryset=films))


def get_owned_collection(collection_id: int, user) -> Collection:
    """Başkasının koleksiyonu da 404 verir (varlığı sızdırılmaz)."""
    return get_object_or_404(collection_queryset(), pk=collection_id, owner=user)


MAX_SHARE_TOKEN_LENGTH = 64
SUMMARY_POSTERS = 6


def get_shared_collection(token: str) -> Collection:
    """Yalnız onaylı ve anahtarı eşleşen koleksiyon; diğer her durum aynı 404'ü verir."""
    if not token or len(token) > MAX_SHARE_TOKEN_LENGTH or is_db_unsafe(token):
        raise Http404
    queryset = collection_queryset().select_related("owner")
    return get_object_or_404(queryset, share_token=token, status=Collection.Status.APPROVED)


def approved_collections(user) -> list[Collection]:
    """Kullanıcının onaylı koleksiyonları, yeniden eskiye; afiş ve film sayısı için tek ek sorgu.

    Kartta yalnız afiş yolu gerekir; filmin diğer sütunları getirilmez.
    """
    films = CollectionFilm.objects.select_related("film").only(
        "collection_id", "position", "film__poster_path"
    )
    return list(
        Collection.objects.filter(owner=user, status=Collection.Status.APPROVED)
        .order_by(F("approved_at").desc(nulls_last=True), "-id")
        .prefetch_related(Prefetch("films", queryset=films))
    )


QUOTE_SOURCE_LABELS = {
    "plot": "Wikipedia · hikâye",
    "overview": "TMDB · tanıtım",
    "review": "izleyici incelemesi",
}


def _quote_source(row: CollectionFilm) -> QuoteSourceOut | None:
    """Alıntının kaynağı; alıntı boşsa ya da tür kayıtlı değilse yok. Alanlar satırdadır."""
    label = QUOTE_SOURCE_LABELS.get(row.source_kind)
    if not row.source_quote or label is None:
        return None
    return QuoteSourceOut(kind=row.source_kind, label=label, url=row.source_url or None)


def _film_out(row: CollectionFilm) -> CollectionFilmOut:
    film = row.film
    sources = []
    # `plot` ertelenmiş (defer); hikâyenin varlığını `plot_source` söyler (boşsa hikâye yok).
    if film.wikipedia_url and film.plot_source:
        sources.append(
            SourceOut(kind="wikipedia", label="Wikipedia · hikâye", url=film.wikipedia_url)
        )
    if film.tmdb_id:
        sources.append(SourceOut(kind="tmdb", label="TMDB · tanıtım", url=tmdb_url(film)))
    return CollectionFilmOut(
        film_id=film.pk,
        position=row.position,
        title=film.title,
        title_tr=film.tr_title or None,
        year=film.year,
        countries=[
            country_name_tr(name)
            for name in ordered_countries(film.countries, film.original_language)
        ],
        directors=list(film.directors[:3]),
        actors=list(film.actors[:6]),
        vote_count=film.vote_count,
        poster_url=poster_url(film),
        rationale=row.rationale,
        source_quote=row.source_quote,
        quote_source=_quote_source(row),
        sources=sources,
    )


def compute_stats(rows: list[CollectionFilm]) -> CollectionStatsOut:
    """İstatistikler saklanmaz; filmlerden her seferinde hesaplanır."""
    years = [row.film.year for row in rows if row.film.year is not None]
    countries = {name for row in rows for name in row.film.countries}
    votes = [row.film.vote_count for row in rows if row.film.vote_count is not None]
    return CollectionStatsOut(
        film_count=len(rows),
        year_min=min(years) if years else None,
        year_max=max(years) if years else None,
        country_count=len(countries),
        avg_vote_count=round(sum(votes) / len(votes), 1) if votes else None,
    )


def _share_url(collection: Collection) -> str | None:
    approved = collection.status == Collection.Status.APPROVED
    return f"/k/{collection.share_token}" if approved and collection.share_token else None


def serialize_collection(collection: Collection) -> CollectionOut:
    """`collection` `collection_queryset()` ile getirilmiş olmalı (aksi halde N+1)."""
    rows = sorted(collection.films.all(), key=lambda row: (row.position, row.pk))
    return CollectionOut(
        id=collection.pk,
        chat_id=collection.chat_id,
        title=collection.title,
        description=collection.description,
        status=collection.status,
        version=collection.version,
        films=[_film_out(row) for row in rows],
        stats=compute_stats(rows),
        share_url=_share_url(collection),
        published_url=collection.published_url or None,
        publish_enabled=publish_enabled(),
        approved_at=collection.approved_at,
        updated_at=collection.updated_at,
    )


def serialize_summary(collection: Collection) -> CollectionSummaryOut:
    """`collection` `approved_collections()` ile getirilmiş olmalı (aksi halde N+1)."""
    rows = sorted(collection.films.all(), key=lambda row: (row.position, row.pk))
    posters = [url for row in rows if (url := poster_url(row.film))]
    return CollectionSummaryOut(
        id=collection.pk,
        title=collection.title,
        status=collection.status,
        film_count=len(rows),
        poster_urls=posters[:SUMMARY_POSTERS],
        share_url=_share_url(collection),
        approved_at=collection.approved_at,
        updated_at=collection.updated_at,
    )


def serialize_shared(collection: Collection) -> SharedCollectionOut:
    """Tam cevaptan yalnız herkese açık alanlar alınır; `owner` önceden getirilmiş olmalı."""
    full = serialize_collection(collection)
    return SharedCollectionOut(
        title=full.title,
        description=full.description,
        films=full.films,
        stats=full.stats,
        owner_display_name=display_name(collection.owner),
        approved_at=full.approved_at or full.updated_at,
    )
