"""Arama hattını ısıtır: modeller ve kelime indeksi diskten yüklenir, bir kukla arama Postgres
önbelleğini ve ekran kartı çekirdeklerini hazırlar. Isıtmadan ilk arama yüzlerce saniye sürebilir.

Yükleme kilitleri (`neural`, `lexical`) tek seferliktir: ısınma sürerken gelen arama isteği aynı
yüklemeyi bekler, ikinci kopya yüklenmez.
"""

import logging
import threading
import time

from django.conf import settings
from django.db import connections

from apps.search.services import lexical, neural, pipeline
from apps.search.services.types import ParsedQuery

logger = logging.getLogger(__name__)

WARMUP_QUERY = ParsedQuery(
    en_query="A quiet drama about a family reunion in a small town.",
    hyde=(
        "After many years apart, three siblings return to their childhood home in a small town. "
        "Old arguments resurface, but a shared loss slowly brings them together again."
    ),
)


def warm_search() -> dict[str, float]:
    """Adım süreleri (sn): kelime indeksi, gömme modeli, yeniden sıralama modeli, kukla arama."""
    timings: dict[str, float] = {}
    for name, step in (
        ("index", lexical.get_index),
        ("embed_model", neural.get_embedder),
        ("rerank_model", neural.get_reranker),
        ("dummy_search", lambda: pipeline.search(WARMUP_QUERY)),
    ):
        started = time.monotonic()
        step()
        timings[name] = round(time.monotonic() - started, 1)
        logger.info("Arama ısındırma: %s %.1f sn", name, timings[name])
    return timings


def _run_background() -> None:
    started = time.monotonic()
    try:
        warm_search()
    except Exception:  # sunucu ısınma hatasıyla düşmemeli; arama ilk istekte kendisi yükler
        logger.exception("Arama ısındırması başarısız; ilk arama soğuk başlayacak")
    else:
        logger.info("Arama hazır (%.1f sn)", time.monotonic() - started)
    finally:
        connections.close_all()  # bu iş parçacığının veritabanı bağlantısı


def start_background_warmup() -> threading.Thread:
    thread = threading.Thread(target=_run_background, name="search-warmup", daemon=True)
    thread.start()
    return thread


def maybe_start_warmup() -> threading.Thread | None:
    """`SEARCH["warmup"]` açıksa ısındırmayı arka planda başlatır; sunucu açılışını bloklamaz."""
    if not settings.SEARCH["warmup"]:
        return None
    return start_background_warmup()
