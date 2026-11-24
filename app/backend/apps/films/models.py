from django.contrib.postgres.fields import ArrayField
from django.db import models
from pgvector.django import HalfVectorField, HnswIndex

from apps.core.models import TimeStampedModel

# bge-m3 çıktı boyutu; kaynak vektörler float16 olduğu için halfvec kullanılır.
EMBEDDING_DIMENSIONS = 1024


class Mood(models.TextChoices):
    """Profil isteminin izinli ton listesi (`profil/prompt.txt`); dışındaki değerler yüklenmez."""

    BLEAK = "bleak"
    MELANCHOLIC = "melancholic"
    TENSE = "tense"
    EERIE = "eerie"
    WARM = "warm"
    HOPEFUL = "hopeful"
    PLAYFUL = "playful"
    ABSURD = "absurd"
    ROMANTIC = "romantic"
    NOSTALGIC = "nostalgic"
    GRITTY = "gritty"
    DREAMLIKE = "dreamlike"
    CLAUSTROPHOBIC = "claustrophobic"
    CONTEMPLATIVE = "contemplative"
    TRAGIC = "tragic"
    UPLIFTING = "uplifting"
    DARKLY_COMIC = "darkly comic"
    SUSPENSEFUL = "suspenseful"
    INTIMATE = "intimate"
    EPIC = "epic"
    CYNICAL = "cynical"
    TENDER = "tender"
    DISTURBING = "disturbing"
    WHIMSICAL = "whimsical"
    SOMBER = "somber"


class Film(TimeStampedModel):
    class PlotSource(models.TextChoices):
        DATASET = "dataset", "Veri seti"
        WIKIPEDIA_RENEWED = "wikipedia_renewed", "Wikipedia (yenilenen hikâye)"
        WIKIPEDIA_ADDED = "wikipedia_added", "Wikipedia (ek film)"

    # Wikidata kaydı olmayan ek filmlerde "tmdb-<tmdb_id>" (profil dosyasındaki kimlikle aynı).
    wikidata_id = models.CharField(max_length=32)
    tmdb_id = models.IntegerField(null=True, blank=True)
    imdb_id = models.CharField(max_length=16, blank=True)
    title = models.CharField(max_length=500)
    original_title = models.CharField(max_length=500, blank=True)
    tr_title = models.CharField(max_length=500, blank=True)
    original_language = models.CharField(max_length=16, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    release_date = models.DateField(null=True, blank=True)
    runtime = models.PositiveSmallIntegerField(null=True, blank=True)
    countries = ArrayField(models.TextField(), default=list, blank=True)
    genres = ArrayField(models.TextField(), default=list, blank=True)
    keywords = ArrayField(models.TextField(), default=list, blank=True)
    directors = ArrayField(models.TextField(), default=list, blank=True)
    actors = ArrayField(models.TextField(), default=list, blank=True)
    overview = models.TextField(blank=True)
    tr_overview = models.TextField(blank=True)
    tagline = models.TextField(blank=True)
    plot = models.TextField(blank=True)
    plot_source = models.CharField(max_length=24, choices=PlotSource.choices, blank=True)
    wikipedia_url = models.URLField(max_length=500, blank=True)
    vote_average = models.FloatField(null=True, blank=True)
    vote_count = models.PositiveIntegerField(default=0)
    popularity = models.FloatField(null=True, blank=True)
    poster_path = models.CharField(max_length=64, blank=True)
    backdrop_path = models.CharField(max_length=64, blank=True)
    card_embedding = HalfVectorField(dimensions=EMBEDDING_DIMENSIONS, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["wikidata_id"], name="films_film_unique_wikidata_id"),
        ]
        indexes = [
            models.Index(fields=["tmdb_id"], name="films_film_tmdb_id_idx"),
            models.Index(fields=["year"], name="films_film_year_idx"),
            models.Index(fields=["vote_count"], name="films_film_vote_count_idx"),
            HnswIndex(
                name="films_film_card_hnsw",
                fields=["card_embedding"],
                m=16,
                ef_construction=64,
                opclasses=["halfvec_cosine_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.year})" if self.year else self.title


class FilmChunk(TimeStampedModel):
    film = models.ForeignKey(Film, on_delete=models.CASCADE, related_name="chunks")
    position = models.PositiveSmallIntegerField()
    # Öneksiz hikâye parçası; vektör "Title: ... Genres: ... Country: ..." önekiyle üretilir.
    text = models.TextField()
    embedding = HalfVectorField(dimensions=EMBEDDING_DIMENSIONS)

    class Meta:
        ordering = ["film_id", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["film", "position"], name="films_filmchunk_unique_film_position"
            ),
        ]
        indexes = [
            HnswIndex(
                name="films_filmchunk_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["halfvec_cosine_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.film_id}#{self.position}"


class FilmProfile(TimeStampedModel):
    class Pacing(models.TextChoices):
        SLOW = "slow", "Yavaş"
        MEDIUM = "medium", "Orta"
        FAST = "fast", "Hızlı"
        UNKNOWN = "unknown", "Bilinmiyor"

    class Evidence(models.TextChoices):
        RICH = "rich", "Zengin"
        THIN = "thin", "Zayıf"
        INSUFFICIENT = "insufficient", "Yetersiz"

    film = models.OneToOneField(Film, on_delete=models.CASCADE, related_name="profile")
    themes = ArrayField(models.TextField(), default=list, blank=True)
    moods = ArrayField(
        models.CharField(max_length=32, choices=Mood.choices), default=list, blank=True
    )
    tone = models.TextField(blank=True)
    pacing = models.CharField(max_length=16, choices=Pacing.choices, blank=True)
    setting_place = models.TextField(blank=True)
    setting_period = models.TextField(blank=True)
    narrative = ArrayField(models.TextField(), default=list, blank=True)
    for_viewers = models.TextField(blank=True)
    tr_pitch = models.TextField(blank=True)
    evidence = models.CharField(max_length=16, choices=Evidence.choices, blank=True)

    def __str__(self):
        return f"Profil: {self.film_id}"


class FilmReview(TimeStampedModel):
    film = models.ForeignKey(Film, on_delete=models.CASCADE, related_name="reviews")
    content = models.TextField()
    rating = models.FloatField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    url = models.URLField(max_length=300)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["film", "url"], name="films_filmreview_unique_film_url"
            ),
        ]

    def __str__(self):
        return f"İnceleme: {self.film_id} ({self.rating})"
