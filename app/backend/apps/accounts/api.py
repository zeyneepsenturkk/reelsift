import logging

from django.middleware.csrf import get_token
from ninja import Router

from apps.accounts.schemas import LoginIn, UserOut
from apps.accounts.services import sessions
from apps.accounts.services.profiles import serialize_user
from apps.core.auth import enforce_csrf
from apps.core.exceptions import ServiceError
from apps.core.throttles import LoginThrottle

logger = logging.getLogger(__name__)

router = Router(tags=["accounts"])


@router.get("/auth/me", response=UserOut, auth=None)
def me(request):
    # Arayüz bu çerezi yazan isteklerin başlığına kopyalar; girişsiz cevapta da kurulur.
    get_token(request)
    if not request.user.is_authenticated:
        raise ServiceError("Giriş yapmalısın.", "not_authenticated", 401)
    return serialize_user(request.user)


@router.post("/auth/login", response=UserOut, auth=None, throttle=[LoginThrottle("10/m")])
def login(request, payload: LoginIn):
    enforce_csrf(request)
    try:
        user = sessions.log_in(request, payload.username, payload.password)
    except ServiceError:
        # Kullanıcı adı ve şifre loglanmaz; yalnız deneme olduğu kaydedilir.
        logger.warning("Başarısız giriş denemesi (adres: %s)", request.META.get("REMOTE_ADDR"))
        raise
    return serialize_user(user)


@router.post("/auth/logout", response={204: None}, auth=None)
def logout(request):
    enforce_csrf(request)
    sessions.log_out(request)
    return 204, None
