import json

from django.test import Client, TestCase

from apps.chats.models import Chat
from apps.chats.tests.base import make_chat, make_message, make_user
from apps.curation.tests.base import make_collection, make_story_film


class ChatApiTestCase(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.other = make_user("other")
        self.client.force_login(self.user)


class CreateChatTests(ChatApiTestCase):
    def test_creates_chat_with_default_title(self):
        response = self.client.post("/api/chats")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["title"], "Yeni sohbet")
        chat = Chat.objects.get(pk=body["id"])
        self.assertEqual(chat.user, self.user)

    def test_unauthenticated_is_401(self):
        self.client.logout()

        response = self.client.post("/api/chats")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "not_authenticated")
        self.assertEqual(Chat.objects.count(), 0)

    def test_csrf_token_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post("/api/chats")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "forbidden")


class ListChatsTests(ChatApiTestCase):
    def test_lists_only_own_chats_newest_first(self):
        first = make_chat(self.user, "Birinci")
        second = make_chat(self.user, "İkinci")
        make_chat(self.other, "Başkası")
        make_message(first)  # eski sohbete mesaj gelince en üste çıkar
        Chat.objects.filter(pk=first.pk).update(updated_at=second.updated_at.replace(year=2100))

        response = self.client.get("/api/chats")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([chat["title"] for chat in response.json()], ["Birinci", "İkinci"])

    def test_unauthenticated_is_401(self):
        self.client.logout()

        self.assertEqual(self.client.get("/api/chats").status_code, 401)


class GetChatTests(ChatApiTestCase):
    def test_returns_messages_in_order_and_current_collection(self):
        chat = make_chat(self.user, "Karlı kasabalar")
        films = [make_story_film(n) for n in (1, 2)]
        old = make_collection(self.user, chat, films=films[:1], title="Eski")
        newest = make_collection(self.user, chat, films=films, title="Yeni")
        make_message(chat, "user", "Karlı kasabalar")
        make_message(
            chat,
            "assistant",
            "Hazır.",
            steps=[
                {
                    "key": "parse",
                    "status": "done",
                    "title": "İsteğini çözdüm.",
                    "detail": "x",
                    "count": None,
                },
                {"key": "notice", "status": "done", "title": "", "detail": "Not.", "count": None},
            ],
            duration_s=3.2,
            collection=newest,
            suggestions=["Daha karanlık"],
        )
        make_message(
            chat, "assistant", "", error={"detail": "Model yanıt vermedi.", "code": "model_error"}
        )

        response = self.client.get(f"/api/chats/{chat.pk}")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["title"], "Karlı kasabalar")
        self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant", "assistant"])
        answer = body["messages"][1]
        self.assertEqual(answer["collection_id"], newest.pk)
        self.assertEqual(answer["duration_s"], 3.2)
        self.assertEqual([step["key"] for step in answer["steps"]], ["parse", "notice"])
        self.assertEqual(answer["suggestions"], ["Daha karanlık"])
        self.assertIsNone(answer["error"])
        self.assertEqual(body["messages"][2]["error"]["code"], "model_error")
        self.assertEqual(body["collection"]["id"], newest.pk)
        self.assertNotEqual(body["collection"]["id"], old.pk)

    def test_chat_without_collection_has_null_collection(self):
        chat = make_chat(self.user)

        body = self.client.get(f"/api/chats/{chat.pk}").json()

        self.assertIsNone(body["collection"])
        self.assertEqual(body["messages"], [])

    def test_other_users_chat_is_404(self):
        chat = make_chat(self.other)

        response = self.client.get(f"/api/chats/{chat.pk}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not_found")

    def test_unknown_chat_is_404_and_unauthenticated_is_401(self):
        self.assertEqual(self.client.get("/api/chats/999999").status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get("/api/chats/1").status_code, 401)

    def test_query_count_is_constant_for_long_chats(self):
        chat = make_chat(self.user)
        for index in range(20):
            make_message(chat, "user", f"Mesaj {index}")

        with self.assertNumQueries(5):  # oturum, kullanıcı, sohbet, mesajlar, koleksiyon
            self.client.get(f"/api/chats/{chat.pk}")

    def test_json_body_is_ignored_on_create(self):
        response = self.client.post(
            "/api/chats", data=json.dumps({"title": "Hack"}), content_type="application/json"
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["title"], "Yeni sohbet")
