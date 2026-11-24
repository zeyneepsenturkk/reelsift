"""Arşivi ve arama hattını MCP (Model Context Protocol) ile dış yapay zekâ asistanlarına açan,
yalnız okuyan sunucu.

Sunucu çalışan backend sürecinin içinde `/mcp` adresinde (streamable HTTP) yaşar; ısınmış arama
modellerini ve kelime indeksini paylaşır. İki araç vardır: `film_ara` (mevcut arama hattı: vektör +
BM25 + RRF + yeniden sıralama; dil modeli çağırmaz) ve `film_getir` (tek filmin ayrıntısı).
Sohbet, seçki ve kullanıcı verisine dokunan araç yoktur.

Araç gövdeleri saf, eşzamanlı fonksiyonlardır (`search_films`, `get_film`); FastMCP kaydı ince bir
katmandır ve eşzamanlı ORM / arama kodunu ayrı iş parçacığında çalıştırır.
"""

import asyncio
import logging
from typing import Any

from django.conf import settings
from django.db import connections
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from apps.films.models import Film

logger = logging.getLogger(__name__)

MCP_PATH = "/mcp"
MAX_RESULTS = 25
DEFAULT_RESULTS = 10
MAX_QUERY_CHARS = 1000
SUMMARY_CHARS = 300
PLOT_CHARS = 1500

MSG_WARMING_UP = "Arama hazırlanıyor, biraz sonra tekrar dene."
MSG_SEARCH_FAILED = "Arama şu an çalışmıyor, biraz sonra tekrar dene."

# DNS rebinding koruması açık kalır; yalnız yerel ve compose ağı adları kabul edilir.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "backend"]
SECURITY = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[*ALLOWED_HOSTS, *(f"{host}:*" for host in ALLOWED_HOSTS)],
    allowed_origins=[f"http://{host}:*" for host in ALLOWED_HOSTS]
    + [f"http://{host}" for host in ALLOWED_HOSTS],
)

INSTRUCTIONS = (
    "ReelSift film arşivinde arama yapar ve film ayrıntısı verir. Yalnız okur. Arşiv metinleri "
    "İngilizcedir: `film_ara` sorgusunu İngilizce yaz."
)

SEARCH_DESCRIPTION = (
    "ReelSift film arşivinde anlam bazlı arama yapar (vektör + kelime + yeniden sıralama). "
    "`sorgu` filmin konusunu, temasını ya da atmosferini anlatan bir cümledir; film adı ya da "
    "kişi adı aramaz. Arşiv metinleri İngilizce olduğu için sorguyu İngilizceye çevirip ver "
    "(örn. 'a lighthouse keeper slowly goes mad on a remote island'). `adet` 1-25 arasıdır. "
    "`yil_en_az` / `yil_en_cok` yapım yılı aralığını, `ulke` İngilizce ülke adını (örn. 'Japan') "
    "kısıtlar. Her film için kimlik, ad, Türkçe ad, yıl, ülkeler, türler, yönetmenler, kısa özet "
    "ve sıra döner; ayrıntı için `film_getir`."
)
GET_DESCRIPTION = (
    "Tek filmin ayrıntısı: ad, yıl, ülke, tür, yönetmen, oyuncular, TMDB özeti, hikâye metninden "
    "en çok ~1500 karakter ve kaynak bağlantıları. `film_id` `film_ara` sonucundaki kimliktir."
)


class McpToolError(ToolError):
    """İstemciye iletisi aynen dönen araç hatası (SDK diğer istisnaların iletisini gizler)."""


def search_ready() -> bool:
    """Arama modelleri ve kelime indeksi bellekte mi? Isınma kapalıysa (ilk çağrı yükler) hazır
    sayılır; ısınma açıkken yüklenmemiş bir hatta çağrı yüzlerce saniye bloklanırdı."""
    if not settings.SEARCH["warmup"]:
        return True
    from apps.search.services import lexical, neural

    return (
        lexical._loaded is not None
        and neural._embedder is not None
        and neural._reranker is not None
    )


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut.rstrip(" ,;:.") + "…"


def _summary(film: Film) -> str:
    return _clip(film.overview or film.tr_overview or film.plot, SUMMARY_CHARS)


def _film_row(film: Film, rank: int) -> dict[str, Any]:
    return {
        "film_id": film.pk,
        "sira": rank,
        "ad": film.title,
        "turkce_ad": film.tr_title,
        "yil": film.year,
        "ulkeler": list(film.countries),
        "turler": list(film.genres),
        "yonetmenler": list(film.directors),
        "ozet": _summary(film),
    }


