POSTER_BASE_URL = "https://image.tmdb.org/t/p/w342"


def tmdb_url(film) -> str:
    return f"https://www.themoviedb.org/movie/{film.tmdb_id}" if film.tmdb_id else ""


def poster_url(film) -> str | None:
    return f"{POSTER_BASE_URL}{film.poster_path}" if film.poster_path else None
