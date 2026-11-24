"""Arşivi veritabanına yükler. Her adım tekrar çalıştırılabilir: kayıt güncellenir, çoğalmaz."""

import hashlib
import logging
import resource
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from django.db import reset_queries, transaction
from django.db.models.functions import MD5
from django.utils import timezone

from apps.core.exceptions import ServiceError
from apps.films.models import Film, FilmChunk, FilmProfile, FilmReview, Mood
from apps.films.services import film_records, sources
from apps.films.services.recipes import chunk_text
from apps.films.services.vector_indexes import (
    bulk_write_window,
    ensure_vector_indexes,
    films_write_lock,
)

logger = logging.getLogger(__name__)

FILM_BATCH = 1000
CHUNK_BATCH = 500
CARD_BATCH = 500
PROFILE_BATCH = 1000
REVIEW_BATCH = 1000
LOG_EVERY_BATCHES = 20

# Yeniden yükleme, vektörleri (kart vektörü `embed_missing` ile de üretilir) ezmemelidir.
_FILM_PRESERVED_FIELDS = {"id", "created_at", "wikidata_id", "card_embedding"}
FILM_UPDATE_FIELDS = [
    f.name for f in Film._meta.concrete_fields if f.name not in _FILM_PRESERVED_FIELDS
]

_MOOD_VALUES = set(Mood.values)


@dataclass
class LoadSummary:
    dataset_films: int = 0
    extra_films: int = 0
    renewed_films: int = 0
    chunks: int = 0
    card_vectors: int = 0
    profiles: int = 0
    dropped_moods: int = 0
    reviews: int = 0
    review_films: int = 0
    merged_extras: int = 0
    merged_extra_ids: set[str] = field(default_factory=set)
    credits_films: int = 0
    credits_written: int = 0
    credits_film_ids: set[str] = field(default_factory=set)
    credits_file_missing: bool = False
    credits_already_filled: int = 0
    credits_unmatched: int = 0
    unmatched_extras: list[str] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    seconds: dict[str, float] = field(default_factory=dict)

    def describe(self) -> str:
        skipped = ", ".join(f"{reason}={count}" for reason, count in sorted(self.skipped.items()))
        line = (
            f"Yükleme özeti: film={self.dataset_films + self.extra_films} "
            f"(veri seti={self.dataset_films}, ek={self.extra_films}, "
            f"hikâyesi yenilenen={self.renewed_films}, arşiv filmine işlenen ek kayıt="
            f"{self.merged_extras}), parça={self.chunks}, "
            f"kart vektörü={self.card_vectors}, profil={self.profiles} "
            f"(atılan ton değeri={self.dropped_moods}), "
            f"inceleme={self.reviews} ({self.review_films} film), "
            f"künye (künyeli film={self.credits_films}, "
            f"bu koşuda künye yüzünden yazılan={self.credits_written}, "
            f"zaten dolu={self.credits_already_filled}, eşleşmeyen={self.credits_unmatched}"
            f"{', künye dosyası bulunamadı' if self.credits_file_missing else ''}); "
            f"atlananlar: {skipped or 'yok'}"
        )
        return line


def _film_id_map(wikidata_ids: set[str]) -> dict[str, int]:
    """Yalnız kapsamdaki filmlerin (wikidata_id -> pk) eşlemesi."""
    return {
        wikidata_id: pk
        for wikidata_id, pk in Film.objects.values_list("wikidata_id", "pk").iterator()
        if wikidata_id in wikidata_ids
    }


_FILM_COMPARE_FIELDS = [name for name in FILM_UPDATE_FIELDS if name != "updated_at"]
# Uzun metinler belleğe alınmaz; veritabanında MD5 özetiyle karşılaştırılır.
_HASHED_FIELDS = {"plot", "overview", "tr_overview", "tagline"}
_PLOT_POSITION = _FILM_COMPARE_FIELDS.index("plot")
_CREDITS_POSITIONS = [_FILM_COMPARE_FIELDS.index("directors"), _FILM_COMPARE_FIELDS.index("actors")]


