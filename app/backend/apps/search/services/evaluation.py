"""Arama değerlendirmesi: ölçütler (saf) + kayıtlı çözümlemelerle iki ölçüm seti.

known50: 50 tarif, hedef film arşivde kaçıncı sırada (R@1/10/50). tone25: 25 ton isteği, MovieLens
etiket genomu cevap anahtarı (P@10, nDCG@10). Dil modeli çağrılmaz; çözümlemeler `/data` altındaki
kayıtlı dosyalardan okunur. Veri yalnız `/data`'dan okunur, repoya ve veritabanına girmez.
"""

import csv
import json
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from django.conf import settings

from apps.core.exceptions import ServiceError
from apps.films.models import Film
from apps.search.services.types import ParsedQuery, QueryFilters, TitleHint

RELEVANT_THRESHOLD = 0.8
KNOWN_VOTE_COUNT = 1000
_DISCOUNTS = 1 / np.log2(np.arange(2, 12))

KNOWN_DIR = "_gecici/embtest-betikler"
TONE_DIR = "degerlendirme"
TONE_PARSED = "degerlendirme/ton-dogrulama/haiku_ton.json"
TONE_REQUESTS = "degerlendirme/ton_istekleri.json"
GENOME_PARQUET = "degerlendirme/genome_arsiv.parquet"
DATASET_CSV = "dataset/final_dataset.csv"


def rank_of(film_id: int, ordered: Sequence[int]) -> int | None:
    """Film kimliğinin 1 tabanlı sırası; listede yoksa None (sıra listenin ötesindedir)."""
    try:
        return ordered.index(film_id) + 1
    except ValueError:
        return None


def recall_at(ranks: Sequence[int | None], k: int) -> float:
    return sum(1 for rank in ranks if rank is not None and rank <= k) / len(ranks)


def precision_at_10(ordered: Sequence[int], gains: dict[int, float], relevant: set[int]) -> float:
    """İlk 10 yargılı filmin kaçı uygun; yargısız filmler sıradan çıkarılır, payda her zaman 10."""
    top = [film_id for film_id in ordered if film_id in gains][:10]
    return sum(1 for film_id in top if film_id in relevant) / 10


def ndcg_at_10(ordered: Sequence[int], gains: dict[int, float]) -> float:
    """Kazanç = etiket uygunluk değeri; ideal sıra tüm yargılı filmlerin en yüksek 10 değeri."""
    top = [gains[film_id] for film_id in ordered if film_id in gains][:10]
    ideal = sorted(gains.values(), reverse=True)[:10]
    ideal_dcg = float((np.array(ideal) * _DISCOUNTS[: len(ideal)]).sum())
    dcg = float((np.array(top) * _DISCOUNTS[: len(top)]).sum())
    return dcg / ideal_dcg if ideal_dcg else 0.0


def mean_relevance_at_10(ordered: Sequence[int], gains: dict[int, float]) -> float:
    top = [gains[film_id] for film_id in ordered if film_id in gains][:10]
    return float(np.pad(top, (0, 10 - len(top))).mean())


def coverage_recall(candidates: Sequence[int], relevant: set[int]) -> float:
    """Aday listesindeki uygun film sayısı / min(50, uygun film sayısı)."""
    return len(relevant.intersection(candidates)) / min(50, len(relevant))


def median_and_max(values: Sequence[float]) -> tuple[float, float]:
    return statistics.median(values), max(values)


def _root() -> Path:
    return Path(settings.SEARCH["eval_data_dir"])


def _read_json(path: Path, encoding: str = "utf-8"):
    if not path.exists():
        raise ServiceError(f"Değerlendirme verisi yok: {path}", "eval_data_missing", 500)
    return json.loads(path.read_bytes().decode(encoding))


def query_from_parsed(out: dict, *, with_filters: bool) -> ParsedQuery:
    """Kayıtlı model çıktısı -> ParsedQuery. Tür (genres) sert filtre değil; ölçümde kullanılmaz."""
    titles = []
    for hint in out.get("titles") or []:
        try:
            titles.append(TitleHint(hint["title"], int(hint["year"])))
        except (KeyError, TypeError, ValueError):
            continue  # deneyde yılı okunamayan öneri atlanıyordu
    filters = QueryFilters()
    if with_filters:
        raw = out.get("filters") or {}
        filters = QueryFilters(
            year_min=raw.get("year_min"),
            year_max=raw.get("year_max"),
            countries=tuple(raw.get("countries") or ()),
            max_vote_count=raw.get("max_vote_count"),
        )
    return ParsedQuery(out["en_query"], out["hyde"], tuple(titles), filters)


@dataclass
class KnownItem:
    index: int
    description: str
    target_wikidata_id: str
    known: bool
    query: ParsedQuery
    target_film_id: int | None = None


