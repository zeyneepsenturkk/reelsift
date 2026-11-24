import logging

from django.http import Http404
from django.views.decorators.csrf import csrf_exempt
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError

from apps.accounts.api import router as accounts_router
from apps.agent.api import router as agent_router
from apps.chats.api import router as chats_router
from apps.core.api import router as core_router
from apps.core.exceptions import ServiceError
from apps.curation.api import router as curation_router

logger = logging.getLogger(__name__)

# Şema ve belge sayfaları kapalı: `/api/openapi.json` ve `/api/docs` girişsiz açık kalıyordu;
# sözleşmedeki girişsiz uçlar dışında her uç girişli olmalı.
api = NinjaAPI(urls_namespace="api", docs_url=None, openapi_url=None)


def error_response(request, detail: str, code: str, status: int):
    return api.create_response(request, {"detail": detail, "code": code}, status=status)


@api.exception_handler(ServiceError)
def handle_service_error(request, exc: ServiceError):
    return error_response(request, exc.message, exc.code, exc.status_code)


@api.exception_handler(ValidationError)
def handle_validation_error(request, exc: ValidationError):
    return error_response(request, "Geçersiz istek.", "validation_error", 422)


@api.exception_handler(AuthenticationError)
def handle_authentication_error(request, exc: AuthenticationError):
    return error_response(request, "Giriş yapmalısın.", "not_authenticated", 401)


# HttpError mesajları (ninja'nın İngilizce iç metinleri) istemciye yazılmaz; sabit metin kullanılır.
HTTP_ERRORS = {
    # Ayrıştırılamayan JSON gövdesi ninja'da 400 olarak gelir; sözleşmede 422 validation_error.
    400: (422, "Geçersiz istek.", "validation_error"),
    # SessionAuth'un ve enforce_csrf'in CSRF reddi.
    403: (
        403,
        "Güvenlik doğrulaması başarısız. Sayfayı yenileyip tekrar dene.",
        "forbidden",
    ),
    404: (404, "Bulunamadı.", "not_found"),
    429: (429, "Çok fazla deneme yaptın. Biraz bekleyip tekrar dene.", "rate_limited"),
}


@api.exception_handler(HttpError)
def handle_http_error(request, exc: HttpError):
    status, detail, code = HTTP_ERRORS.get(
        exc.status_code, (exc.status_code, "İstek işlenemedi.", "http_error")
    )
    return error_response(request, detail, code, status)


@api.exception_handler(Http404)
def handle_not_found(request, exc: Http404):
    return error_response(request, "Bulunamadı.", "not_found", 404)


@api.exception_handler(Exception)
def handle_unexpected(request, exc: Exception):
    logger.exception("Beklenmeyen API hatası")
    return error_response(request, "Beklenmeyen bir hata oluştu.", "server_error", 500)


api.add_router("", core_router)
api.add_router("", accounts_router)
api.add_router("", chats_router)
api.add_router("", curation_router)
api.add_router("", agent_router)


# Kimlik gerektirmeyen catch-all: CSRF denetimi POST'ta HTML 403 döndürüp tek tip
# hata biçimini bozardı; yetki gerektiren hiçbir işlem yapmadığı için muaf tutulur.
@csrf_exempt
def api_not_found(request, path=""):
    """/api/ altında hiçbir yola uymayan istekler de tek tip hata biçimini alsın."""
    return error_response(request, "Bulunamadı.", "not_found", 404)
