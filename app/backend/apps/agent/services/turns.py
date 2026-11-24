"""Yeni tur başlatma: eylemi taslağa karşı doğrular, kullanıcı mesajını kaydeder."""

from apps.chats.services import chats as chat_service
from apps.core.exceptions import ServiceError
from apps.curation.models import Collection, CollectionFilm


def start_turn(chat, text: str, action: dict | None):
    """Eylem geçersizse hata verir; geçerliyse (kullanıcı mesajı, ayrılan asistan kimliği) döner."""
    if action and action["type"] == "replace_film":
        latest = Collection.objects.filter(chat=chat).order_by("-id").first()
        in_draft = (
            latest is not None
            and CollectionFilm.objects.filter(collection=latest, film_id=action["film_id"]).exists()
        )
        if not in_draft:
            raise ServiceError("Bu film taslakta yok.", "validation_error", 422)
        if latest.status == Collection.Status.APPROVED:
            raise ServiceError("Onaylı koleksiyon değiştirilemez.", "collection_locked", 409)
    user_message = chat_service.save_user_message(chat, text)
    return user_message, chat_service.reserve_message_id()
