"""Gerekçe ve alıntı doğrulaması (kodla; model değil). Atlanamaz: `save_draft` alıntıyı kayıt
anında bir kez daha doğrular."""

from apps.agent.schemas import FilmWriting
from apps.agent.services.language import looks_turkish
from apps.core.exceptions import ServiceError
from apps.curation.services.quotes import check_quote


def verify_writings(
    writings: list[FilmWriting], allowed_ids: set[int], films: dict
) -> tuple[dict[int, FilmWriting], dict[int, str]]:
    """(doğrulananlar, sorunlar) döndürür; ikisi de film kimliğine göre.

    - Aday listesinde olmayan film kimliği reddedilir (sessizce yok sayılır).
    - Gerekçe boşsa, Türkçe değilse ya da alıntı kaynak metinde birebir geçmiyorsa sorun yazılır.
    - Cevapta hiç yer almayan film da sorunlu sayılır.
    """
    verified: dict[int, FilmWriting] = {}
    problems: dict[int, str] = {}
    for writing in writings:
        film_id = writing.film_id
        if film_id not in allowed_ids or film_id in verified:
            continue
        film = films.get(film_id)
        if film is None:
            problems[film_id] = "film not found"
            continue
        if not writing.rationale.strip():
            problems[film_id] = "the rationale is empty"
            continue
        if not looks_turkish(writing.rationale):
            problems[film_id] = (
                "the rationale must be written in Turkish, but it was not; write it again "
                "in Turkish (the source quote stays in English, exactly as written)"
            )
            continue
        try:
            check_quote(film, writing.source_kind, writing.source_quote)
        except ServiceError as error:
            problems[film_id] = (
                f"the quote was rejected ({error.message}); copy 1-2 consecutive sentences "
                "exactly as written in one of the film's sources"
            )
            continue
        verified[film_id] = writing
        problems.pop(film_id, None)
    for film_id in allowed_ids:
        if film_id not in verified and film_id not in problems:
            problems[film_id] = "no entry was returned for this film"
    return verified, problems
