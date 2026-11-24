"""Akan cevap: graf olaylarını sözleşmedeki SSE olaylarına çevirir.

İstemci koparsa Django üretece iptal atar: akış ve düğüm iptal olur, yarım cevap kaydedilmez.
Kontrol noktası son biten düğümde kalır; aynı sohbetteki sonraki mesaj temiz başlar
(`prepare_input`).
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from asgiref.sync import sync_to_async
from langgraph.types import Command

from apps.agent.services.locks import chat_locks
from apps.chats.models import Chat
from apps.chats.services import chats as chat_service
from apps.core.exceptions import ServiceError

logger = logging.getLogger(__name__)

PING_INTERVAL_SECONDS = 15.0
RECURSION_LIMIT = 60
# Sözleşme 1.2: `error` olayında yalnız bu kodlar çıkabilir.
STREAM_ERROR_CODES = frozenset({"model_error", "search_error", "collection_locked", "server_error"})
MSG_SERVER_ERROR = "Beklenmeyen bir hata oluştu. Biraz sonra tekrar dene."
MSG_INCOMPLETE = "Cevap tamamlanamadı. Mesajı tekrar gönder."


def sse(event: str, data: dict) -> str:
    return (
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


async def prepare_input(graph, config: dict, turn: dict):
    """Aynı sohbetin durumuna göre grafın alacağı girdiyi seçer.

    - Hiç kayıt yok: ilk mesaj, girdi doğrudan verilir.
    - Bekleyen `interrupt` var: normal devam, `Command(resume=...)`.
    - Aksi halde bir önceki tur yarıda kalmıştır (istemci koptu ya da hata oldu): kayıt
      `await_editor` bitmiş gibi güncellenir, böylece eski bekleyen düğümler çalışmaz ve tur
      `understand`'den temiz başlar. Dönen `None`, `astream(None, ...)` demektir.
    """
    state = await graph.aget_state(config)
    resume = {key: turn[key] for key in ("text", "action", "user_message_id", "message_id")}
    if not state.values:
        return turn
    if any(task.interrupts for task in state.tasks):
        return Command(resume=resume)
    await graph.aupdate_state(config, resume, as_node="await_editor")
    return None


async def _with_heartbeat(stream: AsyncIterator, interval: float) -> AsyncIterator:
    """`interval` saniye olay gelmezse `None` üretir (bağlantı boşta kalmasın diye `: ping`)."""
    iterator = stream.__aiter__()
    pending = asyncio.ensure_future(iterator.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield None
                continue
            try:
                item = pending.result()
            except StopAsyncIteration:
                return
            yield item
            pending = asyncio.ensure_future(iterator.__anext__())
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            await aclose()


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    """`event:`/`data:` bloklarını (olay adı, veri) çiftlerine çevirir; `: ping` atlanır."""
    events = []
    for block in raw.split("\n\n"):
        block = block.strip("\n")
        if not block or block.startswith(":"):
            continue
        name_line, data_line = block.split("\n", 1)
        name = name_line.removeprefix("event: ")
        events.append((name, json.loads(data_line.removeprefix("data: "))))
    return events


def notice_step(text: str) -> dict:
    return {"key": "notice", "status": "done", "title": "", "detail": text, "count": None}


def _error_payload(exc: Exception) -> dict:
    """Sözleşmedeki dört koddan biri değilse iç kod ve iç mesaj istemciye gitmez."""
    if isinstance(exc, ServiceError) and exc.code in STREAM_ERROR_CODES:
        return {"detail": exc.message, "code": exc.code}
    if isinstance(exc, ServiceError):
        logger.error("Akış sırasında iç hata kodu=%s", exc.code, exc_info=exc)
    else:
        logger.error("Akış sırasında beklenmeyen hata", exc_info=exc)
    return {"detail": MSG_SERVER_ERROR, "code": "server_error"}


async def stream_turn(
    graph,
    *,
    chat_id: int,
    user_id: int,
    thread_id: str,
    user_message,
    message_id: int,
    text: str,
    action: dict | None,
    lock_token: object,
    ping_interval: float = PING_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    chat_locks.mark_started(chat_id, lock_token)
    steps: list[dict] = []
    finished = False
    error: dict | None = None
    try:
        try:
            yield sse(
                "message.start",
                {
                    "user_message": chat_service.message_out(user_message).model_dump(mode="json"),
                    "message_id": message_id,
                },
            )
            turn = {
                "chat_id": chat_id,
                "user_id": user_id,
                "user_message_id": user_message.pk,
                "message_id": message_id,
                "text": text,
                "action": action,
            }
            config = {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}
            graph_input = await prepare_input(graph, config, turn)
            stream = graph.astream(
                graph_input, config, stream_mode=["custom", "updates"], version="v2"
            )
            async for chunk in _with_heartbeat(stream, ping_interval):
                if chunk is None:
                    yield ": ping\n\n"
                    continue
                if chunk["type"] != "custom":
                    continue  # "updates" yalnız düğüm bitişi ve interrupt bilgisini taşır
                event, payload = chunk["data"]["event"], chunk["data"]["data"]
                if event == "step.done":
                    steps.append(payload)
                elif event == "notice":
                    steps.append(notice_step(payload["text"]))
                elif event == "message.done":
                    finished = True
                yield sse(event, payload)
            if not finished:
                error = {"detail": MSG_INCOMPLETE, "code": "server_error"}
        except asyncio.CancelledError:
            # İstemci koptu: iş bırakılır, yarım cevap kaydedilmez.
            raise
        except Exception as exc:  # akışın tek hata çıkışı: ayrıntı loga, istemciye sade `error`
            error = _error_payload(exc)

        # Kilit hata kaydı bitene kadar tutulur; yeni tur yarışmasın.
        if error is not None:
            await _save_error(chat_id, user_id, message_id, steps, error)
            yield sse("error", error)
    finally:
        chat_locks.release(chat_id, lock_token)


async def _save_error(chat_id: int, user_id: int, message_id: int, steps: list[dict], error: dict):
    def save():
        chat = Chat.objects.get(pk=chat_id, user_id=user_id)
        chat_service.save_assistant_message(
            chat,
            message_id=message_id,
            text="",
            steps=steps,
            duration_s=None,
            collection_id=None,
            suggestions=[],
            error=error,
        )

    try:
        await sync_to_async(save)()
    except Exception:  # hata kaydı başarısız olsa da `error` olayı istemciye gitmeli
        logger.exception("Hata mesajı kaydedilemedi")
