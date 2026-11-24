from django.db import models


class TimeStampedModel(models.Model):
    """Bütün modellerin türediği soyut taban: oluşturma ve güncelleme zamanı."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
