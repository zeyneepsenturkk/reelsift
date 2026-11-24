"""Film türlerinin Türkçe adları (TMDB türleri ve modelin yazabileceği yaygın eş adlar)."""

GENRE_NAMES_TR = {
    "action": "aksiyon",
    "adventure": "macera",
    "animation": "animasyon",
    "comedy": "komedi",
    "crime": "suç",
    "documentary": "belgesel",
    "drama": "dram",
    "family": "aile",
    "fantasy": "fantastik",
    "history": "tarih",
    "horror": "korku",
    "music": "müzik",
    "mystery": "gizem",
    "romance": "romantik",
    "science fiction": "bilim kurgu",
    "tv movie": "TV filmi",
    "thriller": "gerilim",
    "war": "savaş",
    "western": "western",
    "sci-fi": "bilim kurgu",
    "musical": "müzikal",
    "biography": "biyografi",
    "biopic": "biyografi",
    "sport": "spor",
    "sports": "spor",
    "noir": "kara film",
    "film noir": "kara film",
    "romantic comedy": "romantik komedi",
    "black comedy": "kara komedi",
    "dark comedy": "kara komedi",
    "historical": "tarih",
    "psychological": "psikolojik",
    "psychological thriller": "psikolojik gerilim",
    "political thriller": "siyasi gerilim",
    "political": "siyasi",
    "crime drama": "suç dramı",
    "neo-noir": "neo-noir",
    "road movie": "yol filmi",
    "melodrama": "melodram",
    "satire": "hiciv",
    "suspense": "gerilim",
}


def genre_name_tr(name: str) -> str:
    """Büyük / küçük harf ve baştaki / sondaki boşluk fark etmez; karşılığı olmayan ad olduğu
    gibi kalır."""
    return GENRE_NAMES_TR.get(name.strip().lower(), name)
