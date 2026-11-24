import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel

DEFAULT_TITLE = "Yeni sohbet"


class Chat(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chats"
    )
    title = models.CharField(max_length=200, default=DEFAULT_TITLE)
    # LangGraph checkpoint kaydının anahtarı; sohbet kimliğinden bağımsız ve tahmin edilemez.
    thread_id = models.UUIDField(default=uuid.uuid4, editable=False)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["thread_id"], name="chats_chat_unique_thread_id"),
        ]
        indexes = [
            models.Index(fields=["user", "-updated_at"], name="chats_chat_user_updated_idx"),
        ]

    def __str__(self):
        return f"{self.title} ({self.user_id})"


class Message(TimeStampedModel):
    class Role(models.TextChoices):
        USER = "user", "Kullanıcı"
        ASSISTANT = "assistant", "Asistan"

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    text = models.TextField(blank=True)
    # Adım kayıtları (sözleşmedeki Step listesi; notice'ler de burada saklanır).
    steps = models.JSONField(default=list, blank=True)
    duration_s = models.FloatField(null=True, blank=True)
    collection = models.ForeignKey(
        "curation.Collection",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    suggestions = models.JSONField(default=list, blank=True)
    error = models.JSONField(null=True, blank=True)

    class Meta:
        # Asistan mesajının kimliği akış başında ayrılır; kimlik sırası konuşma sırasıdır.
        ordering = ["id"]
        indexes = [
            models.Index(fields=["chat", "id"], name="chats_message_chat_id_idx"),
        ]

    def __str__(self):
        return f"{self.role}:{self.chat_id}#{self.pk}"
