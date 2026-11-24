"""HNSW indekslerini toplu yüklemede düşürüp yeniden kurar.

İndeks tanımı her zaman modelin `Meta.indexes` nesnesinden gelir (migration'la birebir aynı kalır).
Yarıda kesilme iki katmanla kapatılır: `finally` ile geri kurma ve komut başında "eksikse kur".
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from django.conf import settings
from django.db import connection
from django.db.models import Model
from pgvector.django import HnswIndex

from apps.core.exceptions import ServiceError
from apps.films.models import Film, FilmChunk

logger = logging.getLogger(__name__)

VECTOR_MODELS = (Film, FilmChunk)

# Yükleme/üretim komutları ve indeks penceresi aynı anda tek oturumda çalışabilir.
FILMS_WRITE_LOCK_KEY = 5_241_001


@contextmanager
def films_write_lock() -> Iterator[None]:
    """Oturum düzeyinde danışma kilidi; alınamazsa beklemeden anlaşılır hata verir.

    Aynı oturum kilidi yeniden alabilir (komut kilidi tutarken indeks penceresi de ister)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [FILMS_WRITE_LOCK_KEY])
        acquired = cursor.fetchone()[0]
    if not acquired:
        raise ServiceError(
            "Başka bir yükleme ya da vektör üretimi çalışıyor; bitmesini bekleyip yeniden deneyin.",
            "films_write_locked",
            409,
        )
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [FILMS_WRITE_LOCK_KEY])


def hnsw_indexes(model: type[Model]) -> list[HnswIndex]:
    return [index for index in model._meta.indexes if isinstance(index, HnswIndex)]


def existing_index_names(model: type[Model]) -> set[str]:
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
    return {name for name, info in constraints.items() if info["index"]}


def _settle_pending_constraints() -> None:
    """Çağıran bir işlem içindeyse bekleyen FK denetimleri bitmeden indeks DDL'i çalışmaz."""
    if connection.in_atomic_block:
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def missing_indexes(model: type[Model]) -> list[HnswIndex]:
    present = existing_index_names(model)
    return [index for index in hnsw_indexes(model) if index.name not in present]


def drop_indexes(model: type[Model]) -> None:
    present = existing_index_names(model)
    _settle_pending_constraints()
    with connection.schema_editor() as editor:
        for index in hnsw_indexes(model):
            if index.name in present:
                editor.remove_index(model, index)
                logger.info("İndeks düşürüldü: %s", index.name)


def build_missing_indexes(model: type[Model]) -> None:
    missing = missing_indexes(model)
    if not missing:
        return
    _settle_pending_constraints()
    with connection.cursor() as cursor:
        cursor.execute("SHOW maintenance_work_mem")
        previous = cursor.fetchone()[0]
        cursor.execute(
            "SELECT set_config('maintenance_work_mem', %s, false)",
            [settings.FILMS_INDEX_MAINTENANCE_WORK_MEM],
        )
    try:
        with connection.schema_editor() as editor:
            for index in missing:
                logger.info("İndeks kuruluyor: %s", index.name)
                editor.add_index(model, index)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('maintenance_work_mem', %s, false)", [previous])


def ensure_vector_indexes() -> None:
    """Önceki bir yükleme yarıda kesildiyse eksik kalan indeksleri kurar."""
    for model in VECTOR_MODELS:
        build_missing_indexes(model)


def should_drop(model: type[Model], incoming_rows: int) -> bool:
    """Tablo boşsa ya da eklenecek satır sayısı eşiği aşıyorsa indeks yazımdan önce düşürülür."""
    if incoming_rows <= 0:
        return False
    return incoming_rows >= settings.FILMS_BULK_INDEX_THRESHOLD or not model.objects.exists()


@contextmanager
def bulk_write_window(model: type[Model], incoming_rows: int) -> Iterator[bool]:
    """Büyük yazımın çevresi; hata olsa da indeks geri kurulur. Düşürüldüyse True verir."""
    with films_write_lock():
        dropped = should_drop(model, incoming_rows)
        if dropped:
            drop_indexes(model)
        try:
            yield dropped
        finally:
            if dropped:
                build_missing_indexes(model)
