"""Kaynak alıntısı doğrulaması: alıntı filmin kaynak metninde birebir geçmeli."""

import re
import unicodedata

from apps.core.exceptions import ServiceError
from apps.curation.models import CollectionFilm
from apps.curation.services.sources import tmdb_url

MIN_QUOTE_LENGTH = 20
MAX_QUOTE_LENGTH = 700

_QUOTE_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
        "…": "...",
        # Modele giden kaynak metinde etiket kalıpları `<` yerine `‹` ile etkisizleştirilir
        # (agent/services/data.py); model onu `<` ile alıntılarsa da eşleşsin.
        "‹": "<",
    }
)
_WHITESPACE = re.compile(r"\s+")


class QuoteVerificationError(ServiceError):
    def __init__(self, reason: str):
        super().__init__(reason, "quote_unverified", 422)


def normalize(text: str) -> str:
    """Boşluk ve tırnak/tire türü farkları sayılmaz; harf ve noktalama birebir kalır."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_TRANSLATION)
    return _WHITESPACE.sub(" ", text).strip()


def check_quote(film, kind: str, quote: str) -> str:
    """Alıntı kaynakta birebir geçiyorsa kaynak adresini döndürür, geçmiyorsa hata fırlatır.

    `film.reviews` önceden getirilmiş olmalı (liste başına tek sorgu için).
    """
    needle = normalize(quote)
    if len(needle) < MIN_QUOTE_LENGTH:
        raise QuoteVerificationError("Alıntı çok kısa.")
    if len(needle) > MAX_QUOTE_LENGTH:
        raise QuoteVerificationError("Alıntı çok uzun.")

    if kind == CollectionFilm.SourceKind.PLOT:
        if needle in normalize(film.plot):
            return film.wikipedia_url
    elif kind == CollectionFilm.SourceKind.OVERVIEW:
        # Hikâyesiz Türk filmlerinde ajana Türkçe özet de kaynak olarak gider.
        if needle in normalize(film.overview) or needle in normalize(film.tr_overview):
            return tmdb_url(film)
    elif kind == CollectionFilm.SourceKind.REVIEW:
        for review in film.reviews.all():
            if needle in normalize(review.content):
                return review.url
    else:
        raise QuoteVerificationError("Bilinmeyen kaynak türü.")
    raise QuoteVerificationError("Alıntı belirtilen kaynak metninde birebir geçmiyor.")