def build_query(
    sorgu: str, yil_en_az: int | None = None, yil_en_cok: int | None = None, ulke: str | None = None
):
    """Araç argümanlarından arama hattının sorgusunu kurar (dil modeli yok)."""
    from apps.search.services.types import ParsedQuery, QueryFilters

    text = " ".join((sorgu or "").split())
    if not text:
        raise McpToolError("`sorgu` boş olamaz.")
    if len(text) > MAX_QUERY_CHARS:
        raise McpToolError(f"`sorgu` en çok {MAX_QUERY_CHARS} karakter olabilir.")
    if yil_en_az is not None and yil_en_cok is not None and yil_en_az > yil_en_cok:
        raise McpToolError("`yil_en_az`, `yil_en_cok` değerinden büyük olamaz.")
    country = (ulke or "").strip()
    filters = QueryFilters(
        year_min=yil_en_az, year_max=yil_en_cok, countries=(country,) if country else ()
    )
    return ParsedQuery(en_query=text, hyde=text, filters=filters)


def search_films(
    sorgu: str,
    adet: int = DEFAULT_RESULTS,
    yil_en_az: int | None = None,
    yil_en_cok: int | None = None,
    ulke: str | None = None,
) -> dict[str, Any]:
    """Eşzamanlı; iş parçacığında çağrılır (arama CPU/GPU işi yapar, ORM eşzamanlıdır)."""
    from apps.search.services import pipeline

    limit = max(1, min(MAX_RESULTS, int(adet)))
    query = build_query(sorgu, yil_en_az, yil_en_cok, ulke)
    if not search_ready():
        raise McpToolError(MSG_WARMING_UP)
    try:
        result = pipeline.search(query, limit=limit)
        ids = [candidate.film_id for candidate in result.candidates][:limit]
        films = Film.objects.in_bulk(ids)
        rows = [_film_row(films[pk], rank) for rank, pk in enumerate(ids, 1) if pk in films]
    except McpToolError:
        raise
    except Exception as exc:  # dış servis sınırı: ayrıntı loga gider, istemciye sade hata döner
        logger.exception("MCP film_ara hatası")
        raise McpToolError(MSG_SEARCH_FAILED) from exc
    finally:
        connections.close_all()  # bu iş parçacığının veritabanı bağlantısı
    return {
        "adet": len(rows),
        "gevsetilen_filtreler": list(result.relaxed_filters),
        "filmler": rows,
    }


def get_film(film_id: int) -> dict[str, Any]:
    """Eşzamanlı; iş parçacığında çağrılır."""
    try:
        film = Film.objects.filter(pk=film_id).first()
    finally:
        connections.close_all()
    if film is None:
        raise McpToolError(f"{film_id} kimlikli film arşivde yok.")
    links = {}
    if film.tmdb_id:
        links["tmdb"] = f"https://www.themoviedb.org/movie/{film.tmdb_id}"
    if film.imdb_id:
        links["imdb"] = f"https://www.imdb.com/title/{film.imdb_id}/"
    if film.wikipedia_url:
        links["wikipedia"] = film.wikipedia_url
    return {
        "film_id": film.pk,
        "ad": film.title,
        "orijinal_ad": film.original_title,
        "turkce_ad": film.tr_title,
        "yil": film.year,
        "sure_dakika": film.runtime,
        "ulkeler": list(film.countries),
        "turler": list(film.genres),
        "yonetmenler": list(film.directors),
        "oyuncular": list(film.actors),
        "tmdb_ozeti": film.overview,
        "hikaye": _clip(film.plot, PLOT_CHARS),
        "baglantilar": links,
    }


def create_server() -> MCPServer:
    server = MCPServer("reelsift", instructions=INSTRUCTIONS)

    @server.tool(name="film_ara", description=SEARCH_DESCRIPTION)
    async def film_ara(
        sorgu: str,
        adet: int = DEFAULT_RESULTS,
        yil_en_az: int | None = None,
        yil_en_cok: int | None = None,
        ulke: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(search_films, sorgu, adet, yil_en_az, yil_en_cok, ulke)

    @server.tool(name="film_getir", description=GET_DESCRIPTION)
    async def film_getir(film_id: int) -> dict[str, Any]:
        return await asyncio.to_thread(get_film, film_id)

    return server


def create_asgi_app():
    """(ASGI uygulaması, oturum yöneticisi) çifti. Yönetici lifespan'da `run()` ile açılmalıdır."""
    server = create_server()
    app = server.streamable_http_app(streamable_http_path=MCP_PATH, transport_security=SECURITY)
    return app, server.session_manager
