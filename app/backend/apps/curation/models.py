from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Collection(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Taslak"
        APPROVED = "approved", "Onaylı"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="collections"
    )
    # Sohbet silinirse koleksiyon kalır (onaylı koleksiyon paylaşılmış olabilir).
    chat = models.ForeignKey(
        "chats.Chat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="collections",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    # Taslak her değiştiğinde artar; arayüz eski kopyayı bununla ayırt eder.
    version = models.PositiveIntegerField(default=1)
    # Onaya kadar boş; NULL değerler tekillik kısıtını bozmaz.
    share_token = models.CharField(  # noqa: DJ001  # boş metin tekillik kısıtını bozardı, NULL bozmaz
        max_length=64, null=True, blank=True
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    # Herkese açık sitedeki sayfanın adresi; "Sitede yayınla" başarılı olunca yazılır, geri alınmaz.
    published_url = models.URLField(max_length=500, blank=True)
    # Çözümlenmiş istek (ParsedRequest); "yeniden araştır" ve düzeltme isteklerinin tabanı.
    request = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["share_token"], name="curation_collection_unique_share_token"
            ),
        ]
        indexes = [
            models.Index(fields=["chat", "-id"], name="curation_collection_chat_idx"),
            models.Index(
                fields=["owner", "status", "-updated_at"], name="curation_collection_owner_idx"
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.status})"


class CollectionFilm(TimeStampedModel):
    class SourceKind(models.TextChoices):
        PLOT = "plot", "Hikâye"
        OVERVIEW = "overview", "TMDB özeti"
        REVIEW = "review", "İnceleme"

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name="films")
    # Film verisi yüklemeyle gelir; koleksiyonda kullanılan film sessizce silinmesin.
    film = models.ForeignKey(
        "films.Film", on_delete=models.PROTECT, related_name="collection_entries"
    )
    position = models.PositiveSmallIntegerField()
    rationale = models.TextField()
    source_quote = models.TextField(blank=True)
    source_kind = models.CharField(max_length=16, choices=SourceKind.choices, blank=True)
    source_url = models.URLField(max_length=500, blank=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "film"], name="curation_collectionfilm_unique_film"
            ),
        ]

    def __str__(self):
        return f"{self.collection_id}:{self.position}:{self.film_id}"
