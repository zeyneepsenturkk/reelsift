import csv
import json
import pickle
import tempfile
import zlib
from pathlib import Path

import numpy as np

from apps.films.models import EMBEDDING_DIMENSIONS, Film, FilmChunk
from apps.films.services import sources
from apps.films.services.recipes import chunk_text

DATASET_COLUMNS = [
    "movie_id",
    "country",
    "imdb_id",
    "duration",
    "actors",
    "directors",
    "genre",
    "release_date",
    "wikipedia_link",
    "title",
    "popularity",
    "vote_average",
    "vote_count",
    "tmdb_id",
    "plot",
    "year",
]


def long_plot(sentence_count: int = 40) -> str:
    """~10 kelimelik cümlelerden oluşan, birden çok parçaya bölünen hikâye."""
    return " ".join(
        f"Character number {n} walks across the quiet town and meets somebody new."
        for n in range(sentence_count)
    )


def fake_vector(text: str) -> np.ndarray:
    """Metne bağlı, normalize ve deterministik sahte vektör (gerçek model testte kullanılmaz)."""
    rng = np.random.default_rng(zlib.crc32(text.encode("utf-8")))
    vector = rng.normal(size=EMBEDDING_DIMENSIONS)
    return (vector / np.linalg.norm(vector)).astype(np.float16)


def assert_vectors_equal(actual, expected) -> None:
    """Veritabanı vektörü float32 metnidir; float16 kaynakla küçük farkla karşılaştırılır."""
    np.testing.assert_allclose(
        np.asarray(actual, dtype=np.float32), np.asarray(expected, dtype=np.float32), atol=1e-6
    )


def fake_embedder(texts: list[str], max_seq_length: int) -> np.ndarray:
    return np.stack([fake_vector(text) for text in texts])


def dataset_row(**overrides) -> dict:
    row = {
        "movie_id": "Q1",
        "country": "United States, France",
        "imdb_id": "tt0000001",
        "duration": "100.0",
        "actors": "Actor One, Actor Two",
        "directors": "Director One",
        "genre": "drama film, war film",
        "release_date": "1999-05-01T00:00:00Z",
        "wikipedia_link": "https://en.wikipedia.org/wiki/Alpha",
        "title": "Alpha",
        "popularity": "3.5",
        "vote_average": "6.5",
        "vote_count": "120",
        "tmdb_id": "",
        "plot": "A short plot. It has two sentences.",
        "year": "1999",
    }
    row.update(overrides)
    return row


def tmdb_record(tmdb_id: int, movie_id, **overrides) -> dict:
    record = {
        "tmdb_id": tmdb_id,
        "movie_id": movie_id,
        "imdb_id": f"tt{tmdb_id:07d}",
        "title": f"TMDB {tmdb_id}",
        "original_title": f"Orig {tmdb_id}",
        "original_language": "en",
        "overview": f"Overview of {tmdb_id}.",
        "tagline": "A tagline.",
        "genres": ["Drama", "War"],
        "keywords": ["kw one", "kw two"],
        "release_date": "1999-06-02",
        "runtime": 111,
        "popularity": 9.5,
        "vote_average": 7.7,
        "vote_count": 5000,
        "poster_path": "/poster.jpg",
        "backdrop_path": "/backdrop.jpg",
        "production_countries": [{"iso": "US", "name": "United States of America"}],
        "spoken_languages": ["en"],
        "tr_title": "Türkçe Ad",
        "tr_overview": "Türkçe özet.",
        "adult": False,
        "status": "Released",
    }
    record.update(overrides)
    return record


