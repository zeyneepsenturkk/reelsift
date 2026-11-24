import logging
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

logger = logging.getLogger(__name__)

application = get_asgi_application()

# Geliştirmede uvicorn statik dosyaları kendisi sunmaz; admin CSS'i için gerekli.
from django.conf import settings  # noqa: E402  # ayarlar DJANGO_SETTINGS_MODULE'dan sonra okunmalı

if settings.DEBUG:
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

    application = ASGIStaticFilesHandler(application)


def with_lifespan(django_app, **runtime_options):
    """Django'nun kendi ASGI uygulaması lifespan'ı desteklemez; agent grafı ve bağlantı havuzu
    burada, olay döngüsüyle aynı ömürde açılıp kapatılır (uvicorn `--lifespan on`)."""

    async def app(scope, receive, send):
        if scope["type"] != "lifespan":
            return await django_app(scope, receive, send)

        from apps.agent.runtime import open_runtime  # Django hazır olduktan sonra içe aktarılır

        runtime = open_runtime(**runtime_options)
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    await runtime.__aenter__()
                except Exception as exc:
                    logger.exception("Agent çalışma zamanı açılamadı")
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                    return
                await send({"type": "lifespan.startup.complete"})
                from apps.search.services.warmup import maybe_start_warmup

                maybe_start_warmup()  # arka plan iş parçacığı; açılışı bloklamaz
            elif message["type"] == "lifespan.shutdown":
                await runtime.__aexit__(None, None, None)
                await send({"type": "lifespan.shutdown.complete"})
                return

    return app


application = with_lifespan(application)
