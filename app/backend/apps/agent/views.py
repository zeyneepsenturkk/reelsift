import json
import logging
from typing import Annotated, Literal

from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST
from pydantic import BaseModel, Field, ValidationError

from apps.agent.runtime import get_graph
from apps.agent.services.locks import chat_locks
from apps.agent.services.turns import start_turn
from apps.agent.streaming import stream_turn
from apps.chats.services import chats as chat_service
from apps.core.exceptions import ServiceError
from apps.core.text import SafeText

logger = logging.getLogger(__name__)


class ReplaceFilmAction(BaseModel):
    type: Literal["replace_film"]
    film_id: int


class ResearchAction(BaseModel):
    type: Literal["research"]


class StreamRequest(BaseModel):
    text: SafeText
    action: Annotated[ReplaceFilmAction | ResearchAction, Field(discriminator="type")] | None = None


def json_error(detail: str, code: str, status: int) -> JsonResponse:
    return JsonResponse({"detail": detail, "code": code}, status=status)


def validation_error(detail: str) -> ServiceError:
    return ServiceError(detail, "validation_error", 422)


def parse_body(body: bytes) -> tuple[str, dict | None]:
    """Mesaj metnini ve eylemi doğrular (uzunluk sınırı dahil)."""
    try:
        payload = StreamRequest.model_validate(json.loads(body))
    except (ValueError, ValidationError) as exc:
        raise validation_error("Geçersiz istek.") from exc
    text = payload.text.strip()
    limit = settings.AGENT["message_max_length"]
    if not text:
        raise validation_error("Mesaj boş olamaz.")
    if len(text) > limit:
        raise validation_error(f"Mesaj en fazla {limit} karakter olabilir.")
    return text, payload.action.model_dump() if payload.action else None


@require_POST
async def stream_message(request, chat_id: int):
    user = await request.auser()
    if not user.is_authenticated:
        return json_error("Giriş yapmalısın.", "not_authenticated", 401)
    try:
        chat = await sync_to_async(chat_service.get_owned_chat)(chat_id, user)
    except Http404:
        return json_error("Bulunamadı.", "not_found", 404)

    token = None
    try:
        text, action = parse_body(request.body)
        graph = get_graph()
        token = chat_locks.try_acquire(chat.pk)
        if token is None:
            raise ServiceError(
                "Bu sohbette bir cevap hâlâ hazırlanıyor. Bitmesini bekle.", "chat_busy", 409
            )
        user_message, message_id = await sync_to_async(start_turn)(chat, text, action)
    except ServiceError as exc:
        if token is not None:
            chat_locks.release(chat.pk, token)
        return json_error(exc.message, exc.code, exc.status_code)
    except BaseException:
        if token is not None:
            chat_locks.release(chat.pk, token)
        raise

    response = StreamingHttpResponse(
        stream_turn(
            graph,
            chat_id=chat.pk,
            user_id=user.pk,
            thread_id=str(chat.thread_id),
            user_message=user_message,
            message_id=message_id,
            text=text,
            action=action,
            lock_token=token,
        ),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
