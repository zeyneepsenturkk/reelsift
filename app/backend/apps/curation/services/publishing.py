"""Onaylı seçkiyi herkese açık siteye (reelsift-vitrin) gönderir.

Geri çekme ve güncelleme yoktur: sayfa bir kez
açılır, adresi `Collection.published_url`'de saklanır. Site anahtarı ve cevap gövdesi ne loga ne
hata mesajına yazılır.
"""

import logging
import re
import unicodedata
from urllib.parse import urlparse

import httpx2

from apps.core.exceptions import ServiceError
from apps.curation.models import Collection
from apps.curation.schemas import CollectionFilmOut, CollectionOut, QuoteSourceOut, SourceOut
from apps.curation.services.publish_config import publish_enabled, site_api_key, site_base_url
from apps.curation.services.serializers import get_owned_collection, serialize_collection

logger = logging.getLogger(__name__)

TIMEOUT_S = 15.0
MAX_URL_LENGTH = 500
# Testte sahte taşıyıcı (httpx2.MockTransport) buradan verilir; üretimde None (gerçek ağ).
TRANSPORT: httpx2.BaseTransport | None = None

# Sitenin sınırları (sözleşme); aşan değer 422 yerine gönderilmeden önce kırpılır.
MAX_TITLE = 200
MAX_DESCRIPTION = 2000
MAX_FILMS = 60
MAX_FILM_TITLE = 300
MAX_COUNTRIES, MAX_COUNTRY = 10, 60
MAX_DIRECTORS, MAX_ACTORS, MAX_PERSON = 3, 6, 120
MAX_RATIONALE = MAX_QUOTE = 2000
MAX_LABEL = 80
MAX_SOURCES = 4
MIN_YEAR, MAX_YEAR = 1870, 2100
POSTER_PATTERN = re.compile(
    r"^https://image\.tmdb\.org/t/p/[A-Za-z0-9]+/[A-Za-z0-9_-][A-Za-z0-9._-]*$"
)
POSTER_MAX_LENGTH = 300
# Satır sonu ve sekme dışındaki denetim karakterlerini site reddeder.
ALLOWED_CONTROLS = {"\n", "\r", "\t"}


def _text(value: str | None, max_length: int) -> str:
    cleaned = "".join(
        char
        for char in (value or "")
        if unicodedata.category(char) != "Cc" or char in ALLOWED_CONTROLS
    )
    return cleaned.strip()[:max_length].strip()


def _text_list(values: list[str], max_items: int, max_length: int) -> list[str]:
    cleaned = (_text(value, max_length) for value in values)
    return [value for value in cleaned if value][:max_items]


def _https_url(value: str | None) -> str | None:
    url = _text(value, MAX_URL_LENGTH)
    if not url or any(char.isspace() for char in url):
        return None
    return url if url.startswith("https://") and urlparse(url).hostname else None


def _quote_source(source: QuoteSourceOut | None) -> dict | None:
    label = _text(source.label, MAX_LABEL) if source else ""
    if source is None or not label:
        return None
    return {"kind": source.kind, "label": label, "url": _https_url(source.url)}


def _sources(sources: list[SourceOut]) -> list[dict]:
    items = []
    for source in sources:
        label, url = _text(source.label, MAX_LABEL), _https_url(source.url)
        if label and url:
            items.append({"kind": source.kind, "label": label, "url": url})
    return items[:MAX_SOURCES]


def _film_payload(film: CollectionFilmOut) -> dict:
    poster = film.poster_url
    valid_poster = poster and len(poster) <= POSTER_MAX_LENGTH and POSTER_PATTERN.match(poster)
    year_ok = film.year is not None and MIN_YEAR <= film.year <= MAX_YEAR
    return {
        "position": film.position,
        "title": _text(film.title, MAX_FILM_TITLE),
        "title_tr": _text(film.title_tr, MAX_FILM_TITLE) or None,
        "year": film.year if year_ok else None,
        "countries": _text_list(film.countries, MAX_COUNTRIES, MAX_COUNTRY),
        "directors": _text_list(film.directors, MAX_DIRECTORS, MAX_PERSON),
        "actors": _text_list(film.actors, MAX_ACTORS, MAX_PERSON),
        "poster_url": poster if valid_poster else None,
        "rationale": _text(film.rationale, MAX_RATIONALE),
        # Site `null` alıntıyı reddeder; alıntı yoksa boş metin gider.
        "source_quote": _text(film.source_quote, MAX_QUOTE),
        "quote_source": _quote_source(film.quote_source),
        "sources": _sources(film.sources),
    }


