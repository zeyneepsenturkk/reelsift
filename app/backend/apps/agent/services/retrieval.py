"""Arama servisine (`apps.search`, faz 3) tek ince bağdaştırıcı.

`apps.search` çağrı anında içe aktarılır ve sonuç kendi küçük veri sınıflarımıza çevrilir;
agent kodunun geri kalanı arama paketine bağımlı değildir. Testlerde bu sınıfın sahtesi verilir.
"""

import asyncio
import logging
from collections.abc import Collection
from dataclasses import dataclass

from django.db import connections

from apps.agent.schemas import ParsedRequest
from apps.core.exceptions import ServiceError

logger = logging.getLogger(__name__)

MSG_SEARCH_FAILED = "Arşiv araması şu an çalışmıyor. Biraz sonra tekrar dene."


class SearchError(ServiceError):
    def __init__(self, message: str = MSG_SEARCH_FAILED):
        super().__init__(message, "search_error", 502)


@dataclass(frozen=True)
class RetrievedCandidate:
    film_id: int
    rerank_score: float | None
    rrf_rank: int
    sources: tuple[str, ...]
    rank_value: float | None = None  # `rank_by` verildiyse arama servisinin hesapladığı değer


@dataclass(frozen=True)
class RetrievalResult:
    candidates: tuple[RetrievedCandidate, ...]
    relaxed_filters: tuple[str, ...]
    pool_size: int
    timings: dict[str, float]
    # İstenen kişi başına arşivdeki film sayısı (bulunamayan için 0).
    people_found: tuple[tuple[str, int], ...] = ()


def _run_search(request: ParsedRequest, limit: int, exclude_film_ids: tuple[int, ...]):
    """İş parçacığında çalışır: bu iş parçacığının veritabanı bağlantısı iş bitince kapatılır."""
    from apps.search.services import (
        pipeline,
        types,
    )  # faz 3 paketi çağrı anında yüklenir (ağır modeller açılışı yavaşlatmasın)

    query = types.ParsedQuery(
        en_query=request.en_query,
        hyde=request.hyde,
        titles=tuple(types.TitleHint(hint.title, hint.year) for hint in request.titles),
        filters=types.QueryFilters(
            year_min=request.filters.year_min,
            year_max=request.filters.year_max,
            countries=tuple(request.filters.countries),
            max_vote_count=request.filters.max_vote_count,
        ),
        genres=tuple(request.genres),
        people=tuple(types.PersonHint(person.name, person.role) for person in request.people),
        rank_by=request.rank_by,
    )
    try:
        return pipeline.search(query, limit=limit, exclude_film_ids=exclude_film_ids)
    finally:
        connections.close_all()


def _run_people_films(people: list[tuple[str, str]]) -> list[tuple[str, int, list[int]]]:
    """(ad, rol) -> (ad, arşivdeki film sayısı, kimlikler). Kişi dizini bellekte; veritabanı yok."""
    from apps.search.services import lexical

    try:
        index = lexical.get_index()  # indeks yoksa kurulur: bu iş parçacığının bağlantısı kapatılır
        result = []
        for name, role in people:
            film_ids = index.people.films(name, role)
            result.append((name, int(film_ids.size), film_ids.tolist()))
        return result
    finally:
        connections.close_all()


class SearchServiceRetrieval:
    async def search(
        self, request: ParsedRequest, *, limit: int, exclude_film_ids: Collection[int] = ()
    ) -> RetrievalResult:
        try:
            # Arama ekran kartı/CPU işi yapar; olay döngüsü tıkanmasın diye ayrı iş parçacığında.
            result = await asyncio.to_thread(_run_search, request, limit, tuple(exclude_film_ids))
        except ImportError as exc:
            logger.error("Arama servisi yüklenemedi: %s", exc)
            raise SearchError from exc
        except (
            Exception
        ) as exc:  # dış servis sınırı: ayrıntı loga gider, kullanıcıya sade hata döner
            logger.exception("Arama servisi hatası")
            raise SearchError from exc
        return RetrievalResult(
            candidates=tuple(
                RetrievedCandidate(
                    c.film_id, c.rerank_score, c.rrf_rank, tuple(c.sources), c.rank_value
                )
                for c in result.candidates
            ),
            relaxed_filters=tuple(result.relaxed_filters),
            pool_size=result.pool_size,
            timings=dict(result.timings),
            people_found=tuple(result.people_found),
        )

    async def people_films(self, people: list[tuple[str, str]]) -> list[tuple[str, int, list[int]]]:
        """Soru ve diğer niyetlerde arşiv olgusu için: kişi başına film sayısı ve kimlikleri."""
        try:
            return await asyncio.to_thread(_run_people_films, people)
        except ImportError as exc:
            logger.error("Arama servisi yüklenemedi: %s", exc)
            raise SearchError from exc
        except Exception as exc:  # dış servis sınırı: ayrıntı loga gider
            logger.exception("Kişi dizini hatası")
            raise SearchError from exc
