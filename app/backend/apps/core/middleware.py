import logging

from django.core.exceptions import BadRequest, PermissionDenied, SuspiciousOperation
from django.http import Http404, JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

# Django bunları kendi 4xx cevabına çevirir; 500 sayılmaz.
HANDLED_BY_DJANGO = (Http404, PermissionDenied, SuspiciousOperation, BadRequest)


class ApiMethodNotAllowedMiddleware(MiddlewareMixin):
    """`/api/` altında desteklenmeyen yöntem, Django'nun boş 405'i yerine tek tip hata alır.

    405'i ninja uçları da düz Django view'ları da (`require_POST`) üretir; tek yerde çevirmek iş
    mantığına dokunmaz. `Allow` başlığı korunur.
    """

    def process_response(self, request, response):
        if response.status_code != 405 or not request.path.startswith("/api/"):
            return response
        converted = JsonResponse(
            {"detail": "Bu yöntem desteklenmiyor.", "code": "method_not_allowed"}, status=405
        )
        if "Allow" in response:
            converted["Allow"] = response["Allow"]
        return converted


class ApiUnexpectedErrorMiddleware(MiddlewareMixin):
    """`/api/` altında görünümden çıkan beklenmeyen hata tek tip JSON 500 olur.

    Ninja uçlarının hatasını ninja kendisi çevirir; bu, düz Django görünümleri (akan cevap) içindir.
    Yoksa DEBUG açıkken Django hata ayrıntısını HTML gösterir. İç ayrıntı yalnız loga yazılır.
    """

    def process_exception(self, request, exception):
        if not request.path.startswith("/api/") or isinstance(exception, HANDLED_BY_DJANGO):
            return None
        logger.error("Beklenmeyen API hatası: %s", request.path, exc_info=exception)
        return JsonResponse(
            {"detail": "Beklenmeyen bir hata oluştu.", "code": "server_error"}, status=500
        )
