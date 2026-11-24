from django.http import HttpResponse
from django.urls import path
from django.views.decorators.http import require_GET

# `/api/` dışında 405 veren bir görünüm; 405 çevirisinin yalnız API'ye uygulandığını sınamak için.
urlpatterns = [path("baska/", require_GET(lambda request: HttpResponse("ok")))]
