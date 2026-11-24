"""Arşiv dosyalarını okuyan katman. Dosyalar salt okunur `/data` altındadır; hepsi akışla okunur."""

import csv
import json
import logging
import pickle
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from apps.core.exceptions import ServiceError

logger = logging.getLogger(__name__)

DEFAULT_DATA_ROOT = Path("/data")

RAW_WIKIDATA_ID = re.compile(r"^Q\d+$")

DATASET_CSV = "dataset/final_dataset.csv"
DATASET_IDS_NPY = "vektor/hazir/final_dense_movie_ids.npy"
TMDB_JSONL = "tmdb/movies.jsonl"
EXTRA_FILMS_JSONL = "arsiv-ek/eksik_filmler.jsonl"
PLOT_RENEWALS_JSONL = "arsiv-ek/plot_yenileme.jsonl"
REVIEWS_JSONL = "arsiv-ek/incelemeler.jsonl"
CREDITS_JSONL = "arsiv-ek/kunye.jsonl"
PROFILES_JSONL = "profil/profiller_birlesik.jsonl"
# Türk filmleri için isteğe bağlı ikinci dosyalar; yoksa atlanır.
TURKISH_FILMS_JSONL = "arsiv-ek/turk/turk_filmler.jsonl"
TURKISH_CREDITS_JSONL = "arsiv-ek/turk/turk_kunye.jsonl"
TURKISH_PROFILES_JSONL = "profil/turk/profiller_turk.jsonl"
TURKISH_REVIEWS_JSONL = "arsiv-ek/turk/turk_incelemeler.jsonl"
CHUNK_TEXTS_PKL = "vektor/chunk/chunks.pkl"
CHUNK_VECTOR_FILES = "vektor/chunk-onekli/chunk_{n}.npy"
CHUNK_VECTOR_FILE_COUNT = 8
CARD_VECTORS_NPY = "vektor/tmdb-kart/cards.npy"

# Hikâye alanları (yazar listesi gibi) çok uzun olabilir; csv'nin varsayılan sınırı yetmez.
csv.field_size_limit(10**8)

# TMDB satırından yalnız kullanılan alanlar tutulur; 87 bin kaydın bellek yükü küçülür.
TMDB_KEPT_FIELDS = (
    "tmdb_id",
    "imdb_id",
    "title",
    "original_title",
    "original_language",
    "overview",
    "tagline",
    "genres",
    "keywords",
    "release_date",
    "runtime",
    "popularity",
    "vote_average",
    "vote_count",
    "poster_path",
    "backdrop_path",
    "tr_title",
    "tr_overview",
)


@dataclass
class TmdbIndex:
    by_wikidata_id: dict[str, dict] = field(default_factory=dict)
    by_tmdb_id: dict[int, dict] = field(default_factory=dict)
    record_count: int = 0


def _require_file(root: Path, relative: str) -> Path:
    path = Path(root) / relative
    if not path.is_file():
        raise ServiceError(f"Kaynak dosya bulunamadı: {relative}", "source_file_missing", 500)
    return path


def iter_jsonl(root: Path, relative: str) -> Iterator[dict]:
    path = _require_file(root, relative)
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ServiceError(
                    f"Geçersiz JSON satırı: {relative}:{line_number}", "source_file_invalid", 500
                ) from exc


def iter_dataset_rows(root: Path, limit: int | None = None) -> Iterator[dict]:
    path = _require_file(root, DATASET_CSV)
    with open(path, encoding="utf-8", newline="") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            if limit is not None and index >= limit:
                return
            yield row


def read_dataset_rows_by_id(root: Path, wikidata_ids: set[str]) -> dict[str, dict]:
    """Verilen kimliklerin veri seti satırları; hepsi bulununca okumayı bırakır."""
    found: dict[str, dict] = {}
    if not wikidata_ids:
        return found
    for row in iter_dataset_rows(root):
        if row["movie_id"] in wikidata_ids:
            found[row["movie_id"]] = row
            if len(found) == len(wikidata_ids):
                break
    return found


