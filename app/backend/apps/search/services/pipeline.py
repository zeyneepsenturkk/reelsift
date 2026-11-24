"""Arama hattı: çözümlenmiş istek -> aday kaynakları -> RRF -> yeniden sıralama.

`search` agent'ın çağırdığı tek giriş noktasıdır (iş parçacığından çağrılabilir: modeller ve indeks
kilitle yüklenir). Değerlendirme komutu hattı adımlara bölünmüş halde (`gather`, `rerank_scores`,
`finalize`) kullanır; böylece aynı adaylarla farklı belge kipi ve harman ağırlığı ölçülebilir.

Kişi verilmişse (`ParsedQuery.people`) aday evreni o kişilerin arşivdeki filmleridir: aynı kaynak
listeleri evrenle sınırlı kapsamda çalışır, kısa hikâye elemesi uygulanmaz ve `rank_by` varsa sıra
oy ortalamasına (ağırlıklı) ya da oy sayısına göre kodla verilir.
"""

import logging
import time
from collections.abc import Collection
from dataclasses import dataclass, field

import numpy as np
from django.conf import settings
from django.db.models.functions import Length

from apps.films.models import Film, FilmProfile
from apps.search.services import lexical, neural, scope, text, vectors
from apps.search.services.types import Candidate, ParsedQuery, PersonHint, SearchResult

logger = logging.getLogger(__name__)

# RRF kaynak sırası (deneydeki `USE`).
SOURCE_ORDER = ("dense", "bma", "hyde", "g", "card", "bmb")
# Kişi kaynağı RRF'ye girmez (kimliğe göre sıralı bir liste sıra bilgisi taşımaz); yalnız etikettir.
PERSON_SOURCE = "person"


@dataclass
class Gathered:
    """Birleştirme sonrası ilk `limit` aday (RRF sırasıyla) ve hat bilgisi."""

    film_ids: list[int]
    sources: dict[int, tuple[str, ...]]
    pool_size: int
    relaxed_filters: tuple[str, ...]
    timings: dict[str, float] = field(default_factory=dict)
    people_found: tuple[tuple[str, int], ...] = ()
    # `rank_by` verildiyse adayların değeri; `keep_order` ise `film_ids` zaten bu değere göre sıralı
    # ve yeniden sıralama puanı sırayı değiştirmez.
    rank_values: dict[int, float] | None = None
    keep_order: bool = False
    # Birleştirme sırası (kişi evreninde `film_ids` sırasından farklı olabilir); yoksa sıra no.
    rrf_ranks: dict[int, int] | None = None


class _Timer:
    def __init__(self, timings: dict[str, float]):
        self.timings = timings

    def step(self, name: str, started: float) -> None:
        self.timings[name] = round(self.timings.get(name, 0.0) + time.perf_counter() - started, 4)


def _rank_values(film_ids: list[int], rank_by: str) -> dict[int, float]:
    config = settings.SEARCH
    rows = Film.objects.filter(pk__in=film_ids).values_list("pk", "vote_average", "vote_count")
    return {
        pk: text.rank_value(
            rank_by,
            average,
            votes,
            prior_votes=config["rating_prior_votes"],
            prior_mean=config["rating_prior_mean"],
        )
        for pk, average, votes in rows
    }


def _people_universe(
    index: lexical.LexicalIndex, people: tuple[PersonHint, ...]
) -> tuple[tuple[tuple[str, int], ...], np.ndarray]:
    """Kişi başına arşivdeki film sayısı (filtreden önce) ve kişilerin filmlerinin birleşimi."""
    found = []
    universe = []
    for hint in people:
        film_ids = index.people.films(hint.name, hint.role)
        found.append((hint.name, int(film_ids.size)))
        universe.append(film_ids)
    return tuple(found), np.unique(np.concatenate(universe))


