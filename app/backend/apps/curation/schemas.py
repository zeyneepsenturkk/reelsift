from datetime import datetime
from typing import Literal

from ninja import Field, Schema

from apps.core.text import SafeText


class SourceOut(Schema):
    kind: Literal["wikipedia", "tmdb"]
    label: str
    url: str


class QuoteSourceOut(Schema):
    kind: Literal["plot", "overview", "review"]
    label: str
    url: str | None


class CollectionFilmOut(Schema):
    film_id: int
    position: int
    title: str
    title_tr: str | None
    year: int | None
    countries: list[str]
    directors: list[str]
    actors: list[str]
    vote_count: int | None
    poster_url: str | None
    rationale: str
    source_quote: str
    quote_source: QuoteSourceOut | None
    sources: list[SourceOut]


class CollectionStatsOut(Schema):
    film_count: int
    year_min: int | None
    year_max: int | None
    country_count: int
    avg_vote_count: float | None


class CollectionOut(Schema):
    id: int
    chat_id: int | None
    title: str
    description: str
    status: Literal["draft", "approved"]
    version: int
    films: list[CollectionFilmOut]
    stats: CollectionStatsOut
    share_url: str | None
    # Sitedeki sayfanın adresi; yayınlanmadıysa yok.
    published_url: str | None
    # "Sitede yayınla" kullanılabilir mi (yalnız ayar; seçkinin durumundan bağımsız).
    publish_enabled: bool
    approved_at: datetime | None
    updated_at: datetime


class CollectionSummaryOut(Schema):
    id: int
    title: str
    status: Literal["draft", "approved"]
    film_count: int
    poster_urls: list[str]
    share_url: str | None
    approved_at: datetime | None
    updated_at: datetime


class SharedCollectionOut(Schema):
    """Girişsiz paylaşım cevabı; kimlik alanları (id, chat_id, sahip kullanıcı adı) bilerek yok."""

    title: str
    description: str
    films: list[CollectionFilmOut]
    stats: CollectionStatsOut
    owner_display_name: str
    approved_at: datetime


class CollectionPatchIn(Schema):
    title: SafeText | None = Field(None, max_length=200)
    description: SafeText | None = Field(None, max_length=2000)
