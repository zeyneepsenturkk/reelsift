import logging
import os
from importlib.util import find_spec

from django.db import Error as DatabaseError
from django.db import connection

from apps.core.exceptions import ServiceError
from apps.core.schemas import GpuOut, HealthOut

logger = logging.getLogger(__name__)

DATA_PATH = "/data"
MODELS_PATH = "/models"


def check_database() -> str:
    """Veritabanına bağlanır, pgvector eklentisinin sürümünü döndürür."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            row = cursor.fetchone()
    except DatabaseError as exc:
        logger.error("Veritabanı sağlık kontrolü başarısız: %s", exc)
        raise ServiceError(
            "Veritabanına bağlanılamadı.", "database_unavailable", status_code=503
        ) from exc

    if row is None:
        raise ServiceError("pgvector eklentisi kurulu değil.", "pgvector_missing", status_code=503)
    return row[0]


def check_gpu() -> GpuOut:
    """Ekran kartı görünürlüğü bilgi amaçlıdır; yokluğu sağlık hatası sayılmaz."""
    if find_spec("torch") is None:
        return GpuOut(available=False)

    import torch

    if not torch.cuda.is_available():
        return GpuOut(available=False)
    return GpuOut(available=True, name=torch.cuda.get_device_name(0))


def check_mount(path: str) -> bool:
    return os.path.ismount(path)


def get_health() -> HealthOut:
    pgvector_version = check_database()
    return HealthOut(
        status="ok",
        database=True,
        pgvector_version=pgvector_version,
        gpu=check_gpu(),
        data_mounted=check_mount(DATA_PATH),
        models_mounted=check_mount(MODELS_PATH),
    )
