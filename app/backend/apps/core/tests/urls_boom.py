from django.http import Http404
from django.urls import path


def boom(request):
    raise RuntimeError("gizli-ic-ayrinti")


async def boom_async(request):
    raise RuntimeError("gizli-ic-ayrinti")


def missing(request):
    raise Http404


# `/api/` altı ve dışı: ara katmanın yalnız API'yi tek tip JSON 500'e çevirdiğini sınamak için.
urlpatterns = [
    path("api/boom/", boom),
    path("api/boom-async/", boom_async),
    path("api/missing/", missing),
    path("disarida/", boom),
]
