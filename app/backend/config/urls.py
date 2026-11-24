from django.contrib import admin
from django.urls import include, path, re_path

from config.api import api, api_not_found

urlpatterns = [
    path("admin/", admin.site.urls),
    # Akan cevap ninja dışında düz async view'dır; ninja'nın /api/ yolundan önce gelmelidir.
    path("api/", include("apps.agent.urls")),
    # ninja'nın kök görünümü Django'nun HTML 404'ünü verir; tam `/api/` yolu tek tip JSON 404 alsın.
    path("api/", api_not_found),
    path("api/", api.urls),
    re_path(r"^api/", api_not_found),
]
