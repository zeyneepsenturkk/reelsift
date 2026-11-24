from django.http import JsonResponse
from django.views.csrf import csrf_failure as default_csrf_failure


def csrf_failure(request, reason=""):
    """API istekleri tek tip hata biçimini alır; yönetim paneli varsayılan sayfayı."""
    if not request.path.startswith("/api/"):
        return default_csrf_failure(request, reason=reason)
    return JsonResponse(
        {
            "detail": "Güvenlik doğrulaması başarısız. Sayfayı yenileyip tekrar dene.",
            "code": "forbidden",
        },
        status=403,
    )
