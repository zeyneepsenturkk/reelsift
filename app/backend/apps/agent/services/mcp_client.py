"""MCP istemcisi: aynı süreçteki `reelsift-bilgi` sunucusuna bellek içi taşımayla bağlanır.

Her çağrıda MCP el sıkışması (`initialize`) ve `tools/call` gerçek protokolle yapılır.
"""

import asyncio
import json
import logging

from mcp import Client

from apps.agent.mcp_tools import server

logger = logging.getLogger(__name__)

CALL_TIMEOUT_S = 8.0


async def _call(name: str, arguments: dict) -> dict | None:
    async with Client(server) as client:
        result = await client.call_tool(name, arguments)
    if result.is_error:
        return None
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else None
    return None


async def call_tool(name: str, arguments: dict) -> dict | None:
    """Aracı çağırır ve sonucu sözlük olarak döner; her hatada (metin loglanmaz) None."""
    try:
        return await asyncio.wait_for(_call(name, arguments), CALL_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - araç yolu cevabı hiçbir zaman düşürmemeli
        logger.warning("mcp aracı başarısız tool=%s hata=%s", name, type(exc).__name__)
        return None
