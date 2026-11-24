from django.db import transaction
from django.db.models import F

from apps.core.exceptions import ServiceError
from apps.curation.models import Collection, CollectionFilm
from apps.curation.services.serializers import collection_queryset


def locked_error() -> ServiceError:
    return ServiceError("Onaylı koleksiyon değiştirilemez.", "collection_locked", 409)


def lock_draft(collection_id: int) -> Collection:
    """Satırı kilitler; onaylıysa hata verir. Çağıran `transaction.atomic` içinde olmalı."""
    collection = Collection.objects.select_for_update().get(pk=collection_id)
    if collection.status == Collection.Status.APPROVED:
        raise locked_error()
    return collection


def _fresh(collection_id: int) -> Collection:
    return collection_queryset().get(pk=collection_id)


def update_collection(
    collection_id: int, *, title: str | None, description: str | None
) -> Collection:
    new_title = title.strip() if title is not None else None
    new_description = description.strip() if description is not None else None
    if new_title is None and new_description is None:
        raise ServiceError("Değiştirilecek bir alan gönderilmedi.", "validation_error", 422)
    if new_title is not None and not new_title:
        raise ServiceError("Başlık boş olamaz.", "validation_error", 422)

    with transaction.atomic():
        locked = lock_draft(collection_id)
        if new_title is not None:
            locked.title = new_title
        if new_description is not None:
            locked.description = new_description
        locked.version = F("version") + 1
        locked.save(update_fields=["title", "description", "version", "updated_at"])
    return _fresh(collection_id)


def remove_film(collection_id: int, film_id: int) -> Collection:
    with transaction.atomic():
        locked = lock_draft(collection_id)
        deleted, _ = CollectionFilm.objects.filter(collection=locked, film_id=film_id).delete()
        if not deleted:
            raise ServiceError("Film bu koleksiyonda yok.", "not_found", 404)
        remaining = list(
            CollectionFilm.objects.filter(collection=locked).order_by("position", "id")
        )
        for position, row in enumerate(remaining, start=1):
            row.position = position
        CollectionFilm.objects.bulk_update(remaining, ["position"], batch_size=100)
        locked.version = F("version") + 1
        locked.save(update_fields=["version", "updated_at"])
    return _fresh(collection_id)
