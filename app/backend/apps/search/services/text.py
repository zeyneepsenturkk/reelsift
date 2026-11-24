"""Arama hattının saf mantığı (veritabanı ve model yok): ad eşleme, RRF, belge metni, harman.

Deney betikleri `lib_t.py` (`norm_t`, `g_match`, `rrf`, `fuse`, `ptext`, `docA`, `docB`) ile
birebir aynı tariflerdir; değişiklik ölçülmüş sayıları bozar.
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence

import numpy as np

from apps.search.services.types import TitleHint

DOC_MODES = ("A", "B", "B_end")

_LEADING_ARTICLE = re.compile(r"^(the|a|an|le|la|les|el|il) ")


def normalize_title(title: str) -> str:
    """ASCII'ye indirir, noktalamayı atar, baştaki makaleyi (the, a, le...) kaldırır."""
    ascii_text = (
        unicodedata.normalize("NFKD", str(title)).encode("ascii", "ignore").decode().lower()
    )
    ascii_text = re.sub(r"[^a-z0-9 ]", " ", ascii_text)
    ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
    return _LEADING_ARTICLE.sub("", ascii_text)


TitleIndex = dict[str, list[tuple[int, int | None]]]


def build_title_index(rows: Iterable[tuple[int, str, int | None]]) -> TitleIndex:
    """(film_id, ad, yıl) satırlarından normalleşmiş ad -> [(film_id, yıl)] sözlüğü."""
    index: TitleIndex = defaultdict(list)
    for film_id, title, year in rows:
        index[normalize_title(title)].append((film_id, year))
    return dict(index)


def match_titles(index: TitleIndex, hints: Sequence[TitleHint]) -> list[int]:
    """Modelin önerdiği adların arşivdeki karşılığı: aynı normalleşmiş ad, yıl farkı en çok 1.

    Deneyde yılı olmayan öneri atlanıyordu; burada yıl yoksa yalnız ada bakılır (ilk eşleşme)."""
    matched: list[int] = []
    for hint in hints:
        for film_id, year in index.get(normalize_title(hint.title), []):
            if year is None or hint.year is None or abs(year - hint.year) <= 1:
                matched.append(film_id)
                break
    return matched


