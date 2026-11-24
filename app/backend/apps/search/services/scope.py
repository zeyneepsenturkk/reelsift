"""Arama kapsamı: sert filtreler (yıl, ülke, oy sayısı) + değerlendirme havuzu + hariç tutulanlar.

Koşullar tek yerde SQL parçası olarak kurulur; hem kapsamdaki film kimliklerini bulan sorgu hem de
vektör sorguları aynı parçayı kullanır (iki ayrı uygulama birbirinden sapmasın).
Filtre 30 filmden az film bırakırsa tamamı kaldırılır ve kaldırılan filtrelerin adları döner.
Kişi evreninde (`resolve_people_scope`) bu eşik yoktur: filtre yalnız evreni boşaltıyorsa kalkar.
"""

import logging
from collections.abc import Collection
from dataclasses import dataclass, field, replace

import numpy as np
from django.conf import settings
from django.db import connection

from apps.films.models import Film
from apps.search.services.types import QueryFilters

logger = logging.getLogger(__name__)

FILM_TABLE = Film._meta.db_table
FILM_ALIAS = "f"


@dataclass(frozen=True)
class Scope:
    where: str  # "" ise kısıt yok; doluysa FILM_ALIAS takma adlı films_film üzerinde koşul
    params: tuple
    # Filtre ya da havuzla sınırlı kapsamdaki Film.pk değerleri (hariç tutulanlar düşülmüş);
    # None = kapsam tüm arşiv (yalnız `excluded` düşülür).
    film_ids: np.ndarray | None
    relaxed: tuple[str, ...] = field(default=())
    # Yalnız hariç tutma varken ~93 bin kimlik çekilmesin diye küçük liste ayrı tutulur.
    excluded: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))

    @property
    def restricted(self) -> bool:
        return bool(self.where)

    def mask_for(self, index_film_ids: np.ndarray) -> np.ndarray | None:
        """`index_film_ids` sırasında kapsamdaki filmleri işaretleyen dizi; kısıt yoksa None."""
        if self.film_ids is not None:
            return np.isin(index_film_ids, self.film_ids)
        if len(self.excluded):
            return ~np.isin(index_film_ids, self.excluded)
        return None

    def allows(self, film_id: int) -> bool:
        if self.film_ids is not None:
            index = np.searchsorted(self.film_ids, film_id)
            return bool(index < len(self.film_ids) and self.film_ids[index] == film_id)
        return film_id not in set(self.excluded.tolist())


def _like_pattern(text: str) -> str:
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def active_filter_names(filters: QueryFilters) -> tuple[str, ...]:
    names = []
    if filters.year_min is not None:
        names.append("year_min")
    if filters.year_max is not None:
        names.append("year_max")
    if filters.countries:
        names.append("countries")
    if filters.max_vote_count is not None:
        names.append("max_vote_count")
    return tuple(names)


def filter_conditions(filters: QueryFilters) -> tuple[list[str], list]:
    """Sert filtre koşulları. Ülke adı, film ülkeleri metninde (büyük/küçük harf yok) geçmeli."""
    conditions: list[str] = []
    params: list = []
    if filters.year_min is not None:
        conditions.append(f"{FILM_ALIAS}.year >= %s")
        params.append(filters.year_min)
    if filters.year_max is not None:
        conditions.append(f"{FILM_ALIAS}.year <= %s")
        params.append(filters.year_max)
    if filters.countries:
        likes = f"lower(array_to_string({FILM_ALIAS}.countries, '|')) LIKE %s"
        conditions.append("(" + " OR ".join([likes] * len(filters.countries)) + ")")
        params.extend(_like_pattern(country) for country in filters.countries)
    if filters.max_vote_count is not None:
        conditions.append(f"{FILM_ALIAS}.vote_count <= %s")
        params.append(filters.max_vote_count)
    return conditions, params


def _where(conditions: list[str]) -> str:
    return f" WHERE {' AND '.join(conditions)}" if conditions else ""


def _count_films(conditions: list[str], params: list) -> int:
    sql = f"SELECT count(*) FROM {FILM_TABLE} {FILM_ALIAS}{_where(conditions)}"
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