def _stored_film_values() -> dict[str, tuple]:
    expressions = [MD5(name) if name in _HASHED_FIELDS else name for name in _FILM_COMPARE_FIELDS]
    return {
        row[0]: row[1:]
        for row in Film.objects.values_list("wikidata_id", *expressions).iterator(chunk_size=2000)
    }


def _film_values(film: Film) -> tuple:
    return tuple(
        hashlib.md5(getattr(film, name).encode("utf-8")).hexdigest()
        if name in _HASHED_FIELDS
        else getattr(film, name)
        for name in _FILM_COMPARE_FIELDS
    )


def _upsert_films(batch: list[Film], stored: dict[str, tuple], summary: LoadSummary) -> None:
    # Değişmemiş film yazılmaz: kart vektörü indeksli satırın her güncellemesi HNSW indeksine yeni
    # girdi ekler (yeniden yükleme dakikalarca sürer ve indeks şişer).
    changed: list[Film] = []
    stale_plot_ids: list[str] = []
    for film in batch:
        values = _film_values(film)
        before = stored.get(film.wikidata_id)
        if before == values:
            continue
        changed.append(film)
        if film.wikidata_id in summary.credits_film_ids and (
            before is None or any(before[i] != values[i] for i in _CREDITS_POSITIONS)
        ):
            summary.credits_written += 1
        if before is not None and before[_PLOT_POSITION] != values[_PLOT_POSITION]:
            stale_plot_ids.append(film.wikidata_id)
    summary.skipped["film_zaten_guncel"] += len(batch) - len(changed)
    if not changed:
        return
    with transaction.atomic():
        Film.objects.bulk_create(
            changed,
            batch_size=FILM_BATCH,
            update_conflicts=True,
            unique_fields=["wikidata_id"],
            update_fields=FILM_UPDATE_FIELDS,
        )
        # Hikâyesi değişen filmin eski parçaları bayattır; vektör dosyasından ya da embed_missing
        # ile yeniden oluşur.
        if stale_plot_ids:
            deleted, _ = FilmChunk.objects.filter(film__wikidata_id__in=stale_plot_ids).delete()
            summary.skipped["bayat_parca_silindi"] += deleted


@dataclass
class DatasetIdentifiers:
    ids: set[str] = field(default_factory=set)
    by_imdb: dict[str, list[str]] = field(default_factory=dict)
    by_tmdb: dict[int, list[str]] = field(default_factory=dict)


def index_dataset_identifiers(root: Path) -> DatasetIdentifiers:
    identifiers = DatasetIdentifiers()
    for row in sources.iter_dataset_rows(root):
        wikidata_id = row["movie_id"]
        identifiers.ids.add(wikidata_id)
        if row["imdb_id"]:
            identifiers.by_imdb.setdefault(row["imdb_id"], []).append(wikidata_id)
        tmdb_id = film_records.parse_int(row["tmdb_id"])
        if tmdb_id is not None:
            identifiers.by_tmdb.setdefault(tmdb_id, []).append(wikidata_id)
    return identifiers


def match_archive_film(extra: dict, identifiers: DatasetIdentifiers) -> str | None:
    """Ek kaydın arşivdeki TEK ve kesin karşılığı: aynı Wikidata kimliği, yoksa tekil `imdb_id`,
    yoksa tekil `tmdb_id`. Başlık benzerliğiyle eşleme yapılmaz."""
    wikidata_id = film_records.extra_wikidata_id(extra)
    if wikidata_id in identifiers.ids:
        return wikidata_id
    for candidates in (
        identifiers.by_imdb.get(extra.get("imdb_id") or ""),
        identifiers.by_tmdb.get(extra.get("tmdb_id")),
    ):
        if candidates and len(candidates) == 1:
            return candidates[0]
    return None


@dataclass
class ExtraPlan:
    new: list[dict] = field(default_factory=list)
    merged: dict[str, dict] = field(default_factory=dict)  # arşiv film kimliği -> ek kayıt
    aliases: dict[str, str] = field(default_factory=dict)  # ek kayıt kimliği -> arşiv film kimliği


