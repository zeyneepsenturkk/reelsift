"""Ham kaynak satırlarını `Film` alanlarına çevirir. Birleştirme kuralı: TMDB değeri varsa o."""

from datetime import date

from apps.films.models import Film
from apps.films.services import sources

PLOT_HEADINGS = {"plot", "synopsis", "premise", "plot summary", "summary", "story", "storyline"}


def parse_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_date(value) -> date | None:
    """Kaynaktaki bozuk değerler (boş, Wikidata `genid` bağlantısı) boş tarih sayılır."""
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def split_names(value: str | None) -> list[str]:
    return [name.strip() for name in (value or "").split(",") if name.strip()]


def clean_plot(text: str | None) -> str:
    """Wikipedia'dan gelen hikâyelerin başındaki bölüm başlığı satırını ("Plot") atar."""
    text = (text or "").strip()
    first_line, separator, rest = text.partition("\n")
    if separator and first_line.strip().lower() in PLOT_HEADINGS:
        return rest.strip()
    return text


def _first_text(*values: str | None) -> str:
    return next((value for value in values if value), "")


def _first_list(*values: list[str] | None) -> list[str]:
    return next((list(value) for value in values if value), [])


def turkish_title(record: dict) -> str:
    """TMDB, ad özgün adla aynıysa Türkçe çeviriyi boş döndürür; Türkçe filmde özgün ad
    zaten Türkçe addır."""
    if record.get("tr_title"):
        return record["tr_title"]
    if record.get("original_language") == "tr":
        return record.get("original_title") or ""
    return ""


def build_dataset_film(row: dict, tmdb: dict | None, renewed_plot: str | None) -> dict:
    """Veri seti satırı + eşleşen TMDB kaydı (yoksa None) + yenilenmiş hikâye (yoksa None)."""
    tmdb = tmdb or {}
    if renewed_plot:
        plot, plot_source = clean_plot(renewed_plot), Film.PlotSource.WIKIPEDIA_RENEWED
    else:
        plot, plot_source = row["plot"], Film.PlotSource.DATASET
    if tmdb:
        vote_average = tmdb.get("vote_average")
        vote_count = tmdb.get("vote_count") or 0
        popularity = tmdb.get("popularity")
    else:
        vote_average = parse_float(row["vote_average"])
        vote_count = parse_int(row["vote_count"]) or 0
        popularity = parse_float(row["popularity"])
    return {
        "wikidata_id": row["movie_id"],
        "tmdb_id": tmdb.get("tmdb_id") or parse_int(row["tmdb_id"]),
        "imdb_id": _first_text(tmdb.get("imdb_id"), row["imdb_id"]),
        "title": _first_text(tmdb.get("title"), row["title"]),
        "original_title": tmdb.get("original_title") or "",
        "tr_title": turkish_title(tmdb),
        "original_language": tmdb.get("original_language") or "",
        "year": parse_int(row["year"]),
        "release_date": parse_date(tmdb.get("release_date")) or parse_date(row["release_date"]),
        "runtime": tmdb.get("runtime") or parse_int(row["duration"]) or None,
        "countries": _first_list(tmdb.get("countries"), split_names(row["country"])),
        "genres": _first_list(tmdb.get("genres"), split_names(row["genre"])),
        "keywords": _first_list(tmdb.get("keywords")),
        "directors": sources.drop_raw_ids(split_names(row["directors"])),
        "actors": sources.drop_raw_ids(split_names(row["actors"])),
        "overview": tmdb.get("overview") or "",
        "tr_overview": tmdb.get("tr_overview") or "",
        "tagline": tmdb.get("tagline") or "",
        "plot": plot,
        "plot_source": plot_source,
        "wikipedia_url": row["wikipedia_link"],
        "vote_average": vote_average,
        "vote_count": vote_count,
        "popularity": popularity,
        "poster_path": tmdb.get("poster_path") or "",
        "backdrop_path": tmdb.get("backdrop_path") or "",
    }


def extra_wikidata_id(extra: dict) -> str:
    return extra.get("wikidata_id") or f"tmdb-{extra['tmdb_id']}"


def build_extra_film(extra: dict) -> dict:
    """Arşivde olmayan ek film: TMDB alanları + (varsa) Wikipedia hikâyesi."""
    release_date = parse_date(extra.get("release_date"))
    plot = clean_plot(extra.get("plot"))
    countries = [country["name"] for country in extra.get("production_countries") or []]
    return {
        "wikidata_id": extra_wikidata_id(extra),
        "tmdb_id": extra["tmdb_id"],
        "imdb_id": extra.get("imdb_id") or "",
        "title": extra["title"],
        "original_title": extra.get("original_title") or "",
        "tr_title": turkish_title(extra),
        "original_language": extra.get("original_language") or "",
        "year": extra.get("year") or (release_date.year if release_date else None),
        "release_date": release_date,
        "runtime": extra.get("runtime") or None,
        "countries": countries,
        "genres": list(extra.get("genres") or []),
        "keywords": list(extra.get("keywords") or []),
        "directors": [],
        "actors": [],
        "overview": extra.get("overview") or "",
        "tr_overview": extra.get("tr_overview") or "",
        "tagline": extra.get("tagline") or "",
        "plot": plot,
        "plot_source": Film.PlotSource.WIKIPEDIA_ADDED if plot else "",
        "wikipedia_url": extra.get("wikipedia_link") or "",
        "vote_average": extra.get("vote_average"),
        "vote_count": extra.get("vote_count") or 0,
        "popularity": extra.get("popularity"),
        "poster_path": extra.get("poster_path") or "",
        "backdrop_path": extra.get("backdrop_path") or "",
    }


def apply_credits(record: dict, credits: sources.CreditsIndex | None) -> str | None:
    """Künye dosyasındaki yönetmen/oyuncuyu, `record`un YALNIZ boş alanlarına yazar.

    Dönüş: "applied" (en az bir alan dolduruldu), "already_filled" (künyede veri var ama ilgili
    alanlar zaten doluydu), yoksa None (künye satırı yok ya da künyede veri yok)."""
    entry = credits.by_wikidata_id.get(record["wikidata_id"]) if credits else None
    if entry is None:
        return None
    credits.matched.add(record["wikidata_id"])
    applied = blocked = False
    for name in ("directors", "actors"):
        if not entry[name]:
            continue
        if record[name]:
            blocked = True
            continue
        record[name] = list(entry[name])
        applied = True
    if applied:
        return "applied"
    return "already_filled" if blocked else None


def extra_as_tmdb(extra: dict) -> dict:
    """Ek kaydı, TMDB kaydı olmayan arşiv filmine işlemek için TMDB indeks biçimine çevirir."""
    kept = {name: extra.get(name) for name in sources.TMDB_KEPT_FIELDS}
    kept["countries"] = [country["name"] for country in extra.get("production_countries") or []]
    return kept
