"""Uçtan uca ölçüm ölçütleri: saf fonksiyonlar (girdi listeler, çıktı sayı) ve küme özeti.

Sıra/R@k tanımları `apps.search.services.evaluation` ile aynıdır (yeniden kullanılır).
"""

import statistics
from collections.abc import Sequence

from apps.search.services.evaluation import rank_of

STATUS_OK = "ok"
STATUS_ERROR = "hata"
STATUS_NO_DRAFT = "taslak yok"
MEASURED = (STATUS_OK, STATUS_NO_DRAFT)


def precision_draft(draft_wikidata_ids: Sequence[str], answer_qids: frozenset[str]) -> float | None:
    """Taslaktaki filmlerden cevap listesinde olanların oranı; taslak boşsa None.
    Liste eksik olabildiği için gerçek kesinliğin ALT SINIRIDIR."""
    if not draft_wikidata_ids:
        return None
    return sum(1 for qid in draft_wikidata_ids if qid in answer_qids) / len(draft_wikidata_ids)


def tone_metrics(
    draft_film_ids: Sequence[int], gains: dict[int, float], relevant: frozenset[int]
) -> dict:
    """Genome kapsamındaki (yargılı) taslak filmler ve bunların uygun olanı; kapsam dışı filmler
    yargılanamaz, ayrı sayılır. Ek kısıtı sağlamayan yargılı film kazancı 0 olduğu için uygun
    sayılmaz."""
    covered = [film_id for film_id in draft_film_ids if film_id in gains]
    appropriate = sum(1 for film_id in covered if film_id in relevant)
    return {
        "covered": len(covered),
        "uncovered": len(draft_film_ids) - len(covered),
        "appropriate": appropriate,
        "precision_covered": appropriate / len(covered) if covered else None,
    }


def known_metrics(
    target_film_id: int, draft_film_ids: Sequence[int], search_lists: Sequence[Sequence[int]]
) -> dict:
    """`search_lists`: turdaki arama çağrılarının aday listeleri (çağrı sırasıyla).
    Aday sırası yalnız arama yapıldıysa vardır; aramada hedef yoksa sıra None (kaçırdı)."""
    draft_rank = rank_of(target_film_id, draft_film_ids)
    searched = bool(search_lists)
    ranks = [rank_of(target_film_id, ids) for ids in search_lists]
    found = [rank for rank in ranks if rank is not None]
    return {
        "hit_draft": draft_rank is not None,
        "draft_rank": draft_rank,
        "searched": searched,
        "first_search_rank": ranks[0] if searched else None,
        "best_search_rank": min(found) if found else None,
    }


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def _total_cost(records: Sequence[dict]) -> float | None:
    """Bütün denemelerin harcaması (yeniden denenen hatalı turun eski denemesi dahil)."""
    if any(record["total_cost_usd"] is None for record in records):
        return None
    return round(sum(record["total_cost_usd"] for record in records), 4)


def rate(total: float, n: int, denominator: str) -> dict:
    """Bir oran: değer, kendi paydası (`n`) ve payda adı birlikte. Payda 0 ise değer None."""
    return {
        "value": round(total / n, 4) if n else None,
        "n": n,
        "denominator": denominator,
    }