def _fetch_ids(conditions: list[str], params: list) -> np.ndarray:
    sql = f"SELECT {FILM_ALIAS}.id FROM {FILM_TABLE} {FILM_ALIAS}{_where(conditions)} ORDER BY 1"
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return np.fromiter((row[0] for row in cursor), dtype=np.int64)


def resolve_scope(
    filters: QueryFilters,
    *,
    exclude_film_ids: Collection[int] = (),
    pool_film_ids: Collection[int] | None = None,
    min_films: int | None = None,
) -> Scope:
    """`min_films`: filtre bundan az film bırakırsa kaldırılır (varsayılan ayardaki eşik)."""
    threshold = settings.SEARCH["min_filtered_films"] if min_films is None else min_films
    conditions, params = filter_conditions(filters)
    relaxed: tuple[str, ...] = ()
    if conditions:
        matching = _count_films(conditions, params)
        if matching < threshold:
            relaxed = active_filter_names(filters)
            conditions, params = [], []
            logger.info("Filtre %s film bıraktı; filtreler kaldırıldı: %s", matching, relaxed)
    has_filters = bool(conditions)
    pool = None
    if pool_film_ids is not None:
        pool = np.unique(np.array([int(film_id) for film_id in pool_film_ids], dtype=np.int64))
        conditions.append(f"{FILM_ALIAS}.id = ANY(%s)")
        params.append(pool.tolist())
    restricting_conditions, restricting_params = list(conditions), list(params)
    excluded = np.unique(np.array([int(film_id) for film_id in exclude_film_ids], dtype=np.int64))
    if excluded.size:
        conditions.append(f"NOT ({FILM_ALIAS}.id = ANY(%s))")
        params.append(excluded.tolist())
    if not conditions:
        return Scope("", (), None, relaxed)
    # Kimlik listesi yalnız filtre ya da havuz varsa gerekir; yalnız hariç tutma varken tüm
    # arşivin kimlikleri her istekte çekilmesin diye `excluded` ayrı tutulur.
    film_ids = None
    if has_filters:
        film_ids = _fetch_ids(restricting_conditions, restricting_params)
    elif pool is not None:
        film_ids = pool
    if film_ids is not None:
        film_ids = np.setdiff1d(film_ids, excluded)
    return Scope(" AND ".join(conditions), tuple(params), film_ids, relaxed, excluded)


def resolve_people_scope(
    filters: QueryFilters,
    universe: np.ndarray,
    *,
    exclude_film_ids: Collection[int] = (),
    pool_film_ids: Collection[int] | None = None,
) -> Scope:
    """Kişi evreninin (kişilerin arşivdeki filmleri) kapsamı: filtreler ve hariç tutma uygulanır.

    30 film eşiği burada yoktur (evren zaten küçüktür). Filtre evreni TAMAMEN boşaltıyorsa
    filtreler kaldırılır ve adları döner; kişi kısıtı hiçbir durumda kaldırılmaz (evren boşsa
    kapsam boştur)."""
    if pool_film_ids is not None:
        pool = np.array([int(film_id) for film_id in pool_film_ids], dtype=np.int64)
        universe = np.intersect1d(universe, pool)
    if universe.size == 0:
        return Scope(f"{FILM_ALIAS}.id = ANY(%s)", ([],), np.empty(0, dtype=np.int64))
    relaxed: tuple[str, ...] = ()
    conditions, params = filter_conditions(filters)
    if conditions:
        conditions.append(f"{FILM_ALIAS}.id = ANY(%s)")
        params.append(universe.tolist())
        if _count_films(conditions, params) == 0:
            relaxed = active_filter_names(filters)
            filters = QueryFilters()
            logger.info("Filtre kişi evrenini boşalttı; filtreler kaldırıldı: %s", relaxed)
    film_scope = resolve_scope(
        filters, exclude_film_ids=exclude_film_ids, pool_film_ids=universe, min_films=0
    )
    return replace(film_scope, relaxed=relaxed)
