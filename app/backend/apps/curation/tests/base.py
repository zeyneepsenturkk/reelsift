from apps.chats.tests.base import make_chat, make_user
from apps.curation.models import Collection, CollectionFilm
from apps.films.models import Film, FilmReview
from apps.films.tests.base import make_film

PLOT = (
    "Snow covers the small town of Kallio. A detective walks slowly through the empty streets "
    "and questions every neighbour. The case grows darker with each passing night."
)
PLOT_QUOTE = "A detective walks slowly through the empty streets and questions every neighbour."
OVERVIEW = "A quiet policeman investigates a disappearance during a long northern winter."
OVERVIEW_QUOTE = "A quiet policeman investigates a disappearance during a long northern winter."
REVIEW = "Bleak, patient and beautifully shot. The silence in this film is its loudest character."
REVIEW_QUOTE = "The silence in this film is its loudest character."


def make_story_film(number: int = 1, **overrides) -> Film:
    fields = {
        "title": f"Snow Town {number}",
        "year": 2000 + number,
        "countries": ["Finland"],
        "genres": ["crime film"],
        "directors": [f"Director {number}"],
        "plot": PLOT,
        "plot_source": Film.PlotSource.DATASET,
        "overview": OVERVIEW,
        "tmdb_id": 1000 + number,
        "wikipedia_url": f"https://en.wikipedia.org/wiki/Snow_Town_{number}",
        "poster_path": f"/poster{number}.jpg",
        "vote_count": 100 * number,
    }
    fields.update(overrides)
    return make_film(wikidata_id=f"Q{number}", **fields)


def make_review(film: Film, content: str = REVIEW, url: str | None = None) -> FilmReview:
    return FilmReview.objects.create(
        film=film, content=content, url=url or f"https://example.test/review/{film.pk}"
    )


def make_collection(owner, chat=None, *, films=(), status="draft", **overrides) -> Collection:
    collection = Collection.objects.create(
        owner=owner,
        chat=chat,
        title=overrides.pop("title", "Karlı kasabalar"),
        description=overrides.pop("description", "Ağır tempolu polisiyeler."),
        status=status,
        **overrides,
    )
    for position, film in enumerate(films, start=1):
        CollectionFilm.objects.create(
            collection=collection,
            film=film,
            position=position,
            rationale=f"{film.title} için gerekçe.",
            source_quote=PLOT_QUOTE,
            source_kind="plot",
            source_url=film.wikipedia_url,
        )
    return collection


__all__ = [
    "make_chat",
    "make_collection",
    "make_review",
    "make_story_film",
    "make_user",
]
