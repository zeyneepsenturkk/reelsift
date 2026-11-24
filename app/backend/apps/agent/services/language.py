"""Metnin Türkçe olup olmadığına dair ucuz, belirlenimci denetim (dil modeli ve paket yok).

Editöre gösterilen gerekçe, başlık ve açıklama Türkçe olmalıdır; model bazen istemi dinlemeyip
başka dilde yazar. Kural tek yerdedir:
- Türkçeye özgü harf (ğ, ı, ş, İ; büyükleri) geçiyorsa Türkçedir. Bunlar başka büyük dillerde yok.
- ç, ö, ü Fransızca, Almanca vb. dillerde de var: tek başına yetmez, en az bir Türkçe işlev
  sözcüğüyle birlikte sayılır.
- Aksi halde en az 2 Türkçe işlev sözcüğü gerekir (başka dillerle çakışanlar listede yok: de, da,
  her, ya, ne, var, film).
- 4 sözcükten kısa metin yargılanmaz (Türkçe sayılır): "Gerekçe." ya da "Sessiz Gece" gibi
  kısa metinde dil ayırt edilemez; gerçek gerekçe ve açıklama bundan uzundur.
Bilinen sınırlar: Türkçe film adı (ör. "Kış Uykusu") içeren yabancı dil metni geçer; hiç ğ/ı/ş
içermeyen ve 2'den az işlev sözcüğü olan Türkçe metin (4+ sözcük) kalır.
"""

import re
from collections.abc import Sequence

MIN_FUNCTION_WORDS = 2
MIN_WORDS_TO_JUDGE = 4

STRONG_LETTERS = frozenset("ğışĞİŞ")
WEAK_LETTERS = frozenset("çöüÇÖÜ")

FUNCTION_WORDS = frozenset(
    {
        "ve", "bir", "bu", "şu", "için", "ile", "olarak", "gibi", "ama", "ancak", "çünkü",
        "kadar", "olan", "olduğu", "daha", "çok", "sonra", "ise", "ayrıca", "hem", "veya",
        "değil", "üzerine", "üzerinde", "içinde", "arasında", "bunun", "onun", "kendi",
    }
)  # fmt: skip

# Fiil çekimi: "geçiyor", "anlatıyor", "yürüyor"; başka dillerde bu sonlar yok.
VERB_ENDINGS = ("iyor", "ıyor", "uyor", "üyor")

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def _lower(text: str) -> str:
    # Python'un lower()'ı "I" -> "i" ve "İ" -> "i̇" yapar; Türkçe kurala göre çevrilir.
    return text.replace("İ", "i").replace("I", "ı").lower()


def looks_turkish(text: str) -> bool:
    tokens = _TOKEN.findall(_lower(text))
    if len(tokens) < MIN_WORDS_TO_JUDGE:
        return True
    if any(char in STRONG_LETTERS for char in text):
        return True
    hits = sum(1 for token in tokens if token in FUNCTION_WORDS or token.endswith(VERB_ENDINGS))
    if hits >= MIN_FUNCTION_WORDS:
        return True
    return hits >= 1 and any(char in WEAK_LETTERS for char in text)


# Cevaba sızan iç ifade: model, kendine verilen notlardan / talimattan söz eder. Kalıplar
# bilerek dar: "film notaları", "notlar aldım" gibi meşru cümleler yakalanmaz ("notlar" yalnız
# "notlara göre / notlarda / notlardan / notlarıma" biçimlerinde sayılır).
_LEAK_PATTERNS = re.compile(
    r"notlar(?:a göre|da|dan|ıma|ımda)\b"
    r"|bana verilen"
    r"|talimat(?:lar)?a göre|talimat(?:lar)?ım"
    r"|karşılaştırma yapm"
    r"|(?:söylemem|belirtmem) gerek"
    r"|veritabanına dayan"
    r"|<\s*/?\s*(?:notes|draft|collection|archive|outcome|facts|user_message)\b",
)

# Tırnak içi bölümler (düz, kıvrık, « », „ “) alıntıdır: denetlenmez.
_QUOTED = re.compile(r'"[^"]*"|“[^”]*”|„[^“”]*[“”]|«[^»]*»')
MIN_TITLE_CHARS = 3
# Bu kadar harften kısa metinde dil ayırt edilemez (adlar ve alıntılar çıkarıldıktan sonra):
# ~6-8 sözcük; altında `looks_turkish` yanılır ("Seçkide ... var. Hepsi güzel.").
MIN_LETTERS_TO_JUDGE_LANGUAGE = 40
_SENTENCE_END = frozenset(".!?…")
_QUOTE_CLOSER = {'"': '"', "“": "”", "«": "»", "„": "“"}


def _without_quotes_and_titles(text: str, titles: Sequence[str]) -> str:
    """Denetimden önce tırnak içi bölümler ve o turda modele verilen film adları çıkarılır:
    İngilizce adlar ve alıntılar `looks_turkish` ile Türkçe dışı sayılmasın."""
    text = _QUOTED.sub(" ", text)
    names = sorted({name for name in titles if len(name) >= MIN_TITLE_CHARS}, key=len, reverse=True)
    if names:
        pattern = "|".join(re.escape(_lower(name)) for name in names)
        text = re.sub(pattern, " ", _lower(text))
    return text


def leaks_internal_phrasing(
    text: str, titles: Sequence[str] = (), *, judge_language: bool = True
) -> bool:
    """Cevap, modele verilen notlardan / talimattan söz ediyor ya da Türkçe değil mi.
    `titles`: o turda modele verilen film adları (title, tr_title, original_title).
    `judge_language`: metnin bütününün Türkçe olup olmadığına da bakılır; kısa tek cümlede
    `looks_turkish` yanılabildiği için cümle düzeyinde kapatılır."""
    checked = _without_quotes_and_titles(text, titles)
    lowered = _lower(checked)
    return bool(_LEAK_PATTERNS.search(lowered)) or (
        judge_language
        and sum(len(token) for token in _TOKEN.findall(lowered)) >= MIN_LETTERS_TO_JUDGE_LANGUAGE
        and not looks_turkish(checked)
    )


def pop_sentence(buffer: str) -> tuple[str, str] | None:
    """Akan metnin tamamlanmış ilk cümlesi (sonundaki boşlukla) ve kalan metin. Cümle sonu
    işaretinden sonra boşluk gelmeli ("3.5" bölünmez) ve tırnak AÇIKKEN cümle bölünmez: iki
    cümlelik alıntı tek parça kalır. Tırnak hiç kapanmazsa `None` döner; akış sonunda kalan
    metin çağıran tarafça tek parça olarak denetlenir."""
    closers: list[str] = []
    index = 0
    while index < len(buffer):
        char = buffer[index]
        if closers and char == closers[-1]:
            closers.pop()
        elif char in _QUOTE_CLOSER and not (char == "“" and closers and closers[-1] == "“"):
            closers.append(_QUOTE_CLOSER[char])
        elif char in _SENTENCE_END and not closers:
            end = index
            while end + 1 < len(buffer) and buffer[end + 1] in _SENTENCE_END:
                end += 1
            gap = end + 1
            while gap < len(buffer) and buffer[gap].isspace():
                gap += 1
            if gap > end + 1:
                return buffer[:gap], buffer[gap:]
            index = end
        index += 1
    return None
