from typing import Annotated

from pydantic import AfterValidator


def is_db_unsafe(value: str) -> bool:
    """PostgreSQL'e (ya da UTF-8'e) yazılamayan metin: NUL baytı ve eşleşmemiş vekil karakter.

    İkisi de geçerli JSON/yol girdisi olarak gelebilir, ama sorguda/yazmada 500 üretir.
    """
    if "\x00" in value:
        return True
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


def _reject_unsafe(value: str) -> str:
    if is_db_unsafe(value):
        raise ValueError("Metin geçersiz karakter içeriyor.")
    return value


# Kullanıcıdan gelip veritabanına ya da sorguya giden her metin alanı bu tiple tanımlanır;
# geçersiz karakter 500 yerine 422 `validation_error` olur.
SafeText = Annotated[str, AfterValidator(_reject_unsafe)]
