"""pgvector araması. Her işlev (film kimlikleri, benzerlik) dizilerini azalan benzerlikle döndürür.

İki kip: `exact` kesin arama (filtre SQL'de, film başına en iyi parça SQL'de `GROUP BY` ile; indeks
kullanılmaz) ve `hnsw` (HNSW indeksi, pgvector 0.8 yinelemeli tarama, yaklaşık). Ham SQL yalnız
ORM'in ifade edemediği kısım için (`GROUP BY max(mesafe)`, yinelemeli tarama ayarları);
parametrelidir.
"""

import numpy as np
from django.conf import settings
from django.db import connection, transaction

from apps.films.models import FilmChunk
from apps.search.services.scope import FILM_ALIAS, FILM_TABLE, Scope

CHUNK_TABLE = FilmChunk._meta.db_table
VECTOR_MODES = ("exact", "hnsw")


def _vector_param(vector: np.ndarray) -> str:
    # psycopg bu bağlantıda HalfVector'ı bağlamıyor; "[x,y,...]" metni ::halfvec ile çevrilir.
    return "[" + ",".join(f"{value:.6g}" for value in vector.astype(np.float32).tolist()) + "]"


def _rows_to_arrays(rows) -> tuple[np.ndarray, np.ndarray]:
    if not rows:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float32)
    ids, scores = zip(*rows, strict=True)
    return np.array(ids, dtype=np.int64), np.array(scores, dtype=np.float32)


def _exact_settings(cursor) -> None:
    # 220 bin parçanın taranması tek işlemde ~1 sn, paralel ~0,3 sn. Değerler sabit tamsayıdır
    # (SET LOCAL parametre bağlamayı desteklemez) ve yalnız bu işlem için geçerlidir.
    cursor.execute("SET LOCAL max_parallel_workers_per_gather = 4")
    cursor.execute("SET LOCAL parallel_setup_cost = 0")
    cursor.execute("SET LOCAL parallel_tuple_cost = 0")
    cursor.execute("SET LOCAL min_parallel_table_scan_size = 0")


def _hnsw_settings(cursor) -> None:
    cursor.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
    cursor.execute(f"SET LOCAL hnsw.ef_search = {int(settings.SEARCH['hnsw_ef_search'])}")
    cursor.execute(
        f"SET LOCAL hnsw.max_scan_tuples = {int(settings.SEARCH['hnsw_max_scan_tuples'])}"
    )


def _run(sql: str, params: list, mode: str) -> tuple[np.ndarray, np.ndarray]:
    with transaction.atomic(), connection.cursor() as cursor:
        (_exact_settings if mode == "exact" else _hnsw_settings)(cursor)
        cursor.execute(sql, params)
        return _rows_to_arrays(cursor.fetchall())


def chunk_scores(vector: np.ndarray, scope: Scope, mode: str) -> tuple[np.ndarray, np.ndarray]:
    """Film başına en iyi parçanın kosinüs benzerliği; kapsamdaki, parçası olan filmler için.

    En çok `depth` film döner. İndeksli kipte yalnız en yakın `hnsw_chunk_limit` parçanın filmleri
    bulunabilir."""
    join = (
        f"JOIN {FILM_TABLE} {FILM_ALIAS} ON {FILM_ALIAS}.id = c.film_id" if scope.restricted else ""
    )
    where = f"WHERE {scope.where}" if scope.restricted else ""
    query_vector = _vector_param(vector)
    depth = int(settings.SEARCH["depth"])
    if mode == "exact":
        sql = (
            "SELECT c.film_id, max(1 - (c.embedding <=> %s::halfvec)) AS score "
            f"FROM {CHUNK_TABLE} c {join} {where} GROUP BY c.film_id ORDER BY score DESC LIMIT %s"
        )
        return _run(sql, [query_vector, *scope.params, depth], mode)
    # Yinelemeli taramada sıra gevşek olabilir; MATERIALIZED ara sonuç sonradan yeniden sıralanır.
    sql = (
        "WITH near AS MATERIALIZED (SELECT c.film_id, c.embedding <=> %s::halfvec AS distance "
        f"FROM {CHUNK_TABLE} c {join} {where} "
        "ORDER BY c.embedding <=> %s::halfvec LIMIT %s) "
        "SELECT film_id, 1 - min(distance) AS score FROM near GROUP BY film_id "
        "ORDER BY score DESC LIMIT %s"
    )
    params = [
        query_vector,
        *scope.params,
        query_vector,
        int(settings.SEARCH["hnsw_chunk_limit"]),
        depth,
    ]
    return _run(sql, params, mode)


def card_scores(vector: np.ndarray, scope: Scope, mode: str) -> tuple[np.ndarray, np.ndarray]:
    """TMDB film kartı vektörüne kosinüs benzerliği (kartı olan, kapsamdaki en çok `depth` film)."""
    extra = f"AND {scope.where}" if scope.restricted else ""
    query_vector = _vector_param(vector)
    depth = int(settings.SEARCH["depth"])
    if mode == "exact":
        # Sıralama `1 - mesafe` ifadesiyle yapıldığı için HNSW indeksi kullanılamaz: kesin arama.
        sql = (
            f"SELECT {FILM_ALIAS}.id, 1 - ({FILM_ALIAS}.card_embedding <=> %s::halfvec) AS score "
            f"FROM {FILM_TABLE} {FILM_ALIAS} WHERE {FILM_ALIAS}.card_embedding IS NOT NULL {extra} "
            "ORDER BY score DESC LIMIT %s"
        )
        return _run(sql, [query_vector, *scope.params, depth], mode)
    sql = (
        f"WITH near AS MATERIALIZED (SELECT {FILM_ALIAS}.id, "
        f"{FILM_ALIAS}.card_embedding <=> %s::halfvec AS distance "
        f"FROM {FILM_TABLE} {FILM_ALIAS} WHERE {FILM_ALIAS}.card_embedding IS NOT NULL {extra} "
        f"ORDER BY {FILM_ALIAS}.card_embedding <=> %s::halfvec LIMIT %s) "
        "SELECT id, 1 - distance FROM near ORDER BY distance"
    )
    return _run(sql, [query_vector, *scope.params, query_vector, depth], mode)
