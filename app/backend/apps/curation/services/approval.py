import secrets

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ServiceError
from apps.curation.models import Collection, CollectionFilm

SHARE_TOKEN_BYTES = 16


def approve_collection(collection: Collection, by_user) -> Collection:
    """Koleksiyonu onaylar ve paylaşım anahtarı üretir.

    `status=approved` yapan TEK yerdir. Yalnız `POST /api/collections/{id}/approve` ucu
    çağırır; `apps.agent` bu modülü içe aktarmaz (testle denetlenir).
    """
    with transaction.atomic():
        locked = Collection.objects.select_for_update().get(pk=collection.pk)
        if locked.owner_id != by_user.pk:
            raise ServiceError("Bulunamadı.", "not_found", 404)
        if locked.status == Collection.Status.APPROVED:
            raise ServiceError("Koleksiyon zaten onaylı.", "already_approved", 409)
        if not CollectionFilm.objects.filter(collection=locked).exists():
            raise ServiceError("Filmi olmayan koleksiyon onaylanamaz.", "empty_collection", 422)

        locked.status = Collection.Status.APPROVED
        locked.share_token = secrets.token_urlsafe(SHARE_TOKEN_BYTES)
        locked.approved_at = timezone.now()
        locked.version += 1
        locked.save(update_fields=["status", "share_token", "approved_at", "version", "updated_at"])
    return locked