def load_tmdb_index(root: Path) -> TmdbIndex:
    index = TmdbIndex()
    for record in iter_jsonl(root, TMDB_JSONL):
        index.record_count += 1
        kept = {name: record.get(name) for name in TMDB_KEPT_FIELDS}
        kept["countries"] = [c["name"] for c in record.get("production_countries") or []]
        index.by_tmdb_id[int(record["tmdb_id"])] = kept
        # Bazı TMDB kayıtları birden çok Wikidata kimliğine bağlıdır (liste); ilk kayıt kazanır.
        raw_ids = record.get("movie_id")
        for wikidata_id in raw_ids if isinstance(raw_ids, list) else [raw_ids]:
            if wikidata_id:
                index.by_wikidata_id.setdefault(wikidata_id, kept)
    return index


def load_plot_renewals(root: Path) -> dict[str, str]:
    return {row["movie_id"]: row["yeni_plot"] for row in iter_jsonl(root, PLOT_RENEWALS_JSONL)}


def iter_optional_jsonl(root: Path, relative: str) -> Iterator[dict]:
    """İkinci dosya yoksa atlanır (bilgi logu)."""
    if not (Path(root) / relative).is_file():
        logger.info("İsteğe bağlı kaynak dosya yok, atlandı: %s", relative)
        return
    yield from iter_jsonl(root, relative)


def iter_extra_films(root: Path) -> Iterator[dict]:
    yield from iter_jsonl(root, EXTRA_FILMS_JSONL)
    yield from iter_optional_jsonl(root, TURKISH_FILMS_JSONL)


def _iter_with_second_file(root: Path, first: str, second: str, key: str) -> Iterator[dict]:
    """İki dosyayı sırayla verir; ikinci dosyada birinciyle aynı kimlik varsa birinci kazanır."""
    first_ids = set()
    for record in iter_jsonl(root, first):
        first_ids.add(record[key])
        yield record
    skipped = 0
    for record in iter_optional_jsonl(root, second):
        if record[key] in first_ids:
            skipped += 1
            continue
        yield record
    if skipped:
        logger.warning("İkinci dosyada birinci dosyayla aynı kimlik (%s): %s", second, skipped)


def iter_reviews(root: Path) -> Iterator[dict]:
    return _iter_with_second_file(root, REVIEWS_JSONL, TURKISH_REVIEWS_JSONL, "movie_id")


def iter_profiles(root: Path) -> Iterator[dict]:
    return _iter_with_second_file(root, PROFILES_JSONL, TURKISH_PROFILES_JSONL, "id")


@dataclass
class CreditsIndex:
    """Künye dosyası: wikidata_id -> {"directors": [...], "actors": [...]}."""

    by_wikidata_id: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    matched: set[str] = field(default_factory=set)
    invalid_rows: int = 0
    duplicate_rows: int = 0
    file_missing: bool = False


def drop_raw_ids(names: list[str]) -> list[str]:
    """Çözülmemiş ham Wikidata kimliği olan adları ("Q3325924") atar; boş adları da temizler."""
    stripped = (name.strip() for name in names)
    return [name for name in stripped if name and not RAW_WIKIDATA_ID.match(name)]


def _credits_names(value) -> list[str] | None:
    """Ad listesi; liste değilse ya da içinde metin olmayan öğe varsa None (satır bozuk sayılır)."""
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        return None
    return drop_raw_ids(value)