def gather(
    query: ParsedQuery,
    *,
    limit: int,
    exclude_film_ids: Collection[int] = (),
    pool_film_ids: Collection[int] | None = None,
    vector_mode: str | None = None,
) -> Gathered:
    config = settings.SEARCH
    mode = vector_mode or config["vector_mode"]
    depth = config["depth"]
    timings: dict[str, float] = {}
    timer = _Timer(timings)
    started_all = time.perf_counter()

    started = time.perf_counter()
    index = lexical.get_index()
    timer.step("index", started)

    started = time.perf_counter()
    person_mode = bool(query.people)
    people_found: tuple[tuple[str, int], ...] = ()
    if person_mode:
        people_found, universe = _people_universe(index, query.people)
        film_scope = scope.resolve_people_scope(
            query.filters, universe, exclude_film_ids=exclude_film_ids, pool_film_ids=pool_film_ids
        )
    else:
        film_scope = scope.resolve_scope(
            query.filters, exclude_film_ids=exclude_film_ids, pool_film_ids=pool_film_ids
        )
    timer.step("scope", started)
    if person_mode and film_scope.film_ids is not None and film_scope.film_ids.size == 0:
        # Kişi arşivde yok (ya da filmlerinin hepsi hariç tutuldu): başka kişinin filmi getirilmez.
        timings["gather"] = round(time.perf_counter() - started_all, 4)
        return Gathered([], {}, 0, film_scope.relaxed, timings, people_found)

    started = time.perf_counter()
    en_vector, hyde_vector = neural.encode_texts([query.en_query, query.hyde])
    timer.step("encode", started)

    lists: dict[str, np.ndarray] = {}
    matched: dict[str, set[int]] = {}

    started = time.perf_counter()
    ids, scores = vectors.chunk_scores(en_vector, film_scope, mode)
    lists["dense"] = text.top_ranked(ids, scores, depth)
    timer.step("dense", started)

    started = time.perf_counter()
    ids, scores = vectors.chunk_scores(hyde_vector, film_scope, mode)
    lists["hyde"] = text.top_ranked(ids, scores, depth)
    timer.step("hyde", started)

    started = time.perf_counter()
    ids, scores = vectors.card_scores(en_vector, film_scope, mode)
    lists["card"] = text.top_ranked(ids, scores, depth)
    timer.step("card", started)

    started = time.perf_counter()
    in_scope = film_scope.mask_for(index.film_ids)
    for list_name, index_name in (("bma", "a"), ("bmb", "b")):
        bm25 = index.scores(index_name, query.en_query)
        film_ids = index.film_ids
        if in_scope is not None:
            film_ids, bm25 = film_ids[in_scope], bm25[in_scope]
        lists[list_name] = text.top_ranked(film_ids, bm25, depth)
        # Hiç kelimesi eşleşmeyen (puanı 0) filmler listeyi doldurur ama kaynak sayılmaz.
        matched[list_name] = set(film_ids[bm25 > 0].tolist())
    timer.step("bm25", started)

    started = time.perf_counter()
    suggested = text.match_titles(index.titles, query.titles)
    suggested = [film_id for film_id in suggested if film_scope.allows(film_id)]
    suggested = list(dict.fromkeys(suggested))
    lists["g"] = np.array(suggested, dtype=np.int64)
    timer.step("g", started)

    started = time.perf_counter()
    union = {film_id for arr in lists.values() for film_id in arr.tolist()}
    plot_lengths = dict(
        Film.objects.filter(pk__in=union)
        .annotate(plot_length=Length("plot"))
        .values_list("pk", "plot_length")
    )
    ranked, rrf_scores = text.fuse(
        {name: arr.tolist() for name, arr in lists.items()},
        SOURCE_ORDER,
        plot_lengths,
        suggested,
        rrf_k=config["rrf_k"],
        # Kişi evreninde kısa hikâyeli film de o kişinin filmidir; elenmez.
        min_plot_chars=0 if person_mode else config["min_plot_chars"],
    )
    if person_mode:
        # Evren listelerin derinliğini aşarsa dışarıda kalan film olmasın (kimlik sırasıyla sona).
        ranked += [film_id for film_id in film_scope.film_ids.tolist() if film_id not in rrf_scores]
    timer.step("fuse", started)

    rank_values = None
    keep_order = False
    top = ranked[:limit]
    if query.rank_by:
        started = time.perf_counter()
        if person_mode:
            values = _rank_values(ranked, query.rank_by)
            position = {film_id: place for place, film_id in enumerate(ranked)}
            ranked_by_value = sorted(ranked, key=lambda f: (-values.get(f, 0.0), position[f]))
            top = ranked_by_value[:limit]
            keep_order = True
        else:
            values = _rank_values(top, query.rank_by)
        rank_values = {film_id: values.get(film_id, 0.0) for film_id in top}
        timer.step("rank", started)
    rrf_place = {film_id: place for place, film_id in enumerate(ranked, start=1)}
    rrf_ranks = {film_id: rrf_place[film_id] for film_id in top}
    members = {name: set(arr.tolist()) for name, arr in lists.items()}
    for name, positive in matched.items():
        members[name] &= positive
    sources = {
        film_id: tuple(name for name in SOURCE_ORDER if film_id in members.get(name, ()))
        + ((PERSON_SOURCE,) if person_mode else ())
        for film_id in top
    }
    timings["gather"] = round(time.perf_counter() - started_all, 4)
    return Gathered(
        top,
        sources,
        len(ranked),
        film_scope.relaxed,
        timings,
        people_found,
        rank_values,
        keep_order,
        rrf_ranks,
    )


