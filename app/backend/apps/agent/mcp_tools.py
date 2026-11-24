"""`reelsift-bilgi` MCP araç sunucusu: bir konunun kısa özetini Wikipedia'dan getirir.

Tek araç `wikipedia_ozet`: önce başlığa göre özet sayfası, tutmazsa Wikipedia'nın başlık
araması ile en yakın sayfa denenir; istenen dilde yoksa İngilizceye düşer. Herkese açık API,
anahtar gerekmez.
"""

import logging
from urllib.parse import quote

import httpx2
from mcp.server.mcpserver import MCPServer

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_S = 5.0
USER_AGENT = "ReelSift/1.0"
SUMMARY_MAX_CHARS = 1500
FALLBACK_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("tr", "en")

server = MCPServer("reelsift-bilgi")


def _http_client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        timeout=HTTP_TIMEOUT_S,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def _not_found(language: str) -> dict:
    return {"bulundu": False, "baslik": "", "ozet": "", "adres": "", "dil": language}


async def _get_json(
    client: httpx2.AsyncClient, url: str, params: dict | None = None
) -> dict | None:
    """Başarılı (200) JSON cevabı ya da None (bulunamadı, hata, zaman aşımı)."""
    try:
        response = await client.get(url, params=params)
    except (httpx2.HTTPError, OSError) as exc:
        logger.warning("wikipedia isteği başarısız: %s", type(exc).__name__)
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


async def _summary(client: httpx2.AsyncClient, language: str, title: str) -> dict | None:
    """Başlığın özet sayfası; yoksa, boşsa ya da anlam ayrımı sayfasıysa None."""
    slug = quote(title.strip().replace(" ", "_"), safe="")
    page = await _get_json(
        client, f"https://{language}.wikipedia.org/api/rest_v1/page/summary/{slug}"
    )
    if not page or page.get("type") != "standard":
        return None
    extract = (page.get("extract") or "").strip()
    address = ((page.get("content_urls") or {}).get("desktop") or {}).get("page") or ""
    if not extract or not address:
        return None
    return {
        "bulundu": True,
        "baslik": page.get("title") or title,
        "ozet": extract[:SUMMARY_MAX_CHARS],
        "adres": address,
        "dil": language,
    }


async def _closest_title(client: httpx2.AsyncClient, language: str, query: str) -> str | None:
    """Wikipedia başlık aramasının ilk sonucu (en yakın sayfa)."""
    payload = await _get_json(
        client,
        f"https://{language}.wikipedia.org/w/api.php",
        {"action": "query", "list": "search", "srsearch": query, "srlimit": 1, "format": "json"},
    )
    hits = ((payload or {}).get("query") or {}).get("search") or []
    return hits[0].get("title") if hits else None


@server.tool()
async def wikipedia_ozet(baslik: str, dil: str = "tr") -> dict:
    """Bir kişi, film, tür ya da kavramın Wikipedia özetini ve sayfa adresini getirir.

    Önce `dil` sürümünde, yoksa İngilizce sürümde aranır. Dönüş: bulundu, baslik, ozet, adres, dil.
    """
    query = (baslik or "").strip()
    language = dil if dil in SUPPORTED_LANGUAGES else "tr"
    if not query:
        return _not_found(language)
    languages = [language] + ([FALLBACK_LANGUAGE] if language != FALLBACK_LANGUAGE else [])
    async with _http_client() as client:
        for lang in languages:
            if found := await _summary(client, lang, query):
                return found
        for lang in languages:
            title = await _closest_title(client, lang, query)
            if title and (found := await _summary(client, lang, title)):
                return found
    return _not_found(language)
