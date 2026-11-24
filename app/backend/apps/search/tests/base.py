import tempfile
from contextlib import contextmanager
from unittest import mock

import numpy as np
from django.conf import settings
from django.test import override_settings

from apps.films.models import EMBEDDING_DIMENSIONS, Film, FilmChunk, FilmProfile
from apps.search.services import lexical

# Sahte gömme: metindeki anahtar kelime vektörün eksenini belirler
# (aynı eksen = benzerlik 1, farklı eksen = 0).
AXES = {"dream": 0, "ocean": 1, "war": 2}
OTHER_AXIS = 3


def axis_of(text: str) -> int:
    lowered = text.lower()
    return next((axis for word, axis in AXES.items() if word in lowered), OTHER_AXIS)


def axis_vector(axis: int) -> np.ndarray:
    vector = np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float16)
    vector[axis] = 1.0
    return vector


def fake_encode(texts: list[str]) -> np.ndarray:
    return np.stack([axis_vector(axis_of(text)) for text in texts])


def long_text(word: str, length: int = 400) -> str:
    sentence = f"The story is about {word} and the people who live around it. "
    return (sentence * (length // len(sentence) + 1))[:length]


def make_film(
    key: str,
    *,
    word: str = "dream",
    title: str | None = None,
    year: int | None = 2000,
    countries: tuple[str, ...] = ("France",),
    vote_count: int = 100,
    plot: str | None = None,
    overview: str = "",
    keywords: tuple[str, ...] = (),
    with_card: bool = True,
    with_chunk: bool = True,
    original_title: str = "",
    tr_title: str = "",
    directors: tuple[str, ...] = (),
    actors: tuple[str, ...] = (),
    vote_average: float | None = None,
) -> Film:
    film = Film.objects.create(
        wikidata_id=key,
        title=title or f"Film {key}",
        original_title=original_title,
        tr_title=tr_title,
        directors=list(directors),
        actors=list(actors),
        vote_average=vote_average,
        year=year,
        countries=list(countries),
        vote_count=vote_count,
        plot=long_text(word) if plot is None else plot,
        overview=overview,
        keywords=list(keywords),
        card_embedding=axis_vector(axis_of(word)) if with_card else None,
    )
    if with_chunk:
        FilmChunk.objects.create(
            film=film, position=0, text=film.plot, embedding=axis_vector(axis_of(word))
        )
    return film


def make_profile(film: Film, **overrides) -> FilmProfile:
    fields = {
        "themes": ["memory"],
        "moods": ["tense"],
        "tone": "A tense film.",
        "pacing": "fast",
        "for_viewers": "For viewers looking for a puzzle.",
    }
    fields.update(overrides)
    return FilmProfile.objects.create(film=film, **fields)


def override_search(**overrides):
    return override_settings(SEARCH={**settings.SEARCH, **overrides})


@contextmanager
def search_settings(**overrides):
    """Geçici indeks klasörü ve isteğe bağlı ayarlarla çalışır; bellekteki indeksi sıfırlar."""
    with tempfile.TemporaryDirectory() as directory:
        merged = {**settings.SEARCH, "index_dir": directory, **overrides}
        with override_settings(SEARCH=merged):
            lexical.reset_loaded()
            try:
                yield directory
            finally:
                lexical.reset_loaded()


@contextmanager
def fake_models(score_pairs=None):
    """Gömme ve yeniden sıralama modelleri servis sınırında sahtelenir; gerçek model yüklenmez."""

    def default_scores(pairs):
        return [float(len(document)) for _, document in pairs]

    with (
        mock.patch("apps.search.services.neural.encode_texts", side_effect=fake_encode),
        mock.patch(
            "apps.search.services.neural.score_pairs", side_effect=score_pairs or default_scores
        ) as scorer,
    ):
        yield scorer
