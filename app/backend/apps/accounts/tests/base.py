import json

from django.core.cache import cache
from django.test import Client, TestCase

from apps.chats.tests.base import PASSWORD, make_chat, make_user


class AuthApiTestCase(TestCase):
    """CSRF denetimi AÇIK istemci kullanır: giriş/çıkış gerçek tarayıcı gibi sınanır."""

    def setUp(self):
        # Deneme sınırı sayaçları süreç belleğinde tutulur; testler birbirinin sayacını görmesin.
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = Client(enforce_csrf_checks=True)
        self.user = make_user("editor", first_name="Zeynep", last_name="Şentürk")

    def csrf_headers(self) -> dict:
        self.client.get("/api/auth/me")
        return {"HTTP_X_CSRFTOKEN": self.client.cookies["csrftoken"].value}

    def login(self, username="editor", password=PASSWORD, headers=None, **extra):
        headers = self.csrf_headers() if headers is None else headers
        return self.client.post(
            "/api/auth/login",
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
            **headers,
            **extra,
        )


__all__ = ["PASSWORD", "AuthApiTestCase", "make_chat", "make_user"]
