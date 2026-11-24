"""Dil modeli çıktı şemaları (yapılı çıktı) ve çözümlenmiş istek.

Yapılı çıktı şemalarında varsayılan değer yoktur: her alanı modelin doldurması istenir.
"""

from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["new_search", "refine", "replace_film", "question", "other"]
SourceKind = Literal["plot", "overview", "review"]
PersonRole = Literal["director", "actor", "any"]
RankBy = Literal["rating", "popularity"]

MIN_TARGET = 1
MAX_TARGET = 20
DEFAULT_TARGET = 10
MAX_PEOPLE = 5


class TitleHintLM(BaseModel):
    title: str
    year: int | None


class FiltersLM(BaseModel):
    year_min: int | None
    year_max: int | None
    countries: list[str]
    max_vote_count: int | None


class PersonLM(BaseModel):
    name: str
    role: PersonRole


class RequestLM(BaseModel):
    en_query: str
    hyde: str
    titles: list[TitleHintLM]
    filters: FiltersLM
    genres: list[str]
    target_count: int | None
    # "N tane daha ekle / N film çıkar": editörün söylediği göreli değişim (+N / -N); yoksa null.
    target_delta: int | None
    rank_by: RankBy | None
    # Kişi dışında bir tema, ton, mekân ya da dönem ölçütü var mı? ("X'in filmleri" -> false)
    theme_present: bool


class UnderstandOutput(BaseModel):
    intent: Intent
    # Editörün adını andığı kişiler; soru ve diğer niyetlerde de okunur (istek yokken).
    people: list[PersonLM]
    request: RequestLM | None
    instruction: str
    film_id: int | None
    # Editör taslaktaki filmlerin kalmasını ve yalnız üstüne film eklenmesini mi istiyor?
    keep_draft: bool


class Verdict(BaseModel):
    film_id: int
    verdict: Literal["fit", "partial", "no"]
    reason: str


class JudgeOutput(BaseModel):
    verdicts: list[Verdict]


class SelectOutput(BaseModel):
    selected_ids: list[int]
    title: str
    description: str
    suggestions: list[str]


class FilmWriting(BaseModel):
    film_id: int
    rationale: str
    source_kind: SourceKind
    source_quote: str


class WriteOutput(BaseModel):
    films: list[FilmWriting]


class AltQueryOutput(BaseModel):
    en_query: str
    hyde: str


class TitleHint(BaseModel):
    title: str
    year: int | None = None


class PersonHint(BaseModel):
    name: str
    role: PersonRole = "any"


class RequestFilters(BaseModel):
    year_min: int | None = None
    year_max: int | None = None
    countries: list[str] = Field(default_factory=list)
    max_vote_count: int | None = None


class ParsedRequest(BaseModel):
    """Çözümlenmiş istek: arama servisinin girdisi + tür tercihi + istenen film sayısı.

    Koleksiyonda (`Collection.request`) ve graf durumunda JSON olarak saklanır.
    """

    en_query: str
    hyde: str
    titles: list[TitleHint] = Field(default_factory=list)
    filters: RequestFilters = Field(default_factory=RequestFilters)
    genres: list[str] = Field(default_factory=list)
    target_count: int = DEFAULT_TARGET
    # Editör sayıyı açıkça söyledi mi? Yalnız editöre söylenen metinler için; seçimde kullanılmaz.
    # Alanı olmayan eski kayıtlar "söylendi" sayılır (eski davranış).
    target_stated: bool = True
    people: list[PersonHint] = Field(default_factory=list)
    rank_by: RankBy | None = None
    # Alanı olmayan eski kayıtlarda tema var sayılır (eski davranış: eleme çalışır).
    theme_present: bool = True

    @property
    def people_only(self) -> bool:
        """Yalnız kişi isteği ("X'in filmleri", "X'in en iyi 3 filmi"): kişi dışında tema yok.
        Bu durumda kişinin filmleri elemeden geçirilmez; hepsi uygun sayılır."""
        return bool(self.people) and not self.theme_present and not self.genres


def clean_people(raw: list[PersonLM]) -> list[PersonHint]:
    """Boş adlar atılır, aynı ad (büyük-küçük harf farkıyla) bir kez tutulur, en çok 5 kişi."""
    people: list[PersonHint] = []
    seen: set[str] = set()
    for person in raw:
        name = " ".join(person.name.split())
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        people.append(PersonHint(name=name, role=person.role))
    return people[:MAX_PEOPLE]


def _target_stated(raw_count: int | None, fallback_stated: bool, previous) -> bool:
    """Editör sayıyı bu mesajda söyledi mi? Model "kopyalama" kuralına uymayıp önceki isteğin
    sayısını aynen yazarsa bu yeni söylenmiş sayılmaz; bayrak önceki istekten devralınır.
    Bilinen sınır: editör gerçekten önceki sayıyla aynı sayıyı söylerse de "söylenmedi" kalır."""
    if raw_count is None:
        return fallback_stated
    if previous is not None and raw_count == previous.target_count:
        return previous.target_stated
    return True


def sanitize_request(
    raw: RequestLM,
    *,
    fallback_target: int = DEFAULT_TARGET,
    fallback_stated: bool = False,
    previous: ParsedRequest | None = None,
    people: list[PersonLM] | None = None,
) -> ParsedRequest:
    """Modelin yazdığı isteği güvenli sınırlara çeker (yıl aralığı, film sayısı, boş değerler)."""

    def clean_year(value: int | None) -> int | None:
        return value if value is not None and 1870 <= value <= 2100 else None

    year_min, year_max = clean_year(raw.filters.year_min), clean_year(raw.filters.year_max)
    if year_min is not None and year_max is not None and year_min > year_max:
        year_min, year_max = year_max, year_min
    max_votes = raw.filters.max_vote_count
    if max_votes is not None and max_votes < 0:
        max_votes = None
    # "Az bilinen" (oy sınırı) ile "en bilinen" sırası çelişir: sınır kalır, sıra düşer.
    rank_by = None if raw.rank_by == "popularity" and max_votes is not None else raw.rank_by
    target = raw.target_count if raw.target_count is not None else fallback_target
    return ParsedRequest(
        en_query=raw.en_query.strip(),
        hyde=raw.hyde.strip(),
        titles=[
            TitleHint(title=hint.title.strip(), year=clean_year(hint.year))
            for hint in raw.titles[:5]
            if hint.title.strip()
        ],
        filters=RequestFilters(
            year_min=year_min,
            year_max=year_max,
            countries=[name.strip() for name in raw.filters.countries if name.strip()],
            max_vote_count=max_votes,
        ),
        genres=[genre.strip() for genre in raw.genres if genre.strip()],
        target_count=min(max(target, MIN_TARGET), MAX_TARGET),
        target_stated=_target_stated(raw.target_count, fallback_stated, previous),
        people=clean_people(people or []),
        rank_by=rank_by,
        theme_present=raw.theme_present,
    )
