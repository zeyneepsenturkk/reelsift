from django.contrib.auth import authenticate, login, logout

from apps.core.exceptions import ServiceError
from apps.core.text import is_db_unsafe


def invalid_credentials() -> ServiceError:
    # Kullanıcı yok, şifre yanlış ve kullanıcı pasif: AYNI cevap; hesap varlığı sızmasın.
    return ServiceError("Kullanıcı adı ya da şifre yanlış.", "invalid_credentials", 401)


def log_in(request, username: str, password: str):
    # NUL ve eşleşmemiş vekil karakter sorguda hata verir (500); zaten geçerli bir ad olamaz.
    if is_db_unsafe(username) or is_db_unsafe(password):
        raise invalid_credentials()
    # ModelBackend var olmayan kullanıcıda da şifre özetler (zamanlama farkı yok), pasifi reddeder.
    user = authenticate(request, username=username, password=password)
    if user is None:
        raise invalid_credentials()
    # Oturum anahtarı ve CSRF belirteci yenilenir (oturum sabitleme saldırısına karşı).
    login(request, user)
    return user


def log_out(request) -> None:
    logout(request)
