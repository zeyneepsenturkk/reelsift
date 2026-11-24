from ninja.errors import HttpError
from ninja.security import SessionAuth
from ninja.utils import check_csrf

# Oturum çerezi + CSRF; giriş yoksa 401, CSRF hatası 403 (config/api.py tek tip cevaba çevirir).
session_auth = SessionAuth()


def enforce_csrf(request) -> None:
    """Girişsiz çağrılan yazan uçlar için CSRF denetimi (ninja bunları kendiliğinden denetlemez)."""
    if check_csrf(request):
        raise HttpError(403, "CSRF check Failed")
