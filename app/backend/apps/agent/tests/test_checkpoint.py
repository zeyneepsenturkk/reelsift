"""Gerçek PostgreSQL kontrol noktası kaydedicisiyle yaşam döngüsü denemeleri."""

import asyncio
import uuid

from django.test import TestCase
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from apps.agent.runtime import open_pool
from apps.agent.tests.base import (
    FakeLLM,
    FakeRetrieval,
    data_of,
    make_graph,
    names,
    run_turn,
)
from apps.chats.models import Chat, Message
from apps.curation.models import Collection
from apps.curation.tests.base import make_chat, make_story_film, make_user


class PostgresCheckpointTests(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.chat = make_chat(self.user)
        # Her test kendi iş parçacığı kimliğiyle çalışır (kontrol noktası tabloları ortak).
        Chat.objects.filter(pk=self.chat.pk).update(thread_id=uuid.uuid4())
        self.chat.refresh_from_db()
        self.films = [make_story_film(n) for n in range(1, 7)]
        self.ids = [film.pk for film in self.films]

    async def test_next_message_resumes_the_waiting_graph_after_a_normal_turn(self):
        llm = FakeLLM()
        async with open_pool() as pool:
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            graph = make_graph(llm, FakeRetrieval(self.ids), saver)

            await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
            config = {"configurable": {"thread_id": str(self.chat.thread_id)}}
            state = await graph.aget_state(config)
            self.assertEqual(state.next, ("await_editor",))
            self.assertTrue(any(task.interrupts for task in state.tasks))

            # Süreç yeniden başlamış gibi: yeni graf nesnesi, aynı veritabanı kaydı.
            graph_after_restart = make_graph(llm, FakeRetrieval(self.ids), saver)
            events = await run_turn(graph_after_restart, self.chat, self.user, "Teşekkürler")

        self.assertEqual(names(events)[-1], "message.done")
        self.assertEqual(len(llm.steps("parse")), 2)

    async def test_cancelled_turn_leaves_no_partial_answer_and_next_turn_starts_clean(self):
        llm = FakeLLM(block_step="judge")
        retrieval = FakeRetrieval(self.ids)
        async with open_pool() as pool:
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            graph = make_graph(llm, retrieval, saver)
            config = {"configurable": {"thread_id": str(self.chat.thread_id)}}

            # 1. tur: istemci modelin cevabını beklerken kopar.
            first = asyncio.ensure_future(run_turn(graph, self.chat, self.user, "Birinci istek"))
            await asyncio.wait_for(llm.started.wait(), timeout=20)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first

            interrupted = await graph.aget_state(config)
            self.assertNotEqual(interrupted.next, ("await_editor",))
            self.assertTrue(interrupted.next)  # tur yarıda kaldı (bekleyen düğüm var)
            self.assertEqual(await Message.objects.filter(role="assistant").acount(), 0)
            self.assertEqual(await Collection.objects.acount(), 0)

            # 2. tur: aynı sohbette yeni mesaj; yarım turun kalıntısı çalışmamalı.
            llm.block_step = None
            events = await run_turn(graph, self.chat, self.user, "İkinci istek")

            self.assertEqual(names(events)[-1], "message.done")
            self.assertEqual(
                [data["key"] for data in data_of(events, "step.start")],
                ["parse", "search", "read", "select"],
            )
            self.assertEqual(len(llm.steps("parse")), 2)  # tur `understand`'den başladı
            self.assertEqual(len(retrieval.calls), 2)  # eski turun `judge`'ı kendiliğinden sürmedi
            self.assertEqual(len(data_of(events, "collection")), 1)
            self.assertEqual(await Collection.objects.acount(), 1)
            self.assertIn("İkinci istek", llm.steps("judge")[-1].user)
            self.assertNotIn("Birinci istek", llm.steps("judge")[-1].user)

            # Aynı sohbet bundan sonra normal devam eder.
            state = await graph.aget_state(config)
            self.assertEqual(state.next, ("await_editor",))
            third = await run_turn(graph, self.chat, self.user, "Üçüncü mesaj")
            self.assertEqual(names(third)[-1], "message.done")

    async def test_error_mid_turn_does_not_block_the_next_message(self):
        llm = FakeLLM(fail_step="select")
        async with open_pool() as pool:
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            graph = make_graph(llm, FakeRetrieval(self.ids), saver)

            failed = await run_turn(graph, self.chat, self.user, "Birinci istek")
            llm.fail_step = None
            retried = await run_turn(graph, self.chat, self.user, "Birinci istek")

        self.assertEqual(names(failed)[-1], "error")
        self.assertEqual(names(retried)[-1], "message.done")
        self.assertEqual(await Collection.objects.acount(), 1)
