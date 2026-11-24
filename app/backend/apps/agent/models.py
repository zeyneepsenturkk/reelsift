from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class LLMSettings(TimeStampedModel):
    """Arayüzden kaydedilen dil modeli ayarı; tek satır (pk=1).

    API anahtarları düz metin değil, Fernet ile şifrelenmiş olarak durur (`llm_config`);
    alanlara doğrudan yazılmaz."""

    PROVIDER_CHOICES = [
        ("anthropic", "Claude (Anthropic)"),
        ("gemini", "Gemini"),
        ("ollama", "Yerel model (Ollama)"),
    ]

    provider = models.CharField(max_length=16, choices=PROVIDER_CHOICES)
    anthropic_api_key = models.TextField(blank=True, default="")
    gemini_api_key = models.TextField(blank=True, default="")
    ollama_base_url = models.CharField(max_length=200, blank=True, default="")
    ollama_model = models.CharField(max_length=100, blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="llm_settings_updates",
    )

    class Meta:
        verbose_name = "dil modeli ayarı"
        verbose_name_plural = "dil modeli ayarı"
        constraints = [
            models.CheckConstraint(condition=models.Q(pk=1), name="agent_llmsettings_single_row")
        ]

    def __str__(self) -> str:
        # Anahtar alanları yazılmaz: nesne metni loglara ve hata mesajlarına girebilir.
        return f"Dil modeli ayarı ({self.provider})"