def summarize_set(set_name: str, records: Sequence[dict]) -> dict:
    """Bir kümenin özeti. Her ölçüt iki oranla gelir ve her oran kendi paydasını taşır
    (`rate`): `<ad>_defined` ölçütün tanımlı olduğu turlar üzerinden, `<ad>_all` bütün istekler
    (`n_total`) üzerinden; hatalı ve taslaksız tur `_all`'da 0 sayılır (tone25'te yargılanamayan
    tur hariç). Hatalı turlar ayrıca sayılır ve harcamaya dahildir."""
    measured = [record for record in records if record["status"] in MEASURED]
    seconds = [record["seconds"] for record in measured]
    total_cost = _total_cost(records)
    summary = {
        "n": len(records),
        "n_total": len(records),
        "n_ok": len(measured),
        "attempts": sum(record.get("attempts", 1) for record in records),
        "ok": sum(1 for record in records if record["status"] == STATUS_OK),
        "no_draft": sum(1 for record in records if record["status"] == STATUS_NO_DRAFT),
        "failed": sum(1 for record in records if record["status"] == STATUS_ERROR),
        "mean_films": _mean([record["film_count"] for record in measured]),
        "mean_quote_match": _mean(
            [r["quote_match_rate"] for r in measured if r["quote_match_rate"] is not None]
        ),
        "mean_dropped": _mean([record["dropped_films"] for record in measured]),
        "mean_calls": _mean([record["calls"] for record in measured]),
        "seconds_median": round(statistics.median(seconds), 2) if seconds else None,
        "seconds_max": round(max(seconds), 2) if seconds else None,
        "total_cost_usd": total_cost,
        "mean_cost_usd": (
            round(total_cost / len(records), 4) if total_cost is not None and records else None
        ),
    }
    metrics = [record["metrics"] for record in measured]
    if set_name == "known50":
        summary.update(_known_summary(metrics, len(records)))
    elif set_name == "konu30":
        summary.update(_konu_summary(metrics, records))
    elif set_name == "tone25":
        summary.update(_tone_summary(measured, len(records)))
    return summary


def _known_summary(metrics: Sequence[dict], n_total: int) -> dict:
    hits = [m for m in metrics if m["hit_draft"]]
    searched = [m["first_search_rank"] for m in metrics if m["searched"]]
    summary = {
        "hit_draft_defined": rate(len(hits), len(metrics), "n_ok"),
        "hit_draft_all": rate(len(hits), n_total, "n_total"),
        "mean_draft_rank": _mean([m["draft_rank"] for m in hits]),
        "n_searched": len(searched),
    }
    for k in (1, 10, 50):
        found = sum(1 for rank in searched if rank is not None and rank <= k)
        summary[f"R@{k}_defined"] = rate(found, len(searched), "n_searched")
        summary[f"R@{k}_all"] = rate(found, n_total, "n_total")
    return summary


def _konu_summary(metrics: Sequence[dict], records: Sequence[dict]) -> dict:
    values = [m["precision_draft"] for m in metrics if m["precision_draft"] is not None]
    coverage = [record.get("answer_key") or {} for record in records]
    return {
        "precision_draft_defined": rate(sum(values), len(values), "n_with_draft"),
        "precision_draft_all": rate(sum(values), len(records), "n_total"),
        "n_with_draft": len(values),
        "answer_ids": sum(c.get("size", 0) for c in coverage),
        "answer_in_db": sum(c.get("in_db", 0) for c in coverage),
        "answer_missing": sum(c.get("missing", 0) for c in coverage),
    }


def _tone_summary(measured: Sequence[dict], n_total: int) -> dict:
    """Taslağında en az bir film olup hiçbiri genome kapsamında olmayan tur (`n_unjudgeable`)
    veri sınırıdır, model hatası değil: `_all` paydasına girmez. Hatalı, taslaksız ve filmi
    olmayan taslaklı tur payda içinde 0'dır."""
    values = [r["metrics"]["precision_covered"] for r in measured]
    judged = [value for value in values if value is not None]
    unjudgeable = sum(
        1
        for r in measured
        if r["status"] == STATUS_OK and r["film_count"] > 0 and r["metrics"]["covered"] == 0
    )
    return {
        "precision_covered_defined": rate(sum(judged), len(judged), "n_with_coverage"),
        "precision_covered_all": rate(
            sum(judged), n_total - unjudgeable, "n_total - n_unjudgeable"
        ),
        "n_with_coverage": len(judged),
        "n_unjudgeable": unjudgeable,
        "covered": sum(r["metrics"]["covered"] for r in measured),
        "uncovered": sum(r["metrics"]["uncovered"] for r in measured),
    }