def load_known50(*, with_filters: bool = False) -> list[KnownItem]:
    base = _root() / KNOWN_DIR
    targets = _read_json(base / "b.json") + _read_json(base / "b2.json")
    parsed = _read_json(base / "haiku_out.json")["R"]
    parsed = sorted((row for row in parsed if row["kind"] == "b"), key=lambda row: row["n"])
    descriptions = _read_json(base / "kor_tarifler.json")
    if not (len(targets) == len(parsed) == len(descriptions) == 50):
        raise ServiceError("known50 dosyalarının uzunluğu 50 değil.", "eval_data_mismatch", 500)
    items = []
    for k, (target, row, description) in enumerate(zip(targets, parsed, descriptions, strict=True)):
        if row["tr"] != description["tr"]:
            raise ServiceError(
                f"known50 tarif {k}: çözümleme başka tarife ait.", "eval_data_mismatch", 500
            )
        items.append(
            KnownItem(
                k,
                row["tr"],
                target["id"],
                False,
                query_from_parsed(row["out"], with_filters=with_filters),
            )
        )
    films = {
        wikidata_id: (pk, vote_count)
        for wikidata_id, pk, vote_count in Film.objects.filter(
            wikidata_id__in=[item.target_wikidata_id for item in items]
        ).values_list("wikidata_id", "pk", "vote_count")
    }
    for item in items:
        pk, vote_count = films.get(item.target_wikidata_id, (None, 0))
        item.target_film_id = pk
        item.known = vote_count >= KNOWN_VOTE_COUNT  # deneydeki tanım: oy sayısı 1000 ve üstü
    missing = [item.target_wikidata_id for item in items if item.target_film_id is None]
    if missing:
        raise ServiceError(f"Hedef filmler veritabanında yok: {missing}", "eval_data_mismatch", 500)
    return items


@dataclass
class ToneItem:
    qid: str
    description: str
    query: ParsedQuery
    gains: dict[int, float]  # yargılı filmler (film kimliği -> kazanç)
    relevant: set[int] = field(default_factory=set)


def _genome_scores() -> dict[str, dict[str, float]]:
    import pyarrow.parquet as pq

    path = _root() / GENOME_PARQUET
    if not path.exists():
        raise ServiceError(f"Değerlendirme verisi yok: {path}", "eval_data_missing", 500)
    table = pq.read_table(path, columns=["QID", "tag", "relevance"]).to_pydict()
    scores: dict[str, dict[str, float]] = {}
    for qid, tag, relevance in zip(table["QID"], table["tag"], table["relevance"], strict=True):
        if relevance is not None and not np.isnan(relevance):
            scores.setdefault(qid, {})[tag] = float(relevance)
    return scores


