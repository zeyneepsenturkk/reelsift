from datetime import datetime
from typing import Literal

from ninja import Schema

from apps.curation.schemas import CollectionOut

StepKey = Literal["parse", "search", "read", "select", "retry", "update", "notice"]


class StepOut(Schema):
    key: StepKey
    status: Literal["running", "done", "error"]
    title: str
    detail: str
    count: int | None = None


class MessageErrorOut(Schema):
    detail: str
    code: str


class MessageOut(Schema):
    id: int
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime
    steps: list[StepOut]
    duration_s: float | None
    collection_id: int | None
    suggestions: list[str]
    error: MessageErrorOut | None


class ChatSummaryOut(Schema):
    id: int
    title: str
    updated_at: datetime


class ChatOut(ChatSummaryOut):
    messages: list[MessageOut]
    collection: CollectionOut | None
