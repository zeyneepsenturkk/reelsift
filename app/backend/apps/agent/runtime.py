"""Graf, bağlantı havuzu ve LangGraph kontrol noktası kaydedicisinin yaşam döngüsü.

ASGI lifespan sarmalayıcısı (`config/asgi.py`) açılışta `open_runtime`'ı girer, kapanışta çıkar:
havuz ve graf aynı olay döngüsünde açılmalıdır. Kontrol noktası tabloları Django modeli
değildir; `setup()` açılışta, tekrar çalıştırılabilir biçimde (idempotent) kurar.
"""

import logging
from contextlib import asynccontextmanager

from django.conf import settings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apps.agent.graph import Deps, build_graph
from apps.agent.services.llm import SettingsLLM
from apps.agent.services.retrieval import SearchServiceRetrieval
from apps.core.exceptions import ServiceError

logger = logging.getLogger(__name__)

_graph = None


def get_graph():
    if _graph is None:
        raise ServiceError(
            "Asistan şu an hazır değil. Biraz sonra tekrar dene.", "server_error", 503
        )
    return _graph


def set_graph(graph) -> None:
    """Testler ve `open_runtime` kullanır."""
    global _graph
    _graph = graph


def connection_info(database: dict | None = None) -> str:
    database = database or settings.DATABASES["default"]
    return make_conninfo(
        dbname=database["NAME"],
        user=database["USER"],
        password=database["PASSWORD"],
        host=database["HOST"],
        port=database["PORT"],
    )


@asynccontextmanager
async def open_pool(database: dict | None = None):
    pool = AsyncConnectionPool(
        connection_info(database),
        min_size=1,
        max_size=5,
        open=False,
        # autocommit ve dict_row kaydedicinin gerektirdiği ayarlardır.
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
    )
    await pool.open()
    try:
        yield pool
    finally:
        await pool.close()


@asynccontextmanager
async def open_runtime(*, llm=None, retrieval=None):
    async with open_pool() as pool:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        graph = build_graph(
            Deps(llm=llm or SettingsLLM(), retrieval=retrieval or SearchServiceRetrieval()),
            saver,
        )
        set_graph(graph)
        logger.info("Agent grafı hazır")
        try:
            yield graph
        finally:
            set_graph(None)
