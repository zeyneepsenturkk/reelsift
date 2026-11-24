from django.contrib.auth import get_user_model

from apps.chats.models import Chat, Message

PASSWORD = "test-pass-123"


def make_user(username: str = "editor", **overrides):
    return get_user_model().objects.create_user(username=username, password=PASSWORD, **overrides)


def make_chat(user, title: str = "Yeni sohbet") -> Chat:
    return Chat.objects.create(user=user, title=title)


def make_message(chat: Chat, role: str = "user", text: str = "Merhaba", **overrides) -> Message:
    return Message.objects.create(chat=chat, role=role, text=text, **overrides)
