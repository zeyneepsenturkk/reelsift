from ninja import Router

from apps.core.schemas import ErrorOut, HealthOut
from apps.core.services import health

router = Router(tags=["core"])


@router.get("/health", response={200: HealthOut, 503: ErrorOut}, auth=None)
def get_health(request):
    return health.get_health()