def _profile_texts(film_ids: list[int]) -> dict[int, str]:
    fields = (
        "film_id",
        "themes",
        "moods",
        "tone",
        "pacing",
        "setting_place",
        "setting_period",
        "narrative",
        "for_viewers",
    )
    texts = {}
    for row in FilmProfile.objects.filter(film_id__in=film_ids).values(*fields):
        profile = text.usable_profile_text(
            text.profile_text(
                themes=row["themes"],
                moods=row["moods"],
                tone=row["tone"],
                pacing=row["pacing"],
                setting_place=row["setting_place"],
                setting_period=row["setting_period"],
                narrative=row["narrative"],
                for_viewers=row["for_viewers"],
            )
        )
        if profile:
            texts[row["film_id"]] = profile
    return texts


def rerank_documents(film_ids: list[int], mode: str) -> list[str]:
    """Adayların yeniden sıralama belgeleri (`film_ids` sırasında)."""
    rows = {
        pk: (overview or tr_overview, plot)
        for pk, overview, tr_overview, plot in Film.objects.filter(pk__in=film_ids).values_list(
            "pk", "overview", "tr_overview", "plot"
        )
    }
    profiles = _profile_texts(film_ids) if mode != "A" else {}
    return [
        text.rerank_document(mode, rows[pk][0], rows[pk][1], profiles.get(pk, ""))
        for pk in film_ids
    ]


def rerank_scores(en_query: str, film_ids: list[int], mode: str) -> list[float]:
    """Yeniden sıralama puanları (`film_ids` sırasında). Belge kipi: A, B ya da B_end."""
    if not film_ids:
        return []
    documents = rerank_documents(film_ids, mode)
    return neural.score_pairs([(en_query, document) for document in documents])


def finalize(gathered: Gathered, scores: list[float] | None, blend: float) -> SearchResult:
    """Yeniden sıralama puanları (yoksa RRF sırası) ve harman ağırlığıyla son listeyi kurar."""
    rrf_rank = gathered.rrf_ranks or {
        film_id: rank for rank, film_id in enumerate(gathered.film_ids, start=1)
    }
    rank_values = gathered.rank_values or {}
    if scores is None:
        order = list(gathered.film_ids)
        score_of: dict[int, float | None] = dict.fromkeys(order)
    else:
        if gathered.keep_order:
            order = list(gathered.film_ids)
        else:
            order = text.blended_order(gathered.film_ids, scores, blend, settings.SEARCH["rrf_k"])
        score_of = dict(zip(gathered.film_ids, scores, strict=True))
    candidates = tuple(
        Candidate(
            film_id,
            score_of[film_id],
            rrf_rank[film_id],
            gathered.sources[film_id],
            rank_values.get(film_id),
        )
        for film_id in order
    )
    return SearchResult(
        candidates,
        gathered.relaxed_filters,
        gathered.pool_size,
        dict(gathered.timings),
        gathered.people_found,
    )


def search(
    query: ParsedQuery,
    *,
    limit: int = 50,
    exclude_film_ids: Collection[int] = (),
    pool_film_ids: Collection[int] | None = None,
) -> SearchResult:
    config = settings.SEARCH
    started = time.perf_counter()
    gathered = gather(
        query, limit=limit, exclude_film_ids=exclude_film_ids, pool_film_ids=pool_film_ids
    )
    step = time.perf_counter()
    scores = rerank_scores(query.en_query, gathered.film_ids, config["doc_mode"])
    gathered.timings["rerank"] = round(time.perf_counter() - step, 4)
    result = finalize(gathered, scores, config["blend"])
    result.timings["total"] = round(time.perf_counter() - started, 4)
    return result
