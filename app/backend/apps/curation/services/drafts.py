"""Taslak yazımı. `CollectionFilm` satırı yalnız burada, doğrulanmış alıntıyla oluşur."""

from dataclasses import dataclass

from django.db import transaction
from django.db.models import F

from apps.core.exceptions import ServiceError
from apps.curation.models import Collection, CollectionFilm
from apps.curation.services.collections import lock_draft
from apps.curation.services.quotes import check_quote
from apps.films.models import Film


@dataclass(frozen=True)
class KeptFilm:
    """Taslakta zaten olan ve olduğu gibi (gerekçesi/alıntısı değişmeden) kalan film."""

    film_id: int


@dataclass(frozen=True)
class NewFilm:
    """Yeni yazılan film; alıntı kayıt anında kaynak metinle yeniden doğrulanır."""

    film_id: int
    rationale: str
    source_quote: str
    source_kind: str


def save_draft(
    *,
    owner,
    chat,
    request: dict,
    title: str,
    description: str,
    entries: list[KeptFilm | NewFilm],
    base: Collection | None = None,
) -> int:
    """Taslağı tek işlemde yazar; `base` varsa onu günceller (sürüm artar), yoksa yenisini açar.

    `entries` nihai sıradır. Dönen değer koleksiyon kimliğidir.
    """
    film_ids = [entry.film_id for entry in entries]
    if not film_ids:
        raise ServiceError("Filmi olmayan taslak yazılamaz.", "empty_collection", 422)
    if len(set(film_ids)) != len(film_ids):
        raise ServiceError("Aynı film taslakta bir kereden fazla olamaz.", "validation_error", 422)

    new_ids = [entry.film_id for entry in entries if isinstance(entry, NewFilm)]
    # reviews: inceleme alıntısı doğrulaması için; film başına ayrı sorgu olmasın.
    films = {
        film.pk: film
        for film in Film.objects.filter(pk__in=new_ids)
        .defer("card_embedding")
        .prefetch_related("reviews")
    }

    with transaction.atomic():
        if base is None:
            collection = Collection.objects.create(
                owner=owner,
                chat=chat,
                title=title,
                description=description,
                request=request,
            )
            existing: dict[int, CollectionFilm] = {}
        else:
            collection = lock_draft(base.pk)
            collection.title = title
            collection.description = description
            collection.request = request
            collection.version = F("version") + 1
            collection.save(
                update_fields=["title", "description", "request", "version", "updated_at"]
            )
            existing = {
                row.film_id: row for row in CollectionFilm.objects.filter(collection=collection)
            }

        to_create, to_update = [], []
        for position, entry in enumerate(entries, start=1):
            row = existing.pop(entry.film_id, None)
            if isinstance(entry, KeptFilm):
                if row is None:
                    raise ServiceError("Korunacak film taslakta yok.", "validation_error", 422)
                row.position = position
                to_update.append(row)
                continue

            film = films.get(entry.film_id)
            if film is None:
                raise ServiceError("Film arşivde bulunamadı.", "validation_error", 422)
            if not entry.rationale.strip():
                raise ServiceError("Gerekçe boş olamaz.", "validation_error", 422)
            source_url = check_quote(film, entry.source_kind, entry.source_quote)
            fields = {
                "position": position,
                "rationale": entry.rationale.strip(),
                "source_quote": entry.source_quote.strip(),
                "source_kind": entry.source_kind,
                "source_url": source_url,
            }
            if row is None:
                to_create.append(CollectionFilm(collection=collection, film=film, **fields))
                continue
            for name, value in fields.items():
                setattr(row, name, value)
            to_update.append(row)

        if existing:
            CollectionFilm.objects.filter(pk__in=[row.pk for row in existing.values()]).delete()
        CollectionFilm.objects.bulk_update(
            to_update,
            ["position", "rationale", "source_quote", "source_kind", "source_url"],
            batch_size=100,
        )
        CollectionFilm.objects.bulk_create(to_create, batch_size=100)
    return collection.pk
