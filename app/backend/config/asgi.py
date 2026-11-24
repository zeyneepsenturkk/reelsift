import logging
import os
from contextlib import AsyncExitStack

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

logger = logging.getLogger(__name__)

application = get_asgi_application()

# Geliştirmede uvicorn statik dosyaları kendisi sunmaz; admin CSS'i için gerekli.
from django.conf import settings  # noqa: E402  # ayarlar DJANGO_SETTINGS_MODULE'dan sonra okunmalı

if settings.DEBUG:
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

    application = ASGIStaticFilesHandler(application)


def load_mcp():
    """(MCP ASGI uygulaması, oturum yöneticisi) ya da MCP kapalı / yüklenemezse None."""
    if not settings.MCP_ENABLED:
        return None
    try:
        from apps.search import mcp_server

        return mcp_server.create_asgi_app()
    except Exception:  # MCP olmadan da uygulama açılmalı (paket yok, SDK uyumsuz...)
        logger.exception("MCP sunucusu yüklenemedi; /mcp kapalı")
        return None


def with_mcp(django_app, mcp_app):
    """`/mcp` yolunu MCP uygulamasına, geri kalanını Django uygulamasına yönlendirir."""

    async def app(scope, receive, send):
        if scope["type"] == "http" and scope["path"] in ("/mcp", "/mcp/"):
            return await mcp_app(scope, receive, send)
        return await django_app(scope, receive, send)

    return app


def with_lifespan(django_app, mcp_manager=None, **runtime_options):
    """Django'nun kendi ASGI uygulaması lifespan'ı desteklemez; agent grafı ve bağlantı havuzu
    burada, olay döngüsüyle aynı ömürde açılıp kapatılır (uvicorn `--lifespan on`)."""

    async def app(scope, receive, send):
        if scope["type"] != "lifespan":
            return await django_app(scope, receive, send)

        from apps.agent.runtime import open_runtime  # Django hazır olduktan sonra içe aktarılır

        runtime = open_runtime(**runtime_options)
        mcp_stack = AsyncExitStack()
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    await runtime.__aenter__()
                except Exception as exc:
                    logger.exception("Agent çalışma zamanı açılamadı")
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                    return
                if mcp_manager is not None:
                    try:
                        await mcp_stack.enter_async_context(mcp_manager.run())
                    except Exception:
                        logger.exception("MCP oturum yöneticisi açılamadı")
                await send({"type": "lifespan.startup.complete"})
                from apps.search.services.warmup import maybe_start_warmup

                maybe_start_warmup()  # arka plan iş parçacığı; açılışı bloklamaz
            elif message["type"] == "lifespan.shutdown":
                await mcp_stack.aclose()
                await runtime.__aexit__(None, None, None)
                await send({"type": "lifespan.shutdown.complete"})
                return

    return app


_mcp = load_mcp()
if _mcp is not None:
    application = with_mcp(application, _mcp[0])
application = with_lifespan(application, mcp_manager=_mcp[1] if _mcp else None)
