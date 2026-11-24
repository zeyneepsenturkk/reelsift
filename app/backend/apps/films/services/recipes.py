"""Vektör tarifleri: deney betikleri `chunk.py`, `embed_pre.py`, `prep4.py` ile birebir aynı olmalı.

Bu dosyadaki her değişiklik mevcut vektörlerle uyumu bozar; `embed_missing` açılışta 20 parçayı
ve 20 kartı yeniden üretip kayıtlı vektörlerle karşılaştırarak tarifin tuttuğunu kanıtlar.
"""

import re

# Cümle sonu işaretinden sonra büyük harf/rakam/tırnak gelen boşluklardan bölünür.
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])["\')\]]*\s+(?=[A-Z0-9"\'(\[])')
_WORDS_MIN = 150
_WORDS_MAX = 200
_WORDS_OVERLAP = 30


def chunk_text(text: str) -> list[str]:
    """Hikâyeyi cümle sınırına saygılı ~150-200 kelimelik, ~30 kelime örtüşmeli parçalara böler."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(str(text)) if s.strip()]
    word_counts = [len(s.split()) for s in sentences]
    if sum(word_counts) <= _WORDS_MAX:
        return [" ".join(sentences)]

    chunks = []
    start = 0
    total = len(sentences)
    while start < total:
        end = start
        words = 0
        while end < total and (words < _WORDS_MIN or words + word_counts[end] <= _WORDS_MAX):
            words += word_counts[end]
            end += 1
            if words >= _WORDS_MAX:
                break
        chunks.append(" ".join(sentences[start:end]))
        if end >= total:
            break
        # Örtüşme: ~30 kelime tutana kadar cümle geri sarılır, ama en az bir cümle ilerlenir.
        back = end
        overlap_words = 0
        while back > start + 1 and overlap_words < _WORDS_OVERLAP:
            back -= 1
            overlap_words += word_counts[back]
        start = back if back > start else end
    return chunks


def film_prefix(title: str, year: int | None, genres: str, country: str) -> str:
    """Parça vektörünün öneki; parça metninin kendisine yazılmaz, yalnız vektör için eklenir."""
    year_part = f" ({year})" if year is not None else ""
    return f"Title: {title}{year_part}. Genres: {genres}. Country: {country}. "


def card_text(
    title: str,
    year: int | None,
    tagline: str,
    overview: str,
    keywords: list[str],
    genres: list[str],
    countries: list[str],
) -> str:
    """TMDB film kartı metni (kart vektörünün girdisi)."""
    year_part = str(year) if year is not None else "?"
    text = (
        f"{title} ({year_part}). {tagline or ''} {overview or ''} "
        f"Keywords: {', '.join(keywords)}. Genres: {', '.join(genres)}. "
        f"Country: {', '.join(countries)}."
    )
    return re.sub(r"\s+", " ", text).strip()