def plan_extra_films(
    root: Path, identifiers: DatasetIdentifiers, summary: LoadSummary
) -> ExtraPlan:
    """Ek kayıtları ayırır: yeni film / arşivdeki filme işlenecek / eşleşmeyen (listelenir)."""
    plan = ExtraPlan()
    seen: set[str] = set()
    for extra in sources.iter_extra_films(root):
        wikidata_id = film_records.extra_wikidata_id(extra)
        target = match_archive_film(extra, identifiers)
        if target:
            if target in plan.merged:
                summary.skipped["ek_film_ayni_filme_ikinci_kayit"] += 1
                continue
            plan.merged[target] = extra
            if wikidata_id != target:
                plan.aliases[wikidata_id] = target
            continue
        if extra.get("in_archive_by_id"):
            summary.skipped["ek_film_eslesmedi"] += 1
            summary.unmatched_extras.append(f"{wikidata_id} {extra['title']}")
            continue
        if wikidata_id in seen:
            summary.skipped["ek_film_yinelenen_id"] += 1
            continue
        seen.add(wikidata_id)
        plan.new.append(extra)
    return plan


def _build_film(record: dict, credits: sources.CreditsIndex | None, summary: LoadSummary) -> Film:
    # Künye kayıt kurulurken uygulanır: karşılaştırma ve yazma künyeli hâli görür, böylece
    # ikinci koşuda film "zaten güncel" sayılır ve (kart vektörü dahil) yeniden yazılmaz.
    outcome = film_records.apply_credits(record, credits)
    if outcome == "applied":
        summary.credits_films += 1
        summary.credits_film_ids.add(record["wikidata_id"])
    elif outcome == "already_filled":
        summary.credits_already_filled += 1
    return Film(**record)


def report_unmatched_credits(credits: sources.CreditsIndex, summary: LoadSummary) -> None:
    """Hiçbir filme bağlanmayan künye satırlarını sayar ve loglar (tahminle eşleme yok)."""
    summary.skipped["kunye_bozuk_satir"] += credits.invalid_rows
    summary.skipped["kunye_yinelenen_satir"] += credits.duplicate_rows
    unmatched = sorted(set(credits.by_wikidata_id) - credits.matched)
    summary.credits_unmatched = len(unmatched)
    if unmatched:
        logger.warning(
            "Künye satırı filmle eşleşmedi (%s): %s", len(unmatched), ", ".join(unmatched[:20])
        )