def extra_record(tmdb_id: int, wikidata_id, **overrides) -> dict:
    record = tmdb_record(tmdb_id, wikidata_id, **overrides)
    record.update(
        {
            "wikidata_id": wikidata_id,
            "year": 2010,
            "plot": "Plot\n\nAn extra film plot. It is short.",
            "plot_kaynagi": "wikipedia:Plot",
            "wikipedia_link": "https://en.wikipedia.org/wiki/Extra",
            "in_archive_by_id": False,
        }
    )
    record.update(overrides)
    return record


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_archive(root: Path) -> dict:
    """Küçük, kendi kendine tutarlı bir `/data` kopyası yazar (4 veri seti + 4 ek film)."""
    root = Path(root)
    long = long_plot()
    plots = {
        "Q1": long,  # TMDB kaydı Wikidata kimliğiyle eşleşir; birden çok parça
        "Q2": "A short plot. It has two sentences.",  # TMDB kaydı yok
        "Q3": long_plot(30),  # TMDB kaydı yalnız tmdb_id ile eşleşir; hikâyesi yenilenir
        "Q4": "Another short plot here.",  # CSV'de tmdb_id var ama TMDB kaydı yok
    }
    rows = [
        dataset_row(movie_id="Q1", title="Alpha", plot=plots["Q1"], tmdb_id="101"),
        dataset_row(
            movie_id="Q2",
            title="Beta",
            plot=plots["Q2"],
            year="2001",
            imdb_id="",
            duration="",
            popularity="",
            vote_average="",
            vote_count="",
            directors="",
            actors="",
            release_date="http://www.wikidata.org/.well-known/genid/abc",
        ),
        dataset_row(
            movie_id="Q3",
            title="Gamma",
            plot=plots["Q3"],
            tmdb_id="303",
            year="1985",
            imdb_id="tt0000003",
        ),
        dataset_row(
            movie_id="Q4",
            title="Delta",
            plot=plots["Q4"],
            tmdb_id="404",
            year="1970",
            imdb_id="tt0000004",
        ),
    ]
    (root / "dataset").mkdir(parents=True, exist_ok=True)
    with open(root / sources.DATASET_CSV, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    write_jsonl(
        root / sources.TMDB_JSONL,
        [
            tmdb_record(101, "Q1"),
            tmdb_record(303, "Q999", runtime=0, tagline="", keywords=[]),
            tmdb_record(555, ["Q555", "Q556"]),
        ],
    )
    write_jsonl(
        root / sources.EXTRA_FILMS_JSONL,
        [
            extra_record(1001, "Q100"),
            extra_record(1002, None, plot=None, plot_kaynagi=None, year=None, release_date=""),
            # Arşivdeki Q4 ile imdb_id birebir aynı: Q4'e işlenir, profili Q4'e bağlanır.
            extra_record(1003, "Q103", in_archive_by_id=True, imdb_id="tt0000004"),
            # Aynı Wikidata kimliği arşivde var: Q2'ye işlenir.
            extra_record(1004, "Q2"),
            # Arşivde karşılığı bulunamayan, in_archive_by_id işaretli kayıt: listelenir.
            extra_record(1005, "Q105", in_archive_by_id=True, imdb_id="tt9999999"),
        ],
    )
    write_jsonl(
        root / sources.PLOT_RENEWALS_JSONL,
        [
            {
                "movie_id": "Q3",
                "eski_uzunluk": 10,
                "yeni_plot": "Plot\nA renewed story. It is longer now.",
                "yeni_uzunluk": 40,
            }
        ],
    )
    write_jsonl(
        root / sources.REVIEWS_JSONL,
        [
            {
                "tmdb_id": 101,
                "movie_id": "Q1",
                "toplam_inceleme": 2,
                "incelemeler": [
                    {
                        "icerik": "Great.",
                        "puan": 9.0,
                        "tarih": "2024-07-07T04:49:42Z",
                        "url": "https://x.test/r/1",
                    },
                    {
                        "icerik": "Okay.",
                        "puan": None,
                        "tarih": "bozuk",
                        "url": "https://x.test/r/2",
                    },
                ],
            },
            {
                "tmdb_id": 9,
                "movie_id": "Q77",
                "toplam_inceleme": 1,
                "incelemeler": [
                    {
                        "icerik": "Orphan.",
                        "puan": 5.0,
                        "tarih": "2024-07-07T04:49:42Z",
                        "url": "https://x.test/r/3",
                    }
                ],
            },
        ],
    )
    profile = {
        "themes": ["theme a", "theme b"],
        "mood": ["warm", "bittersweet", "tense"],
        "tone": "A warm tone.",
        "pacing": "medium",
        "setting": {"place": "Paris", "period": "1999"},
        "narrative": ["ensemble cast"],
        "for_viewers": "For viewers looking for warmth.",
        "tr_pitch": "",
        "evidence": "rich",
    }
    write_jsonl(
        root / sources.PROFILES_JSONL,
        [
            {"id": "Q1", "p": profile, "kaynak": "toplu"},
            {
                "id": "Q2",
                "p": {k: v for k, v in profile.items() if k != "evidence"},
                "kaynak": "deneme",
            },
            {"id": "Q100", "p": profile, "kaynak": "toplu"},
            {"id": "Q88", "p": profile, "kaynak": "toplu"},
            {"id": "Q4", "p": {**profile, "tone": "Q4 own tone."}, "kaynak": "toplu"},
            {"id": "Q103", "p": {**profile, "tone": "Extra tone."}, "kaynak": "toplu"},
        ],
    )

    film_rows, texts = [], []
    for row_number, row in enumerate(rows):
        for text in chunk_text(row["plot"]):
            film_rows.append(row_number)
            texts.append(text)
    (root / "vektor" / "chunk").mkdir(parents=True, exist_ok=True)
    with open(root / sources.CHUNK_TEXTS_PKL, "wb") as handle:
        pickle.dump((np.array(film_rows), texts), handle)
    vectors = np.stack([fake_vector(f"chunk-{n}") for n in range(len(texts))])
    (root / "vektor" / "chunk-onekli").mkdir(parents=True, exist_ok=True)
    # Gerçek veri gibi 8 dosyaya bölünür (bazıları boş kalabilir).
    for number, part in enumerate(np.array_split(vectors, sources.CHUNK_VECTOR_FILE_COUNT)):
        np.save(root / sources.CHUNK_VECTOR_FILES.format(n=number), part)
    (root / "vektor" / "tmdb-kart").mkdir(parents=True, exist_ok=True)
    np.save(
        root / sources.CARD_VECTORS_NPY,
        np.stack([fake_vector(f"card-{n}") for n in range(len(rows))]),
    )
    (root / "vektor" / "hazir").mkdir(parents=True, exist_ok=True)
    np.save(
        root / sources.DATASET_IDS_NPY,
        np.array([r["movie_id"] for r in rows], dtype=object),
        allow_pickle=True,
    )
    return {"rows": rows, "texts": texts, "film_rows": film_rows, "chunk_vectors": vectors}


def make_archive_root() -> tuple[tempfile.TemporaryDirectory, Path, dict]:
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    return temp, root, write_archive(root)


def make_film(wikidata_id: str = "Q1", **overrides) -> Film:
    fields = {"wikidata_id": wikidata_id, "title": f"Film {wikidata_id}", "year": 2000}
    fields.update(overrides)
    return Film.objects.create(**fields)


def make_chunk(
    film: Film, position: int = 0, text: str = "Some text.", embedding=None
) -> FilmChunk:
    return FilmChunk.objects.create(
        film=film,
        position=position,
        text=text,
        embedding=fake_vector(text) if embedding is None else embedding,
    )
