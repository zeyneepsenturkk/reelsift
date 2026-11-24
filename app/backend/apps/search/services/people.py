"""Kişi dizini: normalleşmiş kişi adı -> o kişinin yönetmen ya da oyuncu olduğu film kimlikleri.

Eşleşme TAM addır (bulanık eşleşme ve tek soyadıyla eşleşme yoktur): yanlış kişiye gitmektense
bulamamak yeğdir. Normalleştirme veritabanına değil belleğe uygulanır; aynı fonksiyon hem dizini
kurarken hem sorgularken kullanılır. Saf mantıktır (veritabanı ve model yok); dizin kelime araması
indeksiyle birlikte kurulur ve diske yazılır (`lexical`).
"""

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROLES = ("director", "actor")

# NFKD ile ayrışmayan harfler; ı/İ başta (Türkçe adlar ASCII yazılsa da eşleşsin).
_FOLD = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ø": "o",
        "Ø": "o",
        "ł": "l",
        "Ł": "l",
        "đ": "d",
        "Đ": "d",
        "ß": "ss",
        "æ": "ae",
        "Æ": "ae",
        "œ": "oe",
        "Œ": "oe",
    }
)
_NOT_WORD = re.compile(r"[\W_]+")

_EMPTY = np.empty(0, dtype=np.int64)


def normalize_person(name: str) -> str:
    """Büyük-küçük harf, aksan, Türkçe harfler (ı/İ dahil), noktalama ve boşluk sadeleşir.

    ASCII'ye indirilmez: Latin olmayan yazıdaki adlar boş anahtara çökmesin."""
    folded = str(name).translate(_FOLD).casefold()
    decomposed = unicodedata.normalize("NFKD", folded)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NOT_WORD.sub(" ", stripped).strip()


@dataclass
class RoleIndex:
    """Tek rol için ad -> film kimlikleri (CSR düzeni: 250 bin adı küçük listelerle şişirmez)."""

    rows: dict[str, int] = field(default_factory=dict)
    offsets: np.ndarray = field(default_factory=lambda: np.zeros(1, dtype=np.int64))
    film_ids: np.ndarray = field(default_factory=lambda: _EMPTY)

    def films(self, key: str) -> np.ndarray:
        row = self.rows.get(key)
        if row is None:
            return _EMPTY
        return self.film_ids[self.offsets[row] : self.offsets[row + 1]]


@dataclass
class PersonIndex:
    director: RoleIndex = field(default_factory=RoleIndex)
    actor: RoleIndex = field(default_factory=RoleIndex)

    def films(self, name: str, role: str = "any") -> np.ndarray:
        """Kişinin arşivdeki film kimlikleri (artan, tekrarsız). Bulunamazsa boş dizi."""
        key = normalize_person(name)
        if not key:
            return _EMPTY
        if role == "director":
            return self.director.films(key)
        if role == "actor":
            return self.actor.films(key)
        return np.union1d(self.director.films(key), self.actor.films(key))


def _add(entries: dict[str, list[int]], film_id: int, names: Iterable[str]) -> None:
    for name in names:
        key = normalize_person(name)
        if not key:
            continue
        ids = entries.setdefault(key, [])
        if not ids or ids[-1] != film_id:  # satırlar kimlik sırasında gelir; aynı filmde tekrar yok
            ids.append(film_id)


def _role_index(entries: dict[str, list[int]]) -> RoleIndex:
    lengths = np.fromiter((len(ids) for ids in entries.values()), dtype=np.int64)
    offsets = np.zeros(len(entries) + 1, dtype=np.int64)
    np.cumsum(lengths, out=offsets[1:])
    film_ids = np.fromiter(
        (film_id for ids in entries.values() for film_id in ids), dtype=np.int64, count=offsets[-1]
    )
    return RoleIndex({key: row for row, key in enumerate(entries)}, offsets, film_ids)


def build_person_index(
    rows: Iterable[tuple[int, list[str], list[str]]], max_directors: int | None = None
) -> PersonIndex:
    """(film_id, yönetmenler, oyuncular) satırlarından dizin kurar. Satırlar `film_id` sırasında
    olmalıdır (artan sıra, dizinin sıralı kimlik listelerini ucuza üretmesini sağlar).

    `max_directors`: bundan çok yönetmeni olan film (derleme/antoloji, ör. 41 yönetmenli) hiçbir
    yönetmenin evrenine girmez; oyuncu dizinini etkilemez."""
    directors: dict[str, list[int]] = {}
    actors: dict[str, list[int]] = {}
    for film_id, film_directors, film_actors in rows:
        if max_directors is None or len(film_directors) <= max_directors:
            _add(directors, film_id, film_directors)
        _add(actors, film_id, film_actors)
    return PersonIndex(_role_index(directors), _role_index(actors))


def save_person_index(index: PersonIndex, directory: Path) -> None:
    names = {role: list(getattr(index, role).rows) for role in ROLES}
    (directory / "people.json").write_text(json.dumps(names), encoding="utf-8")
    arrays = {}
    for role in ROLES:
        arrays[f"{role}_offsets"] = getattr(index, role).offsets
        arrays[f"{role}_film_ids"] = getattr(index, role).film_ids
    np.savez(directory / "people.npz", **arrays)


def load_person_index(directory: Path) -> PersonIndex:
    names = json.loads((directory / "people.json").read_text(encoding="utf-8"))
    with np.load(directory / "people.npz") as arrays:
        roles = {
            role: RoleIndex(
                {key: row for row, key in enumerate(names[role])},
                arrays[f"{role}_offsets"],
                arrays[f"{role}_film_ids"],
            )
            for role in ROLES
        }
    return PersonIndex(**roles)


def person_index_exists(directory: Path) -> bool:
    return (directory / "people.json").exists() and (directory / "people.npz").exists()
