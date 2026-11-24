"""Editöre görünen adım ve not metinleri. Hepsi kodda, gerçek sayılardan üretilir:
model adım metni yazmaz, sayı uydurulmaz."""

from apps.agent.schemas import MAX_TARGET, ParsedRequest
from apps.curation.services.countries import country_name_tr
from apps.curation.services.genres import genre_name_tr

# Sayının okunuşunun son sesine göre belirtme hâli eki ("31'i", "10'u", "6'yı").
_UNITS = {1: "i", 2: "yi", 3: "ü", 4: "ü", 5: "i", 6: "yı", 7: "yi", 8: "i", 9: "u"}
_TENS = {
    1: "u",  # on
    2: "yi",  # yirmi
    3: "u",  # otuz
    4: "ı",  # kırk
    5: "yi",  # elli
    6: "ı",  # altmış
    7: "i",  # yetmiş
    8: "i",  # seksen
    9: "ı",  # doksan
}


def accusative_suffix(number: int) -> str:
    """0-999 aralığı için sayıya gelen -i hâli eki (apostrofsuz): 31 -> "i", 10 -> "u"."""
    number = abs(number)
    if number == 0:
        return "ı"  # sıfır
    if number % 10:
        return _UNITS[number % 10]
    if number % 100:
        return _TENS[(number // 10) % 10]
    return "ü"  # yüz ve katları (bin için "i" gerekir; bu aralığın dışında kalır)


def acc(number: int) -> str:
    """ "31'i", "10'u" gibi: sayı + apostrof + ek."""
    return f"{number}'{accusative_suffix(number)}"


RANK_LABELS = {"rating": "en yüksek puanlılar", "popularity": "en çok oylananlar"}


def request_summary(request: ParsedRequest) -> str:
    """Çözümlenen isteğin editöre gösterilen kısa özeti (yalnız gerçek filtrelerden)."""
    filters = request.filters
    parts = []
    if request.people:
        parts.append(", ".join(person.name for person in request.people))
    if filters.year_min and filters.year_max:
        parts.append(f"{filters.year_min}-{filters.year_max} arası")
    elif filters.year_min:
        parts.append(f"{filters.year_min} ve sonrası")
    elif filters.year_max:
        parts.append(f"{filters.year_max} ve öncesi")
    if filters.countries:
        parts.append(", ".join(country_name_tr(name) for name in filters.countries))
    if filters.max_vote_count is not None:
        parts.append("az bilinen")
    if request.genres:
        parts.append(", ".join(genre_name_tr(name) for name in request.genres))
    if request.rank_by:
        parts.append(RANK_LABELS[request.rank_by])
    if not parts:
        if not request.target_stated:
            # Sayıyı editör söylemedi; ona mal edilmez.
            return "Bir film seçkisi istiyorsun."
        return f"{request.target_count} filmlik bir seçki istiyorsun."
    return " · ".join(parts)


APPROVED_UNTOUCHED_NOTICE = "Onayladığın seçkiye dokunmadım; bu yeni bir taslak."


def count_note(count: int, request: ParsedRequest) -> str:
    """`respond` istemine giden sayı olgusu (kodla hesaplanır, modele çıkarım bırakılmaz).
    Konusuz, etiketli olgu cümleleri: model "editör istedi" diye üçüncü kişiye çevirmesin.
    İstenen sayıyla karşılaştırma yalnız editör sayıyı söylediyse verilir."""
    if not request.target_stated:
        return f"Films in the saved collection: {count}."
    target = request.target_count
    head = f"Requested number of films: {target}. Films in the saved collection: {count}."
    if count >= target:
        return f"{head} The request is fully met; nothing is missing."
    return f"{head} Missing: {target - count}."


def change_note(delta: int, before: int, count: int) -> str:
    """ "N tane daha ekle / N film çıkar" turunun tek sayı olgusu: istenen değişim, gerçekleşen
    değişim ve taslaktaki güncel sayı (`before`: taslağın önceki film sayısı)."""
    if delta > 0:
        note = (
            f"Films requested to add: {delta}. Films added: {max(count - before, 0)}. "
            f"Films in the saved collection now: {count}."
        )
        if before >= MAX_TARGET:
            note += f" A collection holds at most {MAX_TARGET} films, so no film could be added."
        return note
    return (
        f"Films requested to remove: {-delta}. Films removed: {max(before - count, 0)}. "
        f"Films in the saved collection now: {count}."
    )


NOTES_HEADER = (
    "Facts for your reply. Say them to the editor as your own sentences, speaking to them "
    'directly as "sen".'
)


def replace_note(old_title: str | None, new_title: str | None) -> str:
    """Film değiştirme turunun tek olgusu: hangi film çıktı, hangisi girdi."""
    if old_title and new_title:
        return (
            f"Swap done: {old_title} was taken out and {new_title} was put in its place. "
            "All other films stay as they were."
        )
    return "One film was swapped for another. All other films stay as they were."


RELAXED_FILTER_LABELS = {
    "year": "yıl",
    "year_min": "yıl",
    "year_max": "yıl",
    "countries": "ülke",
    "country": "ülke",
    "max_vote_count": "oy sayısı",
    "vote_count": "oy sayısı",
}


def relaxed_filter_notice(names: tuple[str, ...]) -> str | None:
    """Arama servisinin kendiliğinden kaldırdığı filtreler için editöre not."""
    if not names:
        return None
    labels = []
    for name in names:
        label = RELAXED_FILTER_LABELS.get(name, name)
        if label not in labels:
            labels.append(label)
    joined = ", ".join(labels)
    return (
        f"Arşivde bu {joined} filtresiyle çok az film kaldığı için filtreyi gevşettim; "
        "sonuçlar bu ölçüte tam uymayabilir."
    )


def people_filter_notice(names: tuple[str, ...]) -> str | None:
    """Kişi evreninde filtre, kişinin hiç filmi kalmadığı için uygulanmadıysa editöre not."""
    if not names:
        return None
    labels = []
    for name in names:
        label = RELAXED_FILTER_LABELS.get(name, name)
        if label not in labels:
            labels.append(label)
    return (
        f"Aradığın kişinin bu {', '.join(labels)} filtresiyle hiç filmi kalmadığı için "
        "filtreyi uygulamadım; sonuçlar bu ölçüte uymayabilir."
    )


def universe_note(count: int, available: int) -> str | None:
    """Yalnız kişi isteğinde (sayı söylenmedi) kişinin filmlerinin ne kadarının koleksiyonda
    olduğu; ikisi de kodla hesaplanmış sayılardır."""
    if available > MAX_TARGET:
        if count >= MAX_TARGET:
            return f"Only the first {MAX_TARGET} of the {available} films are in the collection."
        return None
    if count >= available:
        return f"All {available} films of the archive for this request are in the collection."
    return None


def search_done(count: int) -> tuple[str, str]:
    return "Arşivde dolaştım.", f"{count} aday ayırdım."


def read_done(fit: int) -> tuple[str, str]:
    if fit == 0:
        return "Hikâyelerini tek tek okudum.", "Hiçbiri tam bu havayı taşımıyor."
    return "Hikâyelerini tek tek okudum.", f"{acc(fit)} gerçekten bu havayı taşıyor."


def read_skipped(count: int) -> tuple[str, str]:
    """Yalnız kişi isteğinde eleme yapılmaz: kişinin filmleri veritabanından olduğu gibi alınır."""
    if not count:
        return "Arşivden yeni film çıkmadı.", ""
    return "Filmleri arşivden aldım.", f"{count} film."


def people_notes(
    people_found: list[tuple[str, int]], request: ParsedRequest, available: int
) -> list[str]:
    """Kişi aramasının olguları (`respond` notları). Adlar çağıran tarafta etkisizleştirilmiş gelir.
    `available`: aramanın bu istek için bulduğu film sayısı (filtreler sonrası)."""
    notes = []
    for name, count in people_found:
        if count:
            notes.append(f"The archive has {count} film(s) for {name}.")
        else:
            notes.append(f"The archive has no film under the name {name}.")
    if people_found and all(count == 0 for _, count in people_found):
        notes.append("The editor can check how the name is spelled or ask by theme instead.")
    elif request.target_stated and request.target_count > available:
        notes.append(
            f"Requested number of films: {request.target_count}. "
            f"Films in the archive for this request: {available}."
        )
    return notes
