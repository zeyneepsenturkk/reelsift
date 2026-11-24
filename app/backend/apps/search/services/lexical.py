"""Kelime araması (BM25) ve ad eşleme indeksi.

İki BM25 indeksi: A yalnız hikâye metni, B hikâye + ad + TMDB özeti + anahtar kelimeler. Ad eşleme
indeksi `title`, `original_title` ve `tr_title` adlarını anahtar olarak kullanır; kişi dizini
(`people`) yönetmen ve oyuncu adlarından kurulur. Hepsi veritabanındaki metinlerden kurulur,
`index_dir` altına kaydedilir; süreç ilk kullanımda diskten yükler, dosya yoksa kurar. Film sayısı
indeks kurulduğundan beri değiştiyse eski olduğu loglanır.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from django.conf import settings
from django.db import reset_queries

from apps.films.models import Film
from apps.search.services import people as person_dir
from apps.search.services.text import TitleIndex, build_title_index, normalize_title

logger = logging.getLogger(__name__)

INDEX_NAMES = ("a", "b")
_BATCH = 2000

_lock = threading.Lock()  # `_loaded` değişkenini korur
_load_lock = threading.Lock()  # yükleme/kurma tek seferde
_loaded: "LexicalIndex | None" = None


@dataclass
class LexicalIndex:
    film_ids: np.ndarray  # indeks sırasındaki Film.pk değerleri
    retrievers: dict
    titles: TitleIndex
    film_count: int
    people: person_dir.PersonIndex = field(default_factory=person_dir.PersonIndex)

    def scores(self, name: str, query: str) -> np.ndarray:
        """Her indeks belgesi için BM25 puanı (film_ids sırasında)."""
        tokens = _tokenize(query)
        if not tokens:
            return np.zeros(len(self.film_ids), dtype=np.float32)
        return self.retrievers[name].get_scores(tokens)


def index_path() -> Path:
    return Path(settings.SEARCH["index_dir"]) / "lexical"


def _stemmer():
    import Stemmer

    return Stemmer.Stemmer("english")


def _tokenize(query: str) -> list[str]:
    import bm25s

    return bm25s.tokenize(
        query, stopwords="en", stemmer=_stemmer(), return_ids=False, show_progress=False
    )[0]


def _documents(name: str):
    """İndeks sırasında (film_id, belge metni). Büyük metinler `iterator()` ile akıtılır."""
    queryset = Film.objects.order_by("pk")
    if name == "a":
        rows = queryset.values_list("pk", "plot").iterator(chunk_size=_BATCH)
        for film_id, plot in rows:
            yield film_id, plot
    else:
        rows = queryset.values_list("pk", "plot", "title", "overview", "keywords").iterator(
            chunk_size=_BATCH
        )
        for film_id, plot, title, overview, keywords in rows:
            yield film_id, f"{plot} {title} {overview} {' '.join(keywords)}"


def _title_rows() -> list[tuple[int, str, int | None]]:
    """Ad önerisi eşleme satırları: `title`, ayrıca `original_title` ve `tr_title` (normalleşmiş
    hâli ad satırından farklıysa). Model özgün ya da Türkçe adı önerebilir ("Kader")."""
    rows = []
    queryset = Film.objects.order_by("pk").values_list(
        "pk", "title", "original_title", "tr_title", "year"
    )
    for count, (film_id, title, original_title, tr_title, year) in enumerate(
        queryset.iterator(chunk_size=_BATCH), start=1
    ):
        rows.append((film_id, title, year))
        seen = {normalize_title(title)}
        for extra in (original_title, tr_title):
            key = normalize_title(extra) if extra else ""
            if key and key not in seen:
                seen.add(key)
                rows.append((film_id, extra, year))
        if count % 10000 == 0:
            reset_queries()
    return rows


def _person_index() -> person_dir.PersonIndex:
    queryset = Film.objects.order_by("pk").values_list("pk", "directors", "actors")
    rows = queryset.iterator(chunk_size=_BATCH)
    return person_dir.build_person_index(rows, settings.SEARCH["person_max_directors"])


def _build_retriever(name: str) -> tuple[np.ndarray, object]:
    import bm25s

    film_ids: list[int] = []
    documents: list[str] = []
    for count, (film_id, document) in enumerate(_documents(name), start=1):
        film_ids.append(film_id)
        documents.append(document)
        if count % 10000 == 0:
            reset_queries()  # DEBUG açıkken sorgu günlüğü büyük metinlerle belleği doldurur
    tokens = bm25s.tokenize(documents, stopwords="en", stemmer=_stemmer(), show_progress=False)
    del documents
    retriever = bm25s.BM25()
    retriever.index(tokens, show_progress=False)
    return np.array(film_ids, dtype=np.int64), retriever


def build_index() -> dict:
    """İndeksi sıfırdan kurar ve diske yazar; çalışan süreçte bellekteki kopya da yenilenir."""
    global _loaded
    started = time.monotonic()
    target = index_path()
    target.mkdir(parents=True, exist_ok=True)
    seconds: dict[str, float] = {}
    film_ids = None
    for name in INDEX_NAMES:
        step = time.monotonic()
        ids, retriever = _build_retriever(name)
        if film_ids is not None and not np.array_equal(film_ids, ids):
            raise RuntimeError("Film listesi indeks kurulurken değişti; komutu yeniden çalıştırın.")
        film_ids = ids
        retriever.save(str(target / name))
        seconds[name] = round(time.monotonic() - step, 1)
        logger.info("BM25 indeksi %s kuruldu: %s belge", name, len(ids))
    step = time.monotonic()
    titles = _title_rows()
    np.save(target / "film_ids.npy", film_ids)
    (target / "titles.json").write_text(json.dumps(titles), encoding="utf-8")
    seconds["adlar"] = round(time.monotonic() - step, 1)
    step = time.monotonic()
    person_dir.save_person_index(_person_index(), target)
    seconds["kisiler"] = round(time.monotonic() - step, 1)
    meta = {"film_count": len(film_ids), "built_at": time.time()}
    (target / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    with _lock:
        _loaded = None
    seconds["toplam"] = round(time.monotonic() - started, 1)
    return {"film_count": len(film_ids), "seconds": seconds}


def _load_from_disk() -> LexicalIndex:
    import bm25s

    target = index_path()
    meta = json.loads((target / "meta.json").read_text(encoding="utf-8"))
    titles = json.loads((target / "titles.json").read_text(encoding="utf-8"))
    return LexicalIndex(
        film_ids=np.load(target / "film_ids.npy"),
        retrievers={name: bm25s.BM25.load(str(target / name)) for name in INDEX_NAMES},
        titles=build_title_index(titles),
        film_count=meta["film_count"],
        people=person_dir.load_person_index(target),
    )


def index_exists() -> bool:
    # Kişi dizini sonradan eklendi: onsuz kurulmuş eski indeks "yok" sayılır ve yeniden kurulur.
    return (index_path() / "meta.json").exists() and person_dir.person_index_exists(index_path())


def _warn_if_stale(loaded: LexicalIndex) -> None:
    current = Film.objects.count()
    if current != loaded.film_count:
        logger.warning(
            "Kelime araması indeksi eski: indekste %s film var, veritabanında %s. "
            "`manage.py build_search_index` ile yeniden kurun.",
            loaded.film_count,
            current,
        )


def get_index() -> LexicalIndex:
    """İlk çağrıda diskten yükler (yoksa kurar); sonraki çağrılar bellekteki kopyayı döndürür.

    Yükleme ve kurma `_load_lock` altında tek seferdir: eşzamanlı ilk istekler indeksi iki kez
    yüklemez (bellek ikiye katlanmaz), indeks yoksa aynı klasöre iki kez yazılmaz."""
    global _loaded
    loaded = _loaded
    if loaded is not None:
        return loaded  # hazırsa kilitsiz hızlı yol
    with _load_lock:
        if _loaded is not None:
            return _loaded
        if not index_exists():
            logger.warning("Kelime araması indeksi yok; kuruluyor (birkaç dakika sürer).")
            build_index()
        started = time.monotonic()
        loaded = _load_from_disk()
        _warn_if_stale(loaded)
        logger.info("Kelime araması indeksi yüklendi (%.1f sn)", time.monotonic() - started)
        with _lock:
            _loaded = loaded
        return loaded


def reset_loaded() -> None:
    """Testler ve yeniden kurma için bellekteki indeksi bırakır."""
    global _loaded
    with _lock:
        _loaded = None
