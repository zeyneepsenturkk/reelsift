"""Yeterli uygun film çıkmayınca filtre gevşetme sırası (saf mantık, modelsiz)."""

from apps.agent.schemas import ParsedRequest

YEAR_WIDEN_STEP = 5

# Sıra: oy sayısı, yıl aralığı (+-5), ülke. Her adım en çok bir kez uygulanır.
RELAX_ORDER = ("vote_count", "year", "country")

RELAX_NOTICES = {
    "vote_count": (
        "Yeterince uygun film çıkmadığı için 'az bilinen' sınırını kaldırdım; "
        "listede daha tanınmış filmler de olabilir."
    ),
    "year": (
        f"Yeterince uygun film çıkmadığı için yıl aralığını iki yandan {YEAR_WIDEN_STEP} yıl "
        "genişlettim."
    ),
    "country": "Yeterince uygun film çıkmadığı için ülke filtresini kaldırdım.",
}
ALT_QUERY_NOTICE = "Yeterince uygun film çıkmadığı için aramayı başka bir cümleyle yeniden denedim."


def next_relaxation(request: ParsedRequest, applied: list[str]) -> tuple[ParsedRequest, str] | None:
    """Sıradaki uygulanabilir gevşetme; kalmadıysa None (o zaman model alternatif cümle yazar)."""
    filters = request.filters
    for key in RELAX_ORDER:
        if key in applied:
            continue
        if key == "vote_count" and filters.max_vote_count is not None:
            relaxed = filters.model_copy(update={"max_vote_count": None})
        elif key == "year" and (filters.year_min is not None or filters.year_max is not None):
            relaxed = filters.model_copy(
                update={
                    "year_min": None
                    if filters.year_min is None
                    else filters.year_min - YEAR_WIDEN_STEP,
                    "year_max": None
                    if filters.year_max is None
                    else filters.year_max + YEAR_WIDEN_STEP,
                }
            )
        elif key == "country" and filters.countries:
            relaxed = filters.model_copy(update={"countries": []})
        else:
            continue
        return request.model_copy(update={"filters": relaxed}), key
    return None