def rrf_scores(ranked_lists: Sequence[Sequence[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal rank fusion: her listede 1. sıra 1/(k+1), 2. sıra 1/(k+2) ..."""
    scores: dict[int, float] = defaultdict(float)
    for ranked in ranked_lists:
        for position, film_id in enumerate(ranked, start=1):
            scores[film_id] += 1.0 / (k + position)
    return dict(scores)


def top_ranked(film_ids: np.ndarray, scores: np.ndarray, depth: int) -> np.ndarray:
    """Puana göre azalan en iyi `depth` film kimliği (eşitlikte girdi sırası korunur)."""
    if len(film_ids) == 0:
        return film_ids
    order = np.argsort(-scores, kind="stable")[:depth]
    return film_ids[order]


def fuse(
    sources: dict[str, Sequence[int]],
    order: Sequence[str],
    plot_lengths: dict[int, int],
    suggested: Iterable[int],
    *,
    rrf_k: int,
    min_plot_chars: int,
) -> tuple[list[int], dict[int, float]]:
    """Kaynakları RRF ile birleştirir; hikâyesi kısa olup model önerisi olmayan filmleri eler.

    Dönüş: azalan RRF puanıyla sıralı film kimlikleri ve puan sözlüğü.
    Eşitlikte küçük kimlik önde."""
    scores = rrf_scores([sources[name] for name in order if len(sources.get(name, ()))], rrf_k)
    keep = set(suggested)
    scores = {
        film_id: score
        for film_id, score in scores.items()
        if film_id in keep or plot_lengths.get(film_id, 0) >= min_plot_chars
    }
    ranked = sorted(scores, key=lambda film_id: (-scores[film_id], film_id))
    return ranked, scores


def _as_list(value) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return [str(value)] if value else []


def profile_text(
    *,
    themes: Sequence[str],
    moods: Sequence[str],
    tone: str,
    pacing: str,
    setting_place: str,
    setting_period: str,
    narrative: Sequence[str],
    for_viewers: str,
) -> str:
    """Film profilini yeniden sıralama modeline verilen düz metne çevirir (deneydeki `ptext`)."""
    parts = []
    if themes:
        parts.append("Themes: " + "; ".join(_as_list(themes)) + ".")
    if moods:
        parts.append("Mood: " + ", ".join(_as_list(moods)) + ".")
    if tone:
        parts.append("Tone: " + str(tone))
    if pacing and pacing != "unknown":
        parts.append("Pacing: " + str(pacing) + ".")
    setting = [
        str(value)
        for value in (setting_place, setting_period)
        if value and str(value).lower() != "unknown"
    ]
    if setting:
        parts.append("Setting: " + ", ".join(setting) + ".")
    if narrative:
        parts.append("Narrative: " + ", ".join(_as_list(narrative)) + ".")
    viewers = str(for_viewers or "")
    if viewers:
        viewers = re.sub(r"^For viewers looking for\s*", "", viewers, flags=re.IGNORECASE)
        parts.append("For viewers looking for " + viewers)
    return " ".join(parts)


def usable_profile_text(text: str) -> str:
    """Deneyde 20 karakter ve altındaki profil metni profil sayılmıyordu."""
    return text if len(text) > 20 else ""


def rerank_document(mode: str, overview: str, plot: str, profile: str) -> str:
    """Yeniden sıralama belgesi. A: TMDB özeti + hikâye; B: profil + A; B_end: A + profil."""
    base = f"{overview} {plot}" if overview else plot
    if mode == "A":
        return base
    if mode == "B":
        return f"{profile} {base}".strip()
    if mode == "B_end":
        return f"{base} {profile}".strip()
    raise ValueError(f"Bilinmeyen belge kipi: {mode}")


def blended_order(
    film_ids: Sequence[int],
    rerank_scores: Sequence[float],
    blend: float,
    rrf_k: int = 60,
) -> list[int]:
    """Son sıra. `film_ids` RRF sırasındadır. `blend` = RRF sırasının ağırlığı:
    0 yalnız yeniden sıralama sırası; 1 yalnız RRF sırası; arası iki sıranın ağırlıklı RRF'si."""
    scores = np.asarray(rerank_scores, dtype=np.float64)
    rerank_order = np.argsort(-scores, kind="stable")
    rerank_rank = np.empty(len(film_ids), dtype=np.int64)
    rerank_rank[rerank_order] = np.arange(1, len(film_ids) + 1)
    rrf_rank = np.arange(1, len(film_ids) + 1)
    combined = blend / (rrf_k + rrf_rank) + (1.0 - blend) / (rrf_k + rerank_rank)
    final = np.lexsort((rerank_rank, -combined))
    return [film_ids[i] for i in final]


RANK_MODES = ("rating", "popularity")


def weighted_rating(
    average: float | None, votes: int, *, prior_votes: float, prior_mean: float
) -> float:
    """Bayes ortalaması: az oylu filmin ortalaması arşiv ortalamasına çekilir.
    (v / (v + m)) * R + (m / (v + m)) * C"""
    if not votes or average is None:
        return prior_mean
    return (
        votes / (votes + prior_votes) * average + prior_votes / (votes + prior_votes) * prior_mean
    )


def rank_value(
    rank_by: str, average: float | None, votes: int, *, prior_votes: float, prior_mean: float
) -> float:
    """`rating`: ağırlıklı oy ortalaması; `popularity`: oy sayısı.
    Oyu olmayan film `rating`'de 0 alır: oy almış her filmin ağırlıklı değeri 0'dan büyüktür,
    böylece oysuz film arşiv ortalamasıyla az oylu filmlerin önüne geçmez."""
    if rank_by == "rating":
        if not votes or average is None:
            return 0.0
        return weighted_rating(average, votes, prior_votes=prior_votes, prior_mean=prior_mean)
    if rank_by == "popularity":
        return float(votes)
    raise ValueError(f"Bilinmeyen sıralama: {rank_by}")