def load_dataset_films(
    root: Path,
    tmdb_index: sources.TmdbIndex,
    renewals: dict[str, str],
    limit: int | None,
    summary: LoadSummary,
    merged_extras: dict[str, dict] | None = None,
    credits: sources.CreditsIndex | None = None,
) -> list[str]:
    """Veri seti filmleri; satır sırasıyla film kimliklerini döner.

    `merged_extras`: TMDB kaydı olmayan arşiv filmine, eşleşen ek kaydın TMDB alanları işlenir."""
    merged_extras = merged_extras or {}
    dataset_ids: list[str] = []
    used_tmdb_ids: set[int] = set()
    seen: set[str] = set()
    batch: list[Film] = []
    stored = _stored_film_values()

    for row in sources.iter_dataset_rows(root, limit):
        wikidata_id = row["movie_id"]
        # Vektör dosyaları satır sırasına bağlı; boş/yinelenen satır da listede yer tutar.
        dataset_ids.append(wikidata_id)
        csv_tmdb_id = film_records.parse_int(row["tmdb_id"])
        if not wikidata_id:
            summary.skipped["dataset_wikidata_id_bos"] += 1
            continue
        if wikidata_id in seen:
            summary.skipped["dataset_yinelenen_wikidata_id"] += 1
            continue
        seen.add(wikidata_id)

        tmdb = tmdb_index.by_wikidata_id.get(wikidata_id) or tmdb_index.by_tmdb_id.get(csv_tmdb_id)
        if tmdb:
            used_tmdb_ids.add(tmdb["tmdb_id"])
        elif wikidata_id in merged_extras:
            tmdb = film_records.extra_as_tmdb(merged_extras[wikidata_id])
            summary.merged_extras += 1
            summary.merged_extra_ids.add(wikidata_id)
        renewed_plot = renewals.get(wikidata_id)
        if renewed_plot:
            summary.renewed_films += 1
        record = film_records.build_dataset_film(row, tmdb, renewed_plot)
        batch.append(_build_film(record, credits, summary))
        if len(batch) >= FILM_BATCH:
            _upsert_films(batch, stored, summary)
            summary.dataset_films += len(batch)
            batch = []
            if (summary.dataset_films // FILM_BATCH) % LOG_EVERY_BATCHES == 0:
                logger.info("Veri seti filmleri: %s", summary.dataset_films)
    if batch:
        _upsert_films(batch, stored, summary)
        summary.dataset_films += len(batch)

    if limit is None:
        # Tam yüklemede TMDB'de olup hiçbir veri seti filmine bağlanmayan kayıt veri hatasıdır.
        unmatched = tmdb_index.record_count - len(used_tmdb_ids)
        if unmatched:
            summary.skipped["tmdb_kaydi_eslesmedi"] += unmatched
    return dataset_ids


def load_extra_films(
    plan: ExtraPlan, summary: LoadSummary, credits: sources.CreditsIndex | None = None
) -> list[str]:
    """Arşivde karşılığı olmayan ek filmler; yazılan film kimliklerini döner."""
    batch = [
        _build_film(film_records.build_extra_film(extra), credits, summary) for extra in plan.new
    ]
    if batch:
        _upsert_films(batch, _stored_film_values(), summary)
        summary.extra_films += len(batch)
    return [film.wikidata_id for film in batch]


def verify_chunk_alignment(
    root: Path, film_rows, texts: list[str], dataset_ids: list[str], skip_ids: set[str]
) -> None:
    """Parça metinleri, filmin hikâyesinin bugünkü parçalamasıyla birebir aynı olmalıdır."""
    starts: dict[int, int] = {}
    ends: dict[int, int] = {}
    for position, film_row in enumerate(film_rows.tolist()):
        starts.setdefault(film_row, position)
        ends[film_row] = position + 1
    for row, dataset_row in enumerate(sources.iter_dataset_rows(root, len(dataset_ids))):
        if dataset_row["movie_id"] in skip_ids:
            continue
        if row not in starts or chunk_text(dataset_row["plot"]) != texts[starts[row] : ends[row]]:
            raise ServiceError(
                f"Parça metinleri hikâye ile uyuşmuyor: {dataset_row['movie_id']} (satır {row}).",
                "chunk_misaligned",
                500,
            )


def _write_chunks(
    batch: list[FilmChunk], rows: list[int], vectors: sources.ChunkVectors, summary: LoadSummary
) -> None:
    # Parti içindeki satırlar neredeyse bitişik olduğu için tek aralık okunur.
    low = rows[0]
    block = vectors.read(low, rows[-1] + 1)
    for chunk, row in zip(batch, rows, strict=True):
        chunk.embedding = block[row - low]
    FilmChunk.objects.bulk_create(
        batch,
        batch_size=CHUNK_BATCH,
        update_conflicts=True,
        unique_fields=["film", "position"],
        update_fields=["text", "embedding", "updated_at"],
    )
    summary.chunks += len(batch)
    reset_queries()  # DEBUG açıkken sorgu günlüğü vektör metinleriyle belleği doldurur
    if (summary.chunks // CHUNK_BATCH) % LOG_EVERY_BATCHES == 0:
        logger.info("Parçalar: %s", summary.chunks)


def load_chunks(
    root: Path, dataset_ids: list[str], renewed_ids: set[str], summary: LoadSummary
) -> None:
    """Hazır parça vektörleri; hikâyesi yenilenen filmlerin eski parçaları yüklenmez.

    Metni değişmemiş parça yeniden yazılmaz (HNSW her güncellemede şişer). Vektör dosyası AYNI
    metinle değişirse bayat vektör kalır: o durumda ilgili parçalar silinip yeniden yüklenmeli."""
    film_rows, texts = sources.load_chunk_texts(root)
    vectors = sources.open_chunk_vectors(root)
    if vectors.total != len(texts):
        raise ServiceError(
            f"Vektör sayısı ({vectors.total}) parça sayısıyla ({len(texts)}) uyuşmuyor.",
            "chunk_misaligned",
            500,
        )
    verify_chunk_alignment(root, film_rows, texts, dataset_ids, renewed_ids)

    film_pks = _film_id_map(set(dataset_ids))
    scope_pks = set(film_pks.values())
    loaded_text_hashes = {
        (film_id, position): hash(text)
        for film_id, position, text in FilmChunk.objects.order_by()
        .values_list("film_id", "position", "text")
        .iterator(chunk_size=5000)
        if film_id in scope_pks
    }
    next_position: dict[int, int] = {}
    pending: list[tuple[int, int, int]] = []  # (pkl satırı, film pk, parça sırası)
    for index, film_row in enumerate(film_rows.tolist()):
        if film_row >= len(dataset_ids):
            break  # --limit dilimi bitti; pkl film sırasına göre sıralı
        wikidata_id = dataset_ids[film_row]
        if wikidata_id in renewed_ids:
            summary.skipped["yenilenen_filmin_eski_parcasi"] += 1
            continue
        film_pk = film_pks.get(wikidata_id)
        if film_pk is None:
            summary.skipped["parca_film_yok"] += 1
            continue
        position = next_position.get(film_pk, 0)
        next_position[film_pk] = position + 1
        if loaded_text_hashes.get((film_pk, position)) == hash(texts[index]):
            summary.skipped["parca_zaten_yuklu"] += 1
            continue
        pending.append((index, film_pk, position))

    with bulk_write_window(FilmChunk, len(pending)):
        for start in range(0, len(pending), CHUNK_BATCH):
            part = pending[start : start + CHUNK_BATCH]
            batch = [
                FilmChunk(film_id=film_pk, position=position, text=texts[index])
                for index, film_pk, position in part
            ]
            _write_chunks(batch, [index for index, _pk, _pos in part], vectors, summary)
        # İndeks pencere kapanırken kurulur; o sırada büyük yapılar bellekte tutulmasın.
        texts = film_rows = pending = loaded_text_hashes = vectors = film_pks = None


def load_card_vectors(
    root: Path,
    dataset_ids: list[str],
    summary: LoadSummary,
    stale_ids: set[str] | None = None,
) -> None:
    """Hazır kart vektörleri; yalnız kart vektörü boş filmlere yazılır (üretilenler ezilmez).

    `stale_ids`: kart metni artık dosyadaki kaydın kaynağıyla aynı tarifte olmayan filmler (ör.
    TMDB alanı sonradan ek kayıttan işlenenler; dosyadaki kart yalnız başlık/tür/ülkeden üretildi).
    Bunların dosya vektörü kullanılmaz; veritabanındaki kart hâlâ o dosya vektörüyse temizlenir ve
    `embed_missing` güncel kart metninden yeniden üretir."""
    stale_ids = stale_ids or set()
    aligned_ids = sources.load_dataset_ids_alignment(root)
    cards = sources.open_card_vectors(root)
    if len(cards) != len(aligned_ids) or aligned_ids[: len(dataset_ids)] != dataset_ids:
        raise ServiceError(
            "Kart vektörlerinin film sırası veri setiyle uyuşmuyor.", "card_misaligned", 500
        )

    scope = set(dataset_ids)
    stale_rows = {
        wikidata_id: row for row, wikidata_id in enumerate(dataset_ids) if wikidata_id in stale_ids
    }
    empty_pks = {
        wikidata_id: pk
        for wikidata_id, pk in Film.objects.filter(card_embedding__isnull=True)
        .values_list("wikidata_id", "pk")
        .iterator()
        if wikidata_id in scope and wikidata_id not in stale_rows
    }
    stale_pks = dict(  # kartı dolu bayat filmler: film pk -> dosya satırı
        (pk, stale_rows[wikidata_id])
        for wikidata_id, pk in Film.objects.filter(
            wikidata_id__in=list(stale_rows), card_embedding__isnull=False
        ).values_list("wikidata_id", "pk")
    )
    _clear_stale_cards(cards, stale_pks, summary)

    pending = [
        (row, empty_pks[wikidata_id])
        for row, wikidata_id in enumerate(dataset_ids)
        if wikidata_id in empty_pks
    ]
    now = timezone.now()
    with bulk_write_window(Film, len(pending)):
        for start in range(0, len(pending), CARD_BATCH):
            batch = [
                Film(pk=pk, card_embedding=cards[row], updated_at=now)
                for row, pk in pending[start : start + CARD_BATCH]
            ]
            _write_cards(batch, summary)
        cards = pending = empty_pks = None  # indeks kurulurken bellek boşalsın


def _clear_stale_cards(cards, stale_pks: dict[int, int], summary: LoadSummary) -> None:
    """Kartı hâlâ dosyadaki bayat vektör olan filmlerin kartını boşaltır; üretilmiş kart kalır."""
    cleared = []
    for film in Film.objects.filter(pk__in=stale_pks):
        if np.array_equal(
            np.asarray(film.card_embedding, dtype=np.float16), cards[stale_pks[film.pk]]
        ):
            film.card_embedding = None
            cleared.append(film)
    if cleared:
        Film.objects.bulk_update(cleared, ["card_embedding"], batch_size=CARD_BATCH)
        summary.skipped["bayat_kart_temizlendi"] += len(cleared)


def _write_cards(batch: list[Film], summary: LoadSummary) -> None:
    Film.objects.bulk_update(batch, ["card_embedding", "updated_at"], batch_size=CARD_BATCH)
    summary.card_vectors += len(batch)
    reset_queries()  # DEBUG açıkken sorgu günlüğü vektör metinleriyle belleği doldurur
    if (summary.card_vectors // CARD_BATCH) % LOG_EVERY_BATCHES == 0:
        logger.info("Kart vektörleri: %s", summary.card_vectors)


def build_profile(film_pk: int, profile: dict, summary: LoadSummary) -> FilmProfile:
    """Profil kaydı; izinli ton listesinde olmayan `mood` değerleri atılır ve sayılır."""
    raw_moods = profile.get("mood") or []
    moods = [mood for mood in raw_moods if mood in _MOOD_VALUES]
    summary.dropped_moods += len(raw_moods) - len(moods)
    setting = profile.get("setting") or {}
    return FilmProfile(
        film_id=film_pk,
        themes=profile.get("themes") or [],
        moods=moods,
        tone=profile.get("tone") or "",
        pacing=profile.get("pacing") or "",
        setting_place=setting.get("place") or "",
        setting_period=setting.get("period") or "",
        narrative=profile.get("narrative") or [],
        for_viewers=profile.get("for_viewers") or "",
        tr_pitch=profile.get("tr_pitch") or "",
        evidence=profile.get("evidence") or "",
    )


def load_profiles(
    root: Path,
    scope_ids: set[str],
    is_limited: bool,
    summary: LoadSummary,
    aliases: dict[str, str] | None = None,
) -> None:
    """`aliases`: arşiv filmine işlenen ek kaydın profil kimliği -> arşiv film kimliği. Böyle bir
    filmin kendi profili, ek kaydın profiliyle değiştirilir."""
    aliases = aliases or {}
    replaced_ids = set(aliases.values())
    film_pks = _film_id_map(scope_ids)
    batch: list[FilmProfile] = []
    update_fields = [
        f.name
        for f in FilmProfile._meta.concrete_fields
        if f.name not in {"id", "created_at", "film"}
    ]
    for record in sources.iter_profiles(root):
        if record["id"] in replaced_ids:
            summary.skipped["profil_ek_kayitla_degistirildi"] += 1
            continue
        film_pk = film_pks.get(aliases.get(record["id"], record["id"]))
        if film_pk is None:
            reason = "profil_kapsam_disi_limit" if is_limited else "profil_film_bulunamadi"
            summary.skipped[reason] += 1
            continue
        batch.append(build_profile(film_pk, record["p"], summary))
        if len(batch) >= PROFILE_BATCH:
            _write_profiles(batch, update_fields, summary)
            batch = []
    if batch:
        _write_profiles(batch, update_fields, summary)


def _write_profiles(batch: list[FilmProfile], update_fields: list[str], summary: LoadSummary):
    FilmProfile.objects.bulk_create(
        batch,
        batch_size=PROFILE_BATCH,
        update_conflicts=True,
        unique_fields=["film"],
        update_fields=update_fields,
    )
    summary.profiles += len(batch)
    reset_queries()  # DEBUG açıkken sorgu günlüğü vektör metinleriyle belleği doldurur


def parse_review_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def load_reviews(root: Path, scope_ids: set[str], is_limited: bool, summary: LoadSummary) -> None:
    film_pks = _film_id_map(scope_ids)
    batch: list[FilmReview] = []
    for record in sources.iter_reviews(root):
        film_pk = film_pks.get(record["movie_id"])
        if film_pk is None:
            reason = "inceleme_kapsam_disi_limit" if is_limited else "inceleme_film_bulunamadi"
            summary.skipped[reason] += len(record["incelemeler"])
            continue
        summary.review_films += 1
        for review in record["incelemeler"]:
            batch.append(
                FilmReview(
                    film_id=film_pk,
                    content=review["icerik"],
                    rating=review.get("puan"),
                    published_at=parse_review_time(review.get("tarih")),
                    url=review["url"],
                )
            )
        if len(batch) >= REVIEW_BATCH:
            _write_reviews(batch, summary)
            batch = []
    if batch:
        _write_reviews(batch, summary)


def _write_reviews(batch: list[FilmReview], summary: LoadSummary) -> None:
    FilmReview.objects.bulk_create(
        batch,
        batch_size=REVIEW_BATCH,
        update_conflicts=True,
        unique_fields=["film", "url"],
        update_fields=["content", "rating", "published_at", "updated_at"],
    )
    summary.reviews += len(batch)
    reset_queries()  # DEBUG açıkken sorgu günlüğü vektör metinleriyle belleği doldurur


def load_archive(root: Path = sources.DEFAULT_DATA_ROOT, limit: int | None = None) -> LoadSummary:
    """Sıra: filmler -> parçalar -> kart vektörleri -> profiller -> incelemeler."""
    with films_write_lock():
        return _run_load_archive(root, limit)


def _run_load_archive(root: Path, limit: int | None) -> LoadSummary:
    summary = LoadSummary()

    def timed(step: str, started: float) -> None:
        summary.seconds[step] = round(time.monotonic() - started, 1)
        peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
        logger.info(
            "Adım bitti: %s (%s sn, tepe bellek %s MB)", step, summary.seconds[step], peak_mb
        )

    ensure_vector_indexes()
    started = time.monotonic()
    tmdb_index = sources.load_tmdb_index(root)
    renewals = sources.load_plot_renewals(root)
    plan = ExtraPlan()
    if limit is None:
        plan = plan_extra_films(root, index_dataset_identifiers(root), summary)
    credits = sources.load_credits(root)
    summary.credits_file_missing = credits.file_missing
    dataset_ids = load_dataset_films(
        root, tmdb_index, renewals, limit, summary, plan.merged, credits
    )
    extra_ids = load_extra_films(plan, summary, credits) if limit is None else []
    if limit is None:
        # --limit'te kapsam dışı filmlerin künyesi "eşleşmedi" sayılmaz.
        report_unmatched_credits(credits, summary)
    timed("filmler", started)
    del tmdb_index  # ~87 bin kayıt; sonraki adımlarda gerekmez, bellek boşalsın

    renewed_ids = {wikidata_id for wikidata_id in dataset_ids if wikidata_id in renewals}
    scope_ids = set(dataset_ids) | set(extra_ids)

    started = time.monotonic()
    load_chunks(root, dataset_ids, renewed_ids, summary)
    timed("parcalar", started)

    started = time.monotonic()
    load_card_vectors(root, dataset_ids, summary, summary.merged_extra_ids)
    timed("kart_vektorleri", started)

    started = time.monotonic()
    with transaction.atomic():
        # Ek kaydın verisi arşiv filmine uygulanmadıysa (filmin kendi TMDB kaydı var) profili de
        # değiştirilmez.
        applied = {k: v for k, v in plan.aliases.items() if v in summary.merged_extra_ids}
        load_profiles(root, scope_ids, limit is not None, summary, applied)
        load_reviews(root, scope_ids, limit is not None, summary)
    timed("profil_ve_incelemeler", started)

    logger.info(summary.describe())
    return summary