def _dataset_attributes(wikidata_ids: set[str]) -> dict[str, tuple[str, str, float]]:
    """Ek kısıtlar (tür, ülke, yıl) veri setindeki yazımıyla uygulanır (deneydeki `ek_ok`)."""
    csv.field_size_limit(10**8)
    attributes = {}
    with open(_root() / DATASET_CSV, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["movie_id"] in wikidata_ids:
                try:
                    year = float(row["year"])
                except ValueError:
                    year = float("nan")
                attributes[row["movie_id"]] = (row["genre"] or "", row["country"] or "", year)
    return attributes


def _constraint_ok(constraint: dict | None, attributes: tuple[str, str, float]) -> bool:
    if not constraint:
        return True
    genre, country, year = attributes
    if "tur" in constraint and not re.search(constraint["tur"], genre):
        return False
    if "yil_min" in constraint and not year >= constraint["yil_min"]:
        return False
    if "yil_max" in constraint and not year <= constraint["yil_max"]:
        return False
    return not ("ulke" in constraint and not any(name in country for name in constraint["ulke"]))


def load_tone25() -> tuple[list[ToneItem], set[int]]:
    """25 ton isteği ve genome kapsamındaki film kimlikleri (aday havuzu)."""
    root = _root()
    requests = json.loads((root / TONE_REQUESTS).read_bytes().decode("cp1254"))
    parsed = {row["id"]: row for row in _read_json(root / TONE_PARSED)}
    genome = _genome_scores()
    film_ids = dict(
        Film.objects.filter(wikidata_id__in=list(genome)).values_list("wikidata_id", "pk")
    )
    if len(film_ids) != len(genome):
        raise ServiceError(
            "Genome filmlerinin bir kısmı veritabanında yok.", "eval_data_mismatch", 500
        )
    attributes = _dataset_attributes(set(genome))
    items = []
    for request in requests:
        gains: dict[int, float] = {}
        for wikidata_id, tags in genome.items():
            values = [tags[tag] for tag in request["etiketler"] if tag in tags]
            if not values:
                continue  # bu isteğin etiketlerinden hiçbiri bu filmde yok: yargısız
            ok = _constraint_ok(request["ek_kisit"], attributes[wikidata_id])
            gains[film_ids[wikidata_id]] = max(values) if ok else 0.0
        relevant = {film_id for film_id, gain in gains.items() if gain >= RELEVANT_THRESHOLD}
        if len(relevant) != request["uygun_qidler_sayisi"]:
            raise ServiceError(
                f"{request['id']}: cevap anahtarı tutmuyor ({len(relevant)} != "
                f"{request['uygun_qidler_sayisi']}).",
                "eval_data_mismatch",
                500,
            )
        out = dict(parsed[request["id"]]["out"])
        items.append(
            ToneItem(
                request["id"],
                request["istek_en"],
                query_from_parsed(out, with_filters=True),
                gains,
                relevant,
            )
        )
    return items, set(film_ids.values())


def arm_name(doc_mode: str | None, blend: float) -> str:
    if doc_mode is None:
        return "RRF sırası"
    return f"belge {doc_mode}, harman {blend:g}"


def _group_summary(ranks: list[int | None], mask: list[bool] | None = None) -> dict:
    selected = [r for r, keep in zip(ranks, mask or [True] * len(ranks), strict=True) if keep]
    return {
        "n": len(selected),
        "R@1": recall_at(selected, 1),
        "R@10": recall_at(selected, 10),
        "R@50": recall_at(selected, 50),
    }


def run_known50(
    doc_modes: Sequence[str], blends: Sequence[float], vector_mode: str, with_filters: bool
) -> dict:
    from apps.search.services import pipeline  # model ve indeks yükleyen modül, çağrı anında

    items = load_known50(with_filters=with_filters)
    arms = [(None, 0.0)] + [(doc, blend) for doc in doc_modes for blend in blends]
    ranks: dict[tuple, list[int | None]] = {arm: [] for arm in arms}
    gather_seconds: list[float] = []
    for item in items:
        gathered = pipeline.gather(item.query, limit=50, vector_mode=vector_mode)
        gather_seconds.append(gathered.timings["gather"])
        ranks[(None, 0.0)].append(rank_of(item.target_film_id, gathered.film_ids))
        for doc in doc_modes:
            scores = pipeline.rerank_scores(item.query.en_query, gathered.film_ids, doc)
            for blend in blends:
                final = pipeline.finalize(gathered, scores, blend)
                order = [candidate.film_id for candidate in final.candidates]
                ranks[(doc, blend)].append(rank_of(item.target_film_id, order))
    known = [item.known for item in items]
    rows = []
    for arm in arms:
        rows.append(
            {
                "arm": arm_name(*arm),
                "all": _group_summary(ranks[arm]),
                "known": _group_summary(ranks[arm], known),
                "less_known": _group_summary(ranks[arm], [not flag for flag in known]),
            }
        )
    median, longest = median_and_max(gather_seconds)
    return {
        "set": "known50",
        "vector_mode": vector_mode,
        "with_filters": with_filters,
        "rows": rows,
        "gather_seconds": {"median": median, "max": longest},
        "per_query": [
            {"index": item.index, "target": item.target_wikidata_id, "known": item.known}
            | {arm_name(*arm): ranks[arm][item.index] for arm in arms}
            for item in items
        ],
    }


def run_tone25(
    doc_modes: Sequence[str], blends: Sequence[float], vector_mode: str, pool: str
) -> dict:
    from apps.search.services import pipeline

    items, genome_film_ids = load_tone25()
    pool_film_ids = genome_film_ids if pool == "genome" else None
    arms = [(None, 0.0)] + [(doc, blend) for doc in doc_modes for blend in blends]
    metrics: dict[tuple, list[dict]] = {arm: [] for arm in arms}
    gather_seconds: list[float] = []
    pool_sizes: list[int] = []
    for item in items:
        gathered = pipeline.gather(
            item.query, limit=50, pool_film_ids=pool_film_ids, vector_mode=vector_mode
        )
        gather_seconds.append(gathered.timings["gather"])
        pool_sizes.append(gathered.pool_size)
        coverage = coverage_recall(gathered.film_ids, item.relevant)

        def record(arm, order, item=item, coverage=coverage):
            metrics[arm].append(
                {
                    "P@10": precision_at_10(order, item.gains, item.relevant),
                    "nDCG@10": ndcg_at_10(order, item.gains),
                    "ortRel@10": mean_relevance_at_10(order, item.gains),
                    "R@50": coverage,
                }
            )

        record((None, 0.0), gathered.film_ids)
        for doc in doc_modes:
            scores = pipeline.rerank_scores(item.query.en_query, gathered.film_ids, doc)
            for blend in blends:
                final = pipeline.finalize(gathered, scores, blend)
                record((doc, blend), [candidate.film_id for candidate in final.candidates])
    rows = [
        {
            "arm": arm_name(*arm),
            **{
                name: float(np.mean([m[name] for m in metrics[arm]]))
                for name in ("P@10", "nDCG@10", "ortRel@10", "R@50")
            },
        }
        for arm in arms
    ]
    median, longest = median_and_max(gather_seconds)
    return {
        "set": "tone25",
        "vector_mode": vector_mode,
        "pool": pool,
        "n": len(items),
        "rows": rows,
        "gather_seconds": {"median": median, "max": longest},
        "per_query": [
            {"id": item.qid, "relevant": len(item.relevant), "pool_size": pool_sizes[k]}
            | {arm_name(*arm): metrics[arm][k] for arm in arms}
            for k, item in enumerate(items)
        ],
    }