def build_payload(full: CollectionOut) -> dict:
    """Sözleşmedeki istek gövdesi; `film_id`, `vote_count`, `stats`, hazırlayan adı gönderilmez."""
    return {
        "source_id": full.id,
        "title": _text(full.title, MAX_TITLE),
        "description": _text(full.description, MAX_DESCRIPTION),
        "approved_at": (full.approved_at or full.updated_at).isoformat(),
        "films": [_film_payload(film) for film in full.films[:MAX_FILMS]],
    }


def _fail(message: str, code: str) -> ServiceError:
    return ServiceError(message, code, 502)


def _post(payload: dict) -> httpx2.Response:
    try:
        with httpx2.Client(
            timeout=TIMEOUT_S, follow_redirects=False, transport=TRANSPORT
        ) as client:
            return client.post(
                f"{site_base_url()}/api/v1/collections",
                json=payload,
                headers={"Authorization": f"Bearer {site_api_key()}"},
            )
    except (httpx2.HTTPError, httpx2.InvalidURL) as exc:
        # İstisna metni loglanmaz (adres içerebilir); yalnız sınıf adı.
        logger.warning("Site yayın isteği ulaşmadı: %s", type(exc).__name__)
        raise _fail(
            "Siteye ulaşılamadı. Bağlantını kontrol edip tekrar dene.", "publish_unreachable"
        ) from exc


def _published_url(response: httpx2.Response) -> str:
    """Başarılı cevaptaki adres; bozuk cevap `publish_failed`."""
    failed = _fail("Seçki yayınlanamadı, bir daha dener misin?", "publish_failed")
    try:
        body = response.json()
    except ValueError:
        logger.warning("Site yayın cevabı JSON değil (durum %s)", response.status_code)
        raise failed from None
    url = body.get("url") if isinstance(body, dict) else None
    valid = (
        isinstance(url, str)
        and len(url) <= MAX_URL_LENGTH
        and url.startswith(("http://", "https://"))
        and bool(urlparse(url).hostname)
        and not any(char.isspace() for char in url)
    )
    if not valid:
        logger.warning("Site yayın cevabında geçerli adres yok (durum %s)", response.status_code)
        raise failed
    return url


def publish_collection(collection: Collection, by_user) -> Collection:
    """Onaylı seçkiyi siteye gönderir; dönen sayfa adresini `published_url`'e yazar.

    Ağ isteği veritabanı transaction'ı ya da satır kilidi içinde yapılmaz: yavaş site başka
    yazmaları bekletmesin. Eşzamanlı iki yayın siteye gider ama site `source_id` ile aynı
    sayfayı döndürür (200); ikisi de aynı adresi yazar.
    """
    if collection.owner_id != by_user.pk:
        raise ServiceError("Bulunamadı.", "not_found", 404)
    current = get_owned_collection(collection.pk, by_user)
    if current.status != Collection.Status.APPROVED:
        raise ServiceError("Yalnız onaylı seçki yayınlanabilir.", "not_approved", 409)
    if not publish_enabled():
        raise ServiceError("Site yayını bu kurulumda açık değil.", "publish_disabled", 409)
    if current.published_url:
        return current

    response = _post(build_payload(serialize_collection(current)))
    if response.status_code in (200, 201):
        url = _published_url(response)
        current.published_url = url
        current.save(update_fields=["published_url", "updated_at"])
        return current

    logger.warning("Site yayını reddetti (durum %s)", response.status_code)
    if response.status_code == 401:
        raise _fail("Site anahtarı kabul etmedi. Anahtarı kontrol et.", "publish_unauthorized")
    if response.status_code == 422:
        raise _fail("Site seçkiyi kabul etmedi.", "publish_rejected")
    raise _fail("Seçki yayınlanamadı, bir daha dener misin?", "publish_failed")
