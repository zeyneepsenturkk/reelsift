from django.db import connection, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.chats.models import DEFAULT_TITLE, Chat, Message
from apps.chats.schemas import ChatOut, ChatSummaryOut, MessageOut
from apps.curation.models import Collection
from apps.curation.services.serializers import collection_queryset, serialize_collection

TITLE_MAX_LENGTH = 40
HISTORY_LIMIT = 6


def create_chat(user) -> Chat:
    return Chat.objects.create(user=user)


def get_owned_chat(chat_id: int, user) -> Chat:
    """Başkasının sohbeti de 404 verir (varlığı sızdırılmaz)."""
    return get_object_or_404(Chat, pk=chat_id, user=user)


def list_chats(user) -> list[Chat]:
    return list(Chat.objects.filter(user=user))


def summarize(chat: Chat) -> ChatSummaryOut:
    return ChatSummaryOut(id=chat.pk, title=chat.title, updated_at=chat.updated_at)


def message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.pk,
        role=message.role,
        text=message.text,
        created_at=message.created_at,
        steps=message.steps or [],
        duration_s=message.duration_s,
        collection_id=message.collection_id,
        suggestions=message.suggestions or [],
        error=message.error,
    )


def current_collection(chat: Chat) -> Collection | None:
    """Sohbetin güncel koleksiyonu: ona bağlı en yeni koleksiyon (onaylı olsa da)."""
    return collection_queryset().filter(chat=chat).order_by("-id").first()


def chat_detail(chat: Chat) -> ChatOut:
    messages = Message.objects.filter(chat=chat).order_by("id")
    collection = current_collection(chat)
    return ChatOut(
        id=chat.pk,
        title=chat.title,
        updated_at=chat.updated_at,
        messages=[message_out(message) for message in messages],
        collection=serialize_collection(collection) if collection else None,
    )


def save_user_message(chat: Chat, text: str) -> Message:
    with transaction.atomic():  # tek işlem: yavaş disklerde her kayıt ayrı onay beklemesin
        message = Message.objects.create(chat=chat, role=Message.Role.USER, text=text)
        touch_chat(chat)
    return message


def reserve_message_id() -> int:
    """Asistan mesajının kimliğini akış başında ayırır; mesaj ancak cevap bitince yazılır.

    Böylece `message.start` olayı kimliği önceden verebilir ve yarım cevap kaydedilmez.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(pg_get_serial_sequence(%s, 'id'))", [Message._meta.db_table])
        return cursor.fetchone()[0]


def save_assistant_message(
    chat: Chat,
    *,
    message_id: int,
    text: str,
    steps: list[dict],
    duration_s: float | None,
    collection_id: int | None,
    suggestions: list[str],
    error: dict | None = None,
) -> Message:
    with transaction.atomic():
        message = Message.objects.create(
            id=message_id,
            chat=chat,
            role=Message.Role.ASSISTANT,
            text=text,
            steps=steps,
            duration_s=duration_s,
            collection_id=collection_id,
            suggestions=suggestions,
            error=error,
        )
        touch_chat(chat)
    return message


def touch_chat(chat: Chat) -> None:
    Chat.objects.filter(pk=chat.pk).update(updated_at=timezone.now())


def title_from_text(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= TITLE_MAX_LENGTH:
        return text
    return text[:TITLE_MAX_LENGTH].rstrip() + "…"


def update_title(chat: Chat, *, collection_title: str | None, user_text: str) -> Chat:
    """İlk mesajdan sonra başlık: koleksiyon başlığı, yoksa isteğin ilk 40 karakteri."""
    chat.refresh_from_db(fields=["title", "updated_at"])
    if chat.title == DEFAULT_TITLE:
        chat.title = (collection_title or "").strip()[:200] or title_from_text(user_text)
        Chat.objects.filter(pk=chat.pk).update(title=chat.title)
    return chat


def recent_history(chat: Chat, *, before_id: int, limit: int = HISTORY_LIMIT) -> list[Message]:
    """Hata mesajları bağlama girmez; `before_id` geçerli kullanıcı mesajıdır (dahil değil)."""
    rows = Message.objects.filter(chat=chat, error__isnull=True, pk__lt=before_id).order_by("-id")[
        :limit
    ]
    return list(reversed(rows))
