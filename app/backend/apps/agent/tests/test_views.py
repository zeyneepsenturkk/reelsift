import json

from asgiref.sync import sync_to_async
from django.test import AsyncClient, TestCase

from apps.agent import runtime
from apps.agent.services.locks import chat_locks
from apps.agent.tests.base import (
    FakeLLM,
    FakeRetrieval,
    data_of,
    make_graph,
    names,
    parse_sse,
)
from apps.chats.models import Message
from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user


class StreamViewTestCase(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.other = make_user("other")
        self.chat = make_chat(self.user)
        self.films = [make_story_film(n) for n in range(1, 7)]
        self.llm = FakeLLM()
        self.retrieval = FakeRetrieval([film.pk for film in self.films])
        runtime.set_graph(make_graph(self.llm, self.retrieval))
        self.addCleanup(runtime.set_graph, None)
        self.addCleanup(chat_locks._holds.clear)
        self.client = AsyncClient()

    def url(self, chat=None):
        return f"/api/chats/{(chat or self.chat).pk}/messages/stream"

    async def login(self, user=None):
        await sync_to_async(self.client.force_login)(user or self.user)

    async def post(self, payload, chat=None, **kwargs):
        body = payload if isinstance(payload, str) else json.dumps(payload)
        return await self.client.post(
            self.url(chat), data=body, content_type="application/json", **kwargs
        )

    async def read(self, response) -> str:
        return "".join([chunk.decode() async for chunk in response.streaming_content])


class StreamSuccessTests(StreamViewTestCase):
    async def test_streams_contract_events_with_sse_headers(self):
        await self.login()

        response = await self.post({"text": "Karlı kasabalarda polisiyeler"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        self.assertEqual(response["Cache-Control"], "no-cache")
        self.assertEqual(response["X-Accel-Buffering"], "no")
        events = parse_sse(await self.read(response))
        self.assertEqual(names(events)[0], "message.start")
        self.assertEqual(names(events)[-1], "message.done")
        self.assertEqual(len(data_of(events, "collection")), 1)
        saved = await Message.objects.filter(chat=self.chat).acount()
        self.assertEqual(saved, 2)

    async def test_lock_is_released_after_the_stream_ends(self):
        await self.login()

        await self.read(await self.post({"text": "Karlı kasabalar"}))

        self.assertIsNotNone(chat_locks.try_acquire(self.chat.pk))

    async def test_events_arrive_one_by_one_not_in_a_single_burst(self):
        await self.login()
        response = await self.post({"text": "Karlı kasabalar"})

        chunks = [chunk.decode() async for chunk in response.streaming_content]

        # Her olay ayrı parça olarak gelir (arabelleğe alınıp tek seferde gönderilmez).
        self.assertGreater(len(chunks), 10)
        self.assertTrue(all(chunk.endswith("\n\n") for chunk in chunks))
        self.assertEqual(sum(chunk.count("event: ") for chunk in chunks), len(chunks))


class StreamErrorTests(StreamViewTestCase):
    async def test_unauthenticated_is_401_json(self):
        response = await self.post({"text": "Merhaba"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "not_authenticated")
        self.assertEqual(await Message.objects.acount(), 0)

    async def test_other_users_chat_is_404_and_nothing_is_saved(self):
        await self.login(self.other)

        response = await self.post({"text": "Merhaba"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Bulunamadı.", "code": "not_found"})
        self.assertEqual(await Message.objects.acount(), 0)

    async def test_get_is_not_allowed(self):
        await self.login()

        response = await self.client.get(self.url())

        self.assertEqual(response.status_code, 405)

    async def test_invalid_bodies_are_422(self):
        await self.login()
        too_long = "x" * 2001
        cases = [
            "not json",
            {},
            {"text": "   "},
            {"text": too_long},
            {"text": "x", "action": {"type": "approve"}},
            {"text": "x", "action": {"type": "replace_film"}},
            {"text": 5},
        ]
        for payload in cases:
            with self.subTest(payload=str(payload)[:30]):
                response = await self.post(payload)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["code"], "validation_error")
        self.assertEqual(await Message.objects.acount(), 0)

    async def test_message_at_the_limit_is_accepted(self):
        await self.login()

        response = await self.post({"text": "x" * 2000})

        self.assertEqual(response.status_code, 200)
        await self.read(response)

    async def test_csrf_is_enforced(self):
        client = AsyncClient(enforce_csrf_checks=True)
        await sync_to_async(client.force_login)(self.user)

        response = await client.post(
            self.url(), data=json.dumps({"text": "x"}), content_type="application/json"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "forbidden")
        self.assertEqual(await Message.objects.acount(), 0)

    async def test_second_stream_on_the_same_chat_is_409_chat_busy(self):
        await self.login()
        held = chat_locks.try_acquire(self.chat.pk)

        response = await self.post({"text": "Merhaba"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "chat_busy")
        self.assertEqual(await Message.objects.acount(), 0)
        chat_locks.release(self.chat.pk, held)

    async def test_busy_chat_does_not_block_other_chats(self):
        await self.login()
        held = chat_locks.try_acquire(self.chat.pk)
        other_chat = await sync_to_async(make_chat)(self.user)

        response = await self.post({"text": "Merhaba"}, chat=other_chat)

        self.assertEqual(response.status_code, 200)
        await self.read(response)
        chat_locks.release(self.chat.pk, held)

    async def test_replace_film_action_needs_a_draft_with_that_film(self):
        await self.login()

        response = await self.post(
            {"text": "Başkasını bul", "action": {"type": "replace_film", "film_id": 12345}}
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")

    async def test_replace_film_on_approved_collection_is_409_locked(self):
        await self.login()
        collection = await sync_to_async(make_collection)(
            self.user, self.chat, films=self.films[:2], status="approved"
        )

        response = await self.post(
            {
                "text": "Başkasını bul",
                "action": {"type": "replace_film", "film_id": self.films[0].pk},
            }
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "collection_locked")
        self.assertEqual(collection.status, "approved")

    async def test_missing_runtime_is_503_json(self):
        await self.login()
        runtime.set_graph(None)

        response = await self.post({"text": "Merhaba"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(await Message.objects.acount(), 0)
        self.assertIsNotNone(chat_locks.try_acquire(self.chat.pk))

    async def test_model_failure_still_returns_200_with_error_event(self):
        await self.login()
        self.llm.fail_step = "parse"

        response = await self.post({"text": "Karlı kasabalar"})

        self.assertEqual(response.status_code, 200)
        events = parse_sse(await self.read(response))
        self.assertEqual(names(events), ["message.start", "step.start", "error"])
        self.assertEqual(data_of(events, "error")[0]["code"], "model_error")