def load_credits(root: Path) -> CreditsIndex:
    """Künye dosyası isteğe bağlıdır: yoksa boş indeks döner. Bozuk satır sayılır, durmaz.

    Türk filmleri için ikinci dosya da okunur; aynı kimlik iki dosyada varsa birincisi kazanır."""
    index = CreditsIndex()
    path = Path(root) / CREDITS_JSONL
    if not path.is_file():
        index.file_missing = True
        logger.warning(
            "Künye dosyası bulunamadı (%s): künye uygulanmadı; bu yükleme, daha önce künyeden "
            "doldurulmuş yönetmen/oyuncu alanlarını boşaltır.",
            CREDITS_JSONL,
        )
    else:
        _read_credits_file(index, path, CREDITS_JSONL)
    turkish_path = Path(root) / TURKISH_CREDITS_JSONL
    if turkish_path.is_file():
        _read_credits_file(index, turkish_path, TURKISH_CREDITS_JSONL)
    else:
        logger.info("İsteğe bağlı kaynak dosya yok, atlandı: %s", TURKISH_CREDITS_JSONL)
    return index


def _read_credits_file(index: CreditsIndex, path: Path, relative: str) -> None:
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                record = None
            wikidata_id = record.get("wikidata_id") if isinstance(record, dict) else None
            directors = _credits_names(record.get("directors")) if wikidata_id else None
            actors = _credits_names(record.get("actors")) if wikidata_id else None
            if not isinstance(wikidata_id, str) or directors is None or actors is None:
                index.invalid_rows += 1
                logger.warning("Künye satırı bozuk: %s:%s", relative, line_number)
                continue
            if wikidata_id in index.by_wikidata_id:
                index.duplicate_rows += 1
                continue
            index.by_wikidata_id[wikidata_id] = {"directors": directors, "actors": actors}


def load_dataset_ids_alignment(root: Path) -> list[str]:
    """Vektör dosyalarının hazırlandığı film sırası (veri seti satır sırasıyla aynı olmalı)."""
    path = _require_file(root, DATASET_IDS_NPY)
    # allow_pickle: dosya kendi ürettiğimiz salt okunur yerel veridir; dışarıdan pickle okunmaz.
    return [str(value) for value in np.load(path, allow_pickle=True)]


def load_chunk_texts(root: Path) -> tuple[np.ndarray, list[str]]:
    """(her parçanın film satır sırası, parça metinleri); iki dizi aynı uzunlukta olmalıdır."""
    path = _require_file(root, CHUNK_TEXTS_PKL)
    # Güven sınırı: bu pickle kendi ürettiğimiz, salt okunur yerel veridir; dış kaynaktan okunmaz.
    with open(path, "rb") as handle:
        film_rows, texts = pickle.load(handle)
    if len(film_rows) != len(texts):
        raise ServiceError(
            "Parça kimlik listesi ile parça metinleri aynı uzunlukta değil.",
            "chunk_misaligned",
            500,
        )
    return np.asarray(film_rows), texts


class ChunkVectors:
    """Parça vektörleri: 8 npy dosyası mmap ile açılır, yalnız istenen aralık belleğe alınır."""

    def __init__(self, parts: list[np.ndarray]):
        self.parts = parts
        self.offsets = np.cumsum([0] + [len(part) for part in parts])
        self.total = int(self.offsets[-1])

    def read(self, start: int, stop: int) -> np.ndarray:
        pieces = []
        for part, begin, end in zip(self.parts, self.offsets[:-1], self.offsets[1:], strict=True):
            low, high = max(start, begin), min(stop, end)
            if low < high:
                pieces.append(part[low - begin : high - begin])
        return np.concatenate(pieces) if pieces else np.empty((0, 0), dtype=np.float16)


def open_chunk_vectors(root: Path) -> ChunkVectors:
    parts = [
        np.load(_require_file(root, CHUNK_VECTOR_FILES.format(n=n)), mmap_mode="r")
        for n in range(CHUNK_VECTOR_FILE_COUNT)
    ]
    return ChunkVectors(parts)


def open_card_vectors(root: Path) -> np.ndarray:
    return np.load(_require_file(root, CARD_VECTORS_NPY), mmap_mode="r")
