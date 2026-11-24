"""Düğümlerin veritabanı erişimi (eşzamanlı fonksiyonlar; düğümler `sync_to_async` ile çağırır)
ve istem bölümlerinin biçimlendirilmesi.

Film metinleri, incelemeler ve kullanıcı mesajı VERİDİR: istemlere etiketli bölümler olarak
girer; etiketi kapatmaya çalışan metinler etkisizleştirilir (`neutralize`).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from django.db.models.functions import Substr

from apps.agent import prompts
from apps.chats.models import Chat
from apps.chats.services.chats import recent_history
from apps.curation.models import Collection, CollectionFilm
from apps.curation.services.countries import country_name_tr
from apps.curation.services.drafts import KeptFilm, NewFilm, save_draft
from apps.curation.services.serializers import collection_queryset, serialize_collection
from apps.films.models import Film
from apps.search.services.people import normalize_person

JUDGE_PLOT_CHARS = 700
JUDGE_OVERVIEW_CHARS = 500
WRITE_PLOT_CHARS = 4000
REVIEW_CHARS = 1200
MAX_REVIEWS = 2
HISTORY_TEXT_CHARS = 600
ANSWER_PLOT_CHARS = 1500
ANSWER_SHORT_PLOT_CHARS = 600
JUDGE_DIRECTORS = 3
JUDGE_CAST = 5
ARCHIVE_FILM_LIMIT = 15

# Açılış/kapanış, büyük-küçük harf ve `<` ile ad arasındaki boşluk varyasyonları yakalanır.
_TAG = re.compile(r"<\s*/?\s*(?:" + "|".join(prompts.TAGS) + r")\b", re.I)


def neutralize(text: str) -> str:
    """Veri içindeki `</film>` gibi etiket açma/kapatma girişimlerini bozar: `<` yerine `‹`."""
    return _TAG.sub(lambda match: "‹" + match.group(0)[1:], text or "")


def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    boundary = cut.rfind(" ")
    return (cut[:boundary] if boundary > limit * 0.8 else cut).rstrip()


@dataclass(frozen=True)
class TurnContext:
    draft_id: int | None
    draft_status: str | None
    draft_title: str
    draft_description: str
    draft_films: tuple[tuple[int, str, int | None], ...]
    previous_request: dict | None
    history: tuple[tuple[str, str], ...]
    # Anlama istemine giden taslak satırları: çift ad biçimi ("Masumiyet (Innocence, 1997)");
    # editör özgün adı yazınca da film tanınsın. `draft_films` adı arayüz adıdır.
    draft_model_names: tuple[str, ...] = ()


def load_turn_context(chat_id: int, user_id: int, before_message_id: int) -> TurnContext:
    """Güncel taslak (sohbetin en yeni koleksiyonu), önceki istek ve son 6 mesaj."""
    chat = Chat.objects.get(pk=chat_id, user_id=user_id)
    collection = Collection.objects.filter(chat=chat, owner_id=user_id).order_by("-id").first()
    films: tuple[tuple[int, str, int | None], ...] = ()
    model_names: tuple[str, ...] = ()
    if collection:
        # Başlık ve yıl için film kaydı gerekir; tek sorguda birleştirilir.
        rows = (
            CollectionFilm.objects.filter(collection=collection)
            .select_related("film")
            .only("position", "film", "film__title", "film__tr_title", "film__year")
            .order_by("position")
        )
        films = tuple((row.film_id, ui_title(row.film), row.film.year) for row in rows)
        model_names = tuple(_title_line(row.film) for row in rows)
    history = tuple(
        (message.role, truncate(message.text, HISTORY_TEXT_CHARS))
        for message in recent_history(chat, before_id=before_message_id)
    )
    return TurnContext(
        draft_id=collection.pk if collection else None,
        draft_status=collection.status if collection else None,
        draft_title=collection.title if collection else "",
        draft_description=collection.description if collection else "",
        draft_films=films,
        previous_request=(collection.request or None) if collection else None,
        history=history,
        draft_model_names=model_names,
    )


def film_names(ids: list[int]) -> list[str]:
    """Bu turda modele verilen filmlerin her adı (title, tr_title, original_title); cevap
    denetiminde meşru ad olarak sayılır."""
    rows = Film.objects.filter(pk__in=ids).values_list("title", "tr_title", "original_title")
    return [name for row in rows for name in row if name]


def draft_film_ids(collection_id: int) -> list[int]:
    return list(
        CollectionFilm.objects.filter(collection_id=collection_id)
        .order_by("position")
        .values_list("film_id", flat=True)
    )


def load_judge_films(ids: list[int]) -> dict[int, Film]:
    """Değerlendirme için: hikâyenin yalnız başı veritabanında kesilir (60 uzun metin çekilmez)."""
    films = (
        Film.objects.filter(pk__in=ids)
        .defer("card_embedding", "plot")
        .annotate(plot_excerpt=Substr("plot", 1, JUDGE_PLOT_CHARS))
        .select_related("profile")  # film başına ayrı profil sorgusu olmasın
    )
    return {film.pk: film for film in films}


def load_source_films(ids: list[int]) -> dict[int, Film]:
    """Gerekçe ve alıntı için tam kaynak metinleri (hikâye, TMDB özeti, incelemeler)."""
    films = (
        Film.objects.filter(pk__in=ids)
        .defer("card_embedding")
        .prefetch_related("reviews")  # incelemeler tek ek sorguda
    )
    return {film.pk: film for film in films}


def ui_title(film: Film) -> str:
    """Arayüzün gösterdiği ad (`filmName`, collection.ts): Türkçe ad varsa o, yoksa `title`."""
    return film.tr_title or film.title


def _title_line(film: Film) -> str:
    """Modele giden ad: Türkçe ad önde, özgün `title` ve yıl parantezde ("Masumiyet (Innocence,
    1997)"); Türkçe ad yoksa ya da aynıysa "Innocence (1997)". Modelin cevaptaki adı ekrandaki
    adla tutsun diye."""
    if film.tr_title and film.tr_title != film.title:
        original = f"{film.title}, {film.year}" if film.year else film.title
        return neutralize(f"{film.tr_title} ({original})")
    year = f" ({film.year})" if film.year else ""
    return neutralize(f"{film.title}{year}")


def _profile_line(film: Film) -> str:
    profile = getattr(film, "profile", None)
    if profile is None:
        return ""
    parts = []
    if profile.themes:
        parts.append("themes: " + ", ".join(profile.themes))
    if profile.moods:
        parts.append("mood: " + ", ".join(profile.moods))
    if profile.tone:
        parts.append("tone: " + profile.tone)
    if profile.pacing and profile.pacing != "unknown":
        parts.append("pacing: " + profile.pacing)
    if profile.setting_place or profile.setting_period:
        parts.append(f"setting: {profile.setting_place} {profile.setting_period}".strip())
    return neutralize("; ".join(parts))


def format_judge_film(film: Film) -> str:
    lines = [f'<film id="{film.pk}">', f"Title: {_title_line(film)}"]
    if film.countries:
        lines.append("Countries: " + neutralize(", ".join(film.countries)))
    if film.genres:
        lines.append("Genres: " + neutralize(", ".join(film.genres)))
    if film.directors:
        lines.append("Directors: " + neutralize(", ".join(film.directors[:JUDGE_DIRECTORS])))
    if film.actors:
        lines.append("Cast: " + neutralize(", ".join(film.actors[:JUDGE_CAST])))
    if film.overview:
        lines.append("TMDB overview: " + neutralize(truncate(film.overview, JUDGE_OVERVIEW_CHARS)))
    excerpt = getattr(film, "plot_excerpt", "") or ""
    if not excerpt.strip() and film.tr_overview:
        # Hikâyesi olmayan film için Türkçe özet tek metin kaynağıdır.
        lines.append(
            "TMDB overview (Turkish): "
            + neutralize(truncate(film.tr_overview, JUDGE_OVERVIEW_CHARS))
        )
    profile = _profile_line(film)
    if profile:
        lines.append("Profile: " + profile)
    if excerpt.strip():
        lines.append("Story excerpt: " + neutralize(excerpt.strip()))
    lines.append("</film>")
    return "\n".join(lines)


def pick_reviews(film: Film) -> list:
    """En uzun iki inceleme; uzun inceleme daha çok alıntılık cümle taşır."""
    return sorted(film.reviews.all(), key=lambda review: len(review.content), reverse=True)[
        :MAX_REVIEWS
    ]


def _source_tags(film: Film, *, plot_chars: int, reviews: bool) -> list[str]:
    tags = []
    if film.plot.strip():
        tags.append(f'<source kind="plot">{neutralize(truncate(film.plot, plot_chars))}</source>')
    if film.overview.strip():
        tags.append(f'<source kind="overview">{neutralize(film.overview.strip())}</source>')
    if not film.plot.strip() and film.tr_overview.strip():
        tags.append(f'<source kind="overview">{neutralize(film.tr_overview.strip())}</source>')
    if reviews:
        for review in pick_reviews(film):
            excerpt = neutralize(truncate(review.content, REVIEW_CHARS))
            tags.append(f'<source kind="review">{excerpt}</source>')
    return tags


FACT_DIRECTORS = 3
_RANK_NOTES = {
    "rating": "This selection is ordered by TMDB rating, weighted by the number of votes.",
    "popularity": "This selection is ordered by the number of TMDB votes.",
}


def selection_facts(
    film: Film,
    *,
    people: Sequence[str] = (),
    rank_by: str | None = None,
    archive_counts: dict[str, int] | None = None,
    rank_note: bool = True,
) -> str:
    """Gerekçe adımı için KODUN ürettiği olgular: yönetmenler, istekteki kişinin bu filmdeki rolü
    (kişi dizinindekiyle aynı ad normalleştirmesi), `rank_by` değeri ve sıralama notu.
    `archive_counts`: normalleştirilmiş ad -> arşivdeki film sayısı (yalnız kişi + `rank_by`
    isteğinde yazılır)."""
    lines = []
    if film.directors:
        lines.append("Directors: " + neutralize(", ".join(film.directors[:FACT_DIRECTORS])))
    directors = {normalize_person(name) for name in film.directors}
    cast = {normalize_person(name) for name in film.actors}
    for name in people:
        key = normalize_person(name)
        if key in directors:
            lines.append(f"{neutralize(name)} directed this film")
        if key in cast:
            lines.append(f"{neutralize(name)} is in the cast")
    if rank_by == "rating" and film.vote_average is not None and film.vote_count:
        lines.append(f"TMDB rating: {film.vote_average:.1f} ({film.vote_count} votes)")
    elif rank_by == "popularity":
        lines.append(f"TMDB votes: {film.vote_count}")
    if rank_by and archive_counts:
        for name in people:
            count = archive_counts.get(normalize_person(name))
            if count is not None:
                lines.append(f"Films by {neutralize(name)} in the archive: {count}")
    if rank_note and rank_by in _RANK_NOTES:
        lines.append(_RANK_NOTES[rank_by])
    if not lines:
        return ""
    return "<facts>\n" + "\n".join(lines) + "\n</facts>"


def format_source_film(film: Film, facts: str = "") -> str:
    lines = [f'<film id="{film.pk}">', f"<title>{_title_line(film)}</title>"]
    if facts:
        lines.append(facts)
    lines += _source_tags(film, plot_chars=WRITE_PLOT_CHARS, reviews=True)
    lines.append("</film>")
    return "\n".join(lines)


def format_candidate_line(film: Film, reason: str, in_draft: bool) -> str:
    """Seçim adımı için kısa satır: ad, yıl, ülke, yönetmen, değerlendirme gerekçesi."""
    directors = neutralize(", ".join(film.directors[:2]))
    countries = neutralize(", ".join(film.countries[:2]))
    marker = " [already in the current selection]" if in_draft else ""
    return (
        f'<film id="{film.pk}">{_title_line(film)} | {countries} | directors: {directors} '
        f"| note: {neutralize(reason)}{marker}</film>"
    )


def load_answer_texts(collection_id: int, film_id: int | None) -> str:
    """Soru cevabı için taslaktaki filmlerin metinleri (tek film sorulduysa yalnız o)."""
    rows = CollectionFilm.objects.filter(collection_id=collection_id).order_by("position")
    if film_id is not None:
        rows = rows.filter(film_id=film_id)
    rows = list(rows)
    films = load_source_films([row.film_id for row in rows])
    blocks = []
    for row in rows:
        film = films[row.film_id]
        lines = [f'<film id="{film.pk}">', f"<title>{_title_line(film)}</title>"]
        if film.directors:
            lines.append("Directors: " + neutralize(", ".join(film.directors[:JUDGE_DIRECTORS])))
        lines.append(f"<rationale>{neutralize(row.rationale)}</rationale>")
        if row.source_quote:
            lines.append(f"<quote>{neutralize(row.source_quote)}</quote>")
        plot_chars = ANSWER_PLOT_CHARS if film_id is not None else ANSWER_SHORT_PLOT_CHARS
        lines += _source_tags(film, plot_chars=plot_chars, reviews=film_id is not None)
        lines.append("</film>")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def collection_lines(collection_id: int) -> str:
    """Duyuru adımı için taslağın kısa özeti: ad, yıl, ülkeler ve gerekçenin ilk cümlesi."""
    rows = (
        CollectionFilm.objects.filter(collection_id=collection_id)
        .select_related("film")
        .defer("film__card_embedding", "film__plot", "film__overview")
        .order_by("position")
    )
    lines = []
    for row in rows:
        film = row.film
        countries = neutralize(", ".join(country_name_tr(name) for name in film.countries[:2]))
        first_sentence = neutralize(row.rationale.split(". ")[0].strip())
        directors = neutralize(", ".join(film.directors[:2]))
        details = f"{countries}, director: {directors}" if directors else countries
        lines.append(f"- {_title_line(film)} ({details}): {first_sentence}")
    return "\n".join(lines)


_ROLE_LABELS = {"director": " as a director", "actor": " as an actor", "any": ""}


def archive_block(entries: list[tuple[str, str, int, list[int]]]) -> str:
    """Soru ve diğer niyetler için `<archive>` olgusu. Her giriş: (ad, rol, arşivdeki film sayısı,
    film kimlikleri). Filmler yıla göre sıralı, kişi başına en çok 15. Bu mesaj için arama
    yapılmadı: olgu doğrudan kişi dizininden gelir."""
    all_ids = {film_id for _, _, _, film_ids in entries for film_id in film_ids}
    films = {f.pk: f for f in Film.objects.filter(pk__in=all_ids).only("title", "tr_title", "year")}
    lines = []
    for name, role, count, film_ids in entries:
        subject = f"{neutralize(name)}{_ROLE_LABELS.get(role, '')}"
        if not count:
            lines.append(f"{subject}: no film in the archive is listed under this name.")
            continue
        ordered = sorted(
            (films[film_id] for film_id in film_ids if film_id in films),
            key=lambda film: (film.year is None, film.year or 0, film.title),
        )
        shown = "; ".join(_title_line(film) for film in ordered[:ARCHIVE_FILM_LIMIT])
        more = f" (first {ARCHIVE_FILM_LIMIT} by year)" if count > ARCHIVE_FILM_LIMIT else ""
        lines.append(f"{subject}: {count} film(s) in the archive{more}: {shown}")
    return "\n".join(lines)


def persist_draft(
    *,
    chat_id: int,
    user_id: int,
    request: dict,
    title: str,
    description: str,
    entries: list[KeptFilm | NewFilm],
    base_id: int | None,
) -> dict:
    """Taslağı tek işlemde yazar ve tam `Collection` cevabını (sözleşme biçimi) döndürür."""
    chat = Chat.objects.select_related("user").get(pk=chat_id, user_id=user_id)
    base = Collection.objects.get(pk=base_id, owner_id=user_id) if base_id else None
    collection_id = save_draft(
        owner=chat.user,
        chat=chat,
        request=request,
        title=title,
        description=description,
        entries=entries,
        base=base,
    )
    collection = collection_queryset().get(pk=collection_id)
    return serialize_collection(collection).model_dump(mode="json")


def film_title_lines(ids: list[int]) -> dict[int, str]:
    """Film adı ve yılı (etkisizleştirilmiş); film değiştirme notunda adlar için."""
    films = Film.objects.filter(pk__in=ids).only("title", "tr_title", "year")
    return {film.pk: _title_line(film) for film in films}


def collection_film_count(collection_id: int) -> int:
    """Kaydedilmiş taslaktaki gerçek film sayısı (modele sayım bırakılmaz)."""
    return CollectionFilm.objects.filter(collection_id=collection_id).count()


def base_texts(collection_id: int) -> tuple[str, str]:
    collection = Collection.objects.only("title", "description").get(pk=collection_id)
    return collection.title, collection.description
