import re

from apps.accounts.schemas import UserOut

MAX_INITIALS = 2
_NAME_SEPARATORS = re.compile(r"[\s._-]+")


def display_name(user) -> str:
    return user.get_full_name().strip() or user.username


def _initial(word: str) -> str:
    first = next((char for char in word if char.isalnum()), "")
    # Python "i".upper() == "I" verir; Türkçede noktalı büyük harf "İ" olmalı.
    return "İ" if first == "i" else first.upper()[:1]


def initials(user) -> str:
    """Ad ve soyadın baş harfleri; ad soyad boşsa kullanıcı adının sözcüklerinden."""
    source = user.get_full_name().strip() or user.username
    words = [word for word in _NAME_SEPARATORS.split(source) if word]
    picked = words if len(words) <= MAX_INITIALS else [words[0], words[-1]]
    return "".join(_initial(word) for word in picked)


def serialize_user(user) -> UserOut:
    return UserOut(
        id=user.pk,
        username=user.username,
        display_name=display_name(user),
        initials=initials(user),
    )
