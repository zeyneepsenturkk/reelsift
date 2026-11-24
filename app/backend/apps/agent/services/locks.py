"""Sohbet başına tek akış kilidi.

Süreç içi ve tek işçi varsayımıyla çalışır: uvicorn tek süreç/işçi olarak çalıştırılır. Birden çok
işçiye geçilirse kilit ortak bir yere (ör. veritabanı danışma kilidi) taşınmalıdır.

Kilit görünümde alınır, akış üreteci çalışmaya başlayınca "başladı" işaretlenir. İstemci üreteç
hiç başlamadan koparsa `finally` çalışmaz; başlamamış kilit bu yüzden kısa sürede kendiliğinden
düşer.
"""

import time
from dataclasses import dataclass

UNSTARTED_TTL_SECONDS = 30.0


@dataclass
class _Hold:
    token: object
    acquired_at: float
    started: bool = False


class ChatLocks:
    def __init__(self):
        self._holds: dict[int, _Hold] = {}

    def try_acquire(self, chat_id: int) -> object | None:
        hold = self._holds.get(chat_id)
        if hold is not None:
            expired = (
                not hold.started and time.monotonic() - hold.acquired_at > UNSTARTED_TTL_SECONDS
            )
            if not expired:
                return None
        token = object()
        self._holds[chat_id] = _Hold(token=token, acquired_at=time.monotonic())
        return token

    def mark_started(self, chat_id: int, token: object) -> None:
        hold = self._holds.get(chat_id)
        if hold is not None and hold.token is token:
            hold.started = True

    def release(self, chat_id: int, token: object) -> None:
        hold = self._holds.get(chat_id)
        if hold is not None and hold.token is token:
            del self._holds[chat_id]


chat_locks = ChatLocks()
