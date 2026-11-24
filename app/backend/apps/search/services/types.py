from dataclasses import dataclass


@dataclass(frozen=True)
class TitleHint:
    title: str
    year: int | None


@dataclass(frozen=True)
class QueryFilters:
    year_min: int | None = None
    year_max: int | None = None
    countries: tuple[str, ...] = ()  # İngilizce ülke adları (modelin yazdığı gibi)
    max_vote_count: int | None = None


@dataclass(frozen=True)
class PersonHint:
    name: str
    role: str = "any"  # "director", "actor" ya da "any" (rol belli değil)


@dataclass(frozen=True)
class ParsedQuery:
    en_query: str
    hyde: str
    titles: tuple[TitleHint, ...] = ()
    filters: QueryFilters = QueryFilters()
    genres: tuple[str, ...] = ()  # tercih; sert filtre değil
    # Kişi verildiyse aday evreni o kişilerin arşivdeki filmleridir (sert kısıt).
    people: tuple[PersonHint, ...] = ()
    # "rating" ya da "popularity". Kişi evreninde sırayı belirler; her istekte aday başına değer
    # taşınır (kişisiz isteklerde sıra değişmez).
    rank_by: str | None = None


@dataclass(frozen=True)
class Candidate:
    film_id: int  # Film.pk
    rerank_score: float | None
    rrf_rank: int
    sources: tuple[str, ...]  # "dense", "hyde", "card", "bma", "bmb", "g", "person"
    rank_value: float | None = None  # `rank_by` verildiyse ağırlıklı puan ya da oy sayısı


@dataclass(frozen=True)
class SearchResult:
    candidates: tuple[Candidate, ...]  # son sırayla
    relaxed_filters: tuple[str, ...]  # kaldırılan filtre adları; yoksa ()
    pool_size: int  # birleştirme sonrası aday sayısı
    timings: dict[str, float]  # adım -> saniye
    # İstenen kişi başına arşivdeki film sayısı (filtreden önce); bulunamayan kişi için 0.
    people_found: tuple[tuple[str, int], ...] = ()
