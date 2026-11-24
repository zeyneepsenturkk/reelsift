from django.test import TestCase

from apps.agent.schemas import FiltersLM
from apps.agent.tests.base import (
    INVENTED_QUOTE,
    FakeLLM,
    FakeRetrieval,
    data_of,
    make_graph,
    names,
    request_lm,
    run_turn,
    understood,
)
from apps.chats.models import Chat, Message
from apps.curation.models import Collection, CollectionFilm
from apps.curation.tests.base import PLOT_QUOTE, make_chat, make_story_film, make_user


class FlowTestCase(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.chat = make_chat(self.user)
        self.films = [make_story_film(n) for n in range(1, 9)]
        self.ids = [film.pk for film in self.films]

    def graph(self, llm, *results):
        retrieval = FakeRetrieval(*results)
        return make_graph(llm, retrieval), retrieval

    async def latest_collection(self):
        return await Collection.objects.filter(chat=self.chat).order_by("-id").afirst()


class NewSearchFlowTests(FlowTestCase):
    async def test_full_turn_event_order_and_shapes_follow_the_contract(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, (self.ids, ("year_min",)))

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalarda 5 polisiye")

        order = names(events)
        self.assertEqual(order[0], "message.start")
        self.assertEqual(order[-1], "message.done")
        self.assertEqual(
            [name for name in order if name.startswith("step.")],
            ["step.start", "step.done"] * 4,
        )
        keys = [data["key"] for data in data_of(events, "step.start")]
        self.assertEqual(keys, ["parse", "search", "read", "select"])
        for start, done in zip(
            data_of(events, "step.start"), data_of(events, "step.done"), strict=True
        ):
            self.assertEqual(set(start), {"key", "title"})
            self.assertEqual(set(done), {"key", "status", "title", "detail", "count"})
            self.assertEqual(done["status"], "done")
            self.assertEqual(start["key"], done["key"])
        # Metin akışı, öneriler ve koleksiyon olayı vardır; öneriler mesaj bitişinden önce gelir.
        self.assertIn("text.delta", order)
        self.assertLess(order.index("suggestions"), order.index("message.done"))
        self.assertEqual(len(data_of(events, "collection")), 1)
        start = data_of(events, "message.start")[0]
        self.assertEqual(start["user_message"]["role"], "user")
        self.assertEqual(start["user_message"]["text"], "Karlı kasabalarda 5 polisiye")
        done = data_of(events, "message.done")[0]
        self.assertEqual(done["message"]["id"], start["message_id"])
        self.assertEqual(done["chat"]["title"], "Karlı kasabalarda cinayet")

    async def test_step_texts_use_real_numbers(self):
        graph, _ = self.graph(FakeLLM(fit_ids=set(self.ids[:6])), self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        done = {data["key"]: data for data in data_of(events, "step.done")}
        self.assertEqual(done["parse"]["title"], "İsteğini çözdüm.")
        self.assertEqual(done["parse"]["detail"], "Finlandiya")
        self.assertEqual(done["search"]["detail"], "8 aday ayırdım.")
        self.assertEqual(done["search"]["count"], 8)
        self.assertEqual(done["read"]["detail"], "6'yı gerçekten bu havayı taşıyor.")
        self.assertEqual(done["read"]["count"], 6)
        self.assertEqual(done["select"]["title"], "En iyi 5'i seçtim")
        self.assertEqual(done["select"]["detail"], "ve her biri için nedenini yazdım.")

    async def test_draft_is_persisted_with_verified_quotes_and_message_saved(self):
        graph, _ = self.graph(FakeLLM(), self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        collection = await self.latest_collection()
        self.assertEqual(collection.status, "draft")
        self.assertEqual(collection.version, 1)
        self.assertEqual(collection.request["target_count"], 5)
        rows = [row async for row in CollectionFilm.objects.filter(collection=collection)]
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertEqual(row.source_quote, PLOT_QUOTE)
            self.assertEqual(row.source_kind, "plot")
        sent = data_of(events, "collection")[0]
        self.assertEqual(sent["id"], collection.pk)
        self.assertEqual(len(sent["films"]), 5)
        saved = await Message.objects.aget(pk=data_of(events, "message.start")[0]["message_id"])
        self.assertEqual(saved.role, "assistant")
        self.assertEqual(saved.collection_id, collection.pk)
        self.assertEqual(saved.text, "Seçki **hazır**. Karlı kasabalar ortak nokta.")
        self.assertEqual(
            saved.suggestions, ["Daha karanlık olsun", "Daha eski filmler", "Sadece Avrupa"]
        )
        self.assertGreater(saved.duration_s, -1)
        self.assertEqual(
            [step["key"] for step in saved.steps], ["parse", "search", "read", "select"]
        )

    async def test_relaxed_filter_notice_is_sent_and_stored_in_steps(self):
        graph, _ = self.graph(FakeLLM(), (self.ids, ("year_min", "year_max")))

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        notices = data_of(events, "notice")
        self.assertEqual(len(notices), 1)
        self.assertIn("yıl", notices[0]["text"])
        saved = await Message.objects.aget(pk=data_of(events, "message.start")[0]["message_id"])
        self.assertIn("notice", [step["key"] for step in saved.steps])

    async def test_invented_quote_is_repaired_once_and_accepted_when_fixed(self):
        llm = FakeLLM(first_bad_ids={self.ids[0]})
        graph, _ = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        repairs = [call for call in llm.steps("write") if "<problems>" in call.user]
        self.assertEqual(len(repairs), 1)  # yalnız tek onarım çağrısı
        self.assertEqual(repairs[0].user.count("<film id="), 1)
        rows = {
            row.film_id
            async for row in CollectionFilm.objects.filter(
                collection=await self.latest_collection()
            )
        }
        self.assertIn(self.ids[0], rows)
        self.assertEqual(
            data_of(events, "step.done")[-1]["detail"], "ve her biri için nedenini yazdım."
        )

    async def test_quote_missing_from_source_is_dropped_after_failed_repair(self):
        llm = FakeLLM(bad_quote_ids={self.ids[1]})
        graph, _ = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        repairs = [call for call in llm.steps("write") if "<problems>" in call.user]
        self.assertEqual(len(repairs), 1)
        rows = [
            row
            async for row in CollectionFilm.objects.filter(
                collection=await self.latest_collection()
            )
        ]
        self.assertEqual(len(rows), 4)
        self.assertNotIn(self.ids[1], [row.film_id for row in rows])
        self.assertNotIn(INVENTED_QUOTE, [row.source_quote for row in rows])
        select_done = data_of(events, "step.done")[-1]
        self.assertIn(
            "1 film, alıntısı doğrulanamadığı için dışarıda kaldı.", select_done["detail"]
        )
        self.assertEqual(len(data_of(events, "collection")[0]["films"]), 4)
        self.assertIn("1 film(s) were left out", llm.steps("respond")[0].user)

    async def test_film_id_outside_candidates_is_rejected_and_replaced_from_fit_list(self):
        llm = FakeLLM(select_override=[999999, self.ids[0], self.ids[0]])
        graph, _ = self.graph(llm, self.ids)

        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        rows = [
            row.film_id
            async for row in CollectionFilm.objects.filter(
                collection=await self.latest_collection()
            )
        ]
        self.assertNotIn(999999, rows)
        self.assertEqual(rows.count(self.ids[0]), 1)
        self.assertEqual(len(rows), 5)

    async def test_search_excludes_nothing_and_asks_configured_depth(self):
        graph, retrieval = self.graph(FakeLLM(), self.ids)

        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(retrieval.calls[0]["limit"], 100)
        self.assertEqual(retrieval.calls[0]["exclude"], ())
        self.assertEqual(retrieval.calls[0]["request"].filters.countries, ["Finland"])


class RetryTests(FlowTestCase):
    async def test_retries_at_most_twice_then_continues_without_collection(self):
        llm = FakeLLM(fit_ids=set())
        graph, retrieval = self.graph(llm, self.ids[:3], self.ids[3:6], self.ids[6:])

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(len(retrieval.calls), 3)  # ilk arama + en çok 2 yeniden deneme
        self.assertEqual(len(data_of(events, "collection")), 0)
        self.assertEqual(await Collection.objects.acount(), 0)
        self.assertEqual(names(events)[-1], "message.done")
        self.assertIn("no_collection", llm.steps("respond")[0].user)
        message = data_of(events, "message.done")[0]["message"]
        self.assertIsNone(message["collection_id"])
        self.assertEqual(
            [data["key"] for data in data_of(events, "step.start")],
            ["parse", "search", "read", "retry", "search", "read", "retry", "search", "read"],
        )

    async def test_filters_are_relaxed_in_order_then_alternative_query(self):
        request = request_lm(
            filters=FiltersLM(
                year_min=2000, year_max=2010, countries=["Finland"], max_vote_count=2000
            )
        )
        llm = FakeLLM(understand=understood(request=request), fit_ids=set())
        graph, retrieval = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Az bilinen Fin polisiyeleri")

        seen = [call["request"].filters for call in retrieval.calls]
        self.assertEqual(seen[0].max_vote_count, 2000)
        self.assertIsNone(seen[1].max_vote_count)  # 1. gevşetme: oy sayısı
        self.assertEqual((seen[1].year_min, seen[1].year_max), (2000, 2010))
        self.assertEqual((seen[2].year_min, seen[2].year_max), (1995, 2015))  # 2. gevşetme: yıl +-5
        self.assertEqual(len(data_of(events, "notice")), 2)
        self.assertEqual(llm.steps("retry"), [])  # alternatif cümle için deneme hakkı kalmadı

    async def test_alternative_query_is_used_when_no_filter_is_left_to_relax(self):
        request = request_lm(
            filters=FiltersLM(year_min=None, year_max=None, countries=[], max_vote_count=None)
        )
        llm = FakeLLM(understand=understood(request=request), fit_ids=set())
        graph, retrieval = self.graph(llm, self.ids)

        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(len(llm.steps("retry")), 2)
        queries = [call["request"].en_query for call in retrieval.calls]
        self.assertEqual(
            queries[1:], ["alternative search number 1", "alternative search number 2"]
        )

    async def test_recovers_when_a_retry_finds_enough_films(self):
        llm = FakeLLM(fit_ids=set(self.ids[3:]))
        graph, retrieval = self.graph(llm, self.ids[:3], self.ids[3:])

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(len(retrieval.calls), 2)
        self.assertEqual(len(data_of(events, "collection")[0]["films"]), 5)
        notice = data_of(events, "notice")[0]["text"]
        self.assertIn("ülke filtresini kaldırdım", notice)

    async def test_empty_search_result_produces_no_collection(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, [])

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(await Collection.objects.acount(), 0)
        self.assertEqual(names(events)[-1], "message.done")
        self.assertEqual(llm.steps("judge"), [])


class RefineTests(FlowTestCase):
    async def start_draft(self, llm, graph):
        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        return data_of(events, "collection")[0]

    async def test_refine_keeps_still_fitting_films_and_their_rationale(self):
        llm = FakeLLM()
        graph, retrieval = self.graph(llm, self.ids)
        first = await self.start_draft(llm, graph)
        first_ids = [film["film_id"] for film in first["films"]]
        before = {
            row.film_id: (row.rationale, row.source_quote, row.pk)
            async for row in CollectionFilm.objects.filter(collection_id=first["id"])
        }
        # Yeni istekte ilk iki film artık uygun değil; yeni filmler gelir.
        llm.fit_ids = set(self.ids) - set(first_ids[:2])
        llm.understand = understood("refine", instruction="darker")

        events = await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        updated = data_of(events, "collection")[0]
        self.assertEqual(updated["id"], first["id"])
        self.assertEqual(updated["version"], 2)
        new_ids = [film["film_id"] for film in updated["films"]]
        self.assertTrue(set(first_ids[:2]).isdisjoint(new_ids))
        kept = set(first_ids[2:]) & set(new_ids)
        self.assertEqual(len(kept), 3)
        after = {
            row.film_id: (row.rationale, row.source_quote, row.pk)
            async for row in CollectionFilm.objects.filter(collection_id=first["id"])
        }
        for film_id in kept:
            self.assertEqual(after[film_id], before[film_id])  # gerekçe ve satır değişmedi
        # Yalnız yeni 2 film için gerekçe yazıldı.
        written = llm.steps("write")[-1].user
        self.assertEqual(written.count("<film id="), 2)
        self.assertEqual([data["key"] for data in data_of(events, "step.start")][-1], "update")
        self.assertEqual(data_of(events, "step.done")[-1]["title"], "Seçkiyi güncelledim.")
        self.assertEqual(await Collection.objects.acount(), 1)  # yeni taslak açılmadı

    async def test_refine_also_judges_existing_draft_films(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, self.ids[:5])
        first = await self.start_draft(llm, graph)
        llm.understand = understood("refine", instruction="darker")

        await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        judged = " ".join(call.user for call in llm.steps("judge")[1:])
        for film in first["films"]:
            self.assertIn(f'<film id="{film["film_id"]}">', judged)

    async def test_replace_film_action_changes_exactly_one_film(self):
        llm = FakeLLM()
        graph, retrieval = self.graph(llm, self.ids)
        first = await self.start_draft(llm, graph)
        first_ids = [film["film_id"] for film in first["films"]]
        target = first_ids[1]
        before = {
            row.film_id: row.rationale
            async for row in CollectionFilm.objects.filter(collection_id=first["id"])
        }

        events = await run_turn(
            graph,
            self.chat,
            self.user,
            "Bunun yerine başkasını bul",
            action={"type": "replace_film", "film_id": target},
        )

        updated = data_of(events, "collection")[0]
        new_ids = [film["film_id"] for film in updated["films"]]
        self.assertEqual(len(new_ids), 5)
        self.assertNotIn(target, new_ids)
        self.assertEqual(new_ids[0], first_ids[0])
        self.assertEqual(new_ids[2:], first_ids[2:])
        replacement = new_ids[1]
        self.assertNotIn(replacement, first_ids)
        self.assertEqual(updated["title"], first["title"])
        after = {
            row.film_id: row.rationale
            async for row in CollectionFilm.objects.filter(collection_id=first["id"])
        }
        for film_id in first_ids:
            if film_id != target:
                self.assertEqual(after[film_id], before[film_id])
        self.assertEqual(len(llm.steps("parse")), 1)  # eylem modele sorulmadı
        self.assertEqual(set(retrieval.calls[-1]["exclude"]), set(first_ids))
        self.assertEqual(llm.steps("write")[-1].user.count("<film id="), 1)
        self.assertEqual(llm.steps("select"), llm.steps("select")[:1])  # ikinci seçim çağrısı yok

    async def test_research_action_opens_new_draft_without_the_old_films(self):
        llm = FakeLLM()
        graph, retrieval = self.graph(llm, self.ids)
        first = await self.start_draft(llm, graph)
        first_ids = {film["film_id"] for film in first["films"]}

        events = await run_turn(
            graph, self.chat, self.user, "Yeniden araştır", action={"type": "research"}
        )

        updated = data_of(events, "collection")[0]
        self.assertNotEqual(updated["id"], first["id"])
        self.assertTrue(first_ids.isdisjoint(film["film_id"] for film in updated["films"]))
        self.assertEqual(await Collection.objects.acount(), 2)

    async def test_new_search_after_approval_opens_new_draft_and_keeps_approved_one(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, self.ids)
        first = await self.start_draft(llm, graph)
        await Collection.objects.filter(pk=first["id"]).aupdate(status="approved")
        llm.understand = understood("refine", instruction="darker")

        events = await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        updated = data_of(events, "collection")[0]
        self.assertNotEqual(updated["id"], first["id"])
        self.assertEqual((await Collection.objects.aget(pk=first["id"])).status, "approved")
        self.assertEqual((await Collection.objects.aget(pk=first["id"])).version, 1)


class QuestionAndOtherTests(FlowTestCase):
    async def test_question_streams_answer_and_leaves_collection_unchanged(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, self.ids)
        first = data_of(
            await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film"), "collection"
        )[0]
        llm.understand = understood("question", request=None, film_id=first["films"][0]["film_id"])
        llm.reply = "Bu film **kasvetli** olduğu için seçildi."

        events = await run_turn(graph, self.chat, self.user, "Bu film neden seçildi?")

        self.assertEqual(len(data_of(events, "collection")), 0)
        text = "".join(data["delta"] for data in data_of(events, "text.delta"))
        self.assertEqual(text.strip(), "Bu film **kasvetli** olduğu için seçildi.")
        collection = await Collection.objects.aget(pk=first["id"])
        self.assertEqual(collection.version, 1)
        self.assertIn(PLOT_QUOTE, llm.steps("answer")[-1].user)  # yalnız o filmin metinleri
        self.assertEqual(llm.steps("answer")[-1].user.count("<film id="), 1)
        done = data_of(events, "message.done")[0]["message"]
        self.assertIsNone(done["collection_id"])

    async def test_typing_approve_in_chat_does_not_change_status(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, self.ids)
        first = data_of(
            await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film"), "collection"
        )[0]
        llm.understand = understood("other", request=None)
        llm.reply = "Onaylamak için sağdaki **Onayla** düğmesine basmalısın."

        events = await run_turn(graph, self.chat, self.user, "Onayla ve kaydet")

        collection = await Collection.objects.aget(pk=first["id"])
        self.assertEqual(collection.status, "draft")
        self.assertIsNone(collection.share_token)
        self.assertIsNone(collection.approved_at)
        self.assertEqual(names(events)[-1], "message.done")
        # Cevap isteminde "yalnız düğmeyle onaylanır" kuralı sabit olarak yer alır.
        from apps.agent import prompts

        self.assertIn("Onayla", prompts.ANSWER_SYSTEM)

    async def test_question_without_draft_is_answered_as_other(self):
        llm = FakeLLM(understand=understood("question", request=None))
        graph, retrieval = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Bu neden seçildi?")

        self.assertEqual(retrieval.calls, [])
        self.assertIn("no_draft_to_ask_about", llm.steps("answer")[0].user)
        self.assertEqual(names(events)[-1], "message.done")

    async def test_refine_without_draft_becomes_new_search(self):
        llm = FakeLLM(understand=understood("refine", instruction="darker"))
        graph, retrieval = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        self.assertEqual(len(retrieval.calls), 1)
        self.assertEqual(len(data_of(events, "collection")), 1)
        self.assertEqual(data_of(events, "step.start")[-1]["key"], "select")


class ErrorTests(FlowTestCase):
    async def test_model_error_emits_error_event_and_saves_error_message(self):
        llm = FakeLLM(fail_step="judge")
        graph, _ = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(names(events)[-1], "error")
        error = data_of(events, "error")[0]
        self.assertEqual(
            error,
            {
                "detail": "Dil modeline şu an ulaşılamıyor. Biraz sonra tekrar dene.",
                "code": "model_error",
            },
        )
        self.assertNotIn("message.done", names(events))
        message_id = data_of(events, "message.start")[0]["message_id"]
        saved = await Message.objects.aget(pk=message_id)
        self.assertEqual(saved.error, error)
        self.assertEqual(saved.text, "")
        self.assertEqual([step["key"] for step in saved.steps], ["parse", "search"])
        self.assertEqual(await Collection.objects.acount(), 0)

    async def test_unexpected_error_hides_details(self):
        class Boom(FakeRetrieval):
            async def search(self, *args, **kwargs):
                raise RuntimeError("secret internal detail sk-ant-123")

        graph = make_graph(FakeLLM(), Boom())

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        error = data_of(events, "error")[0]
        self.assertEqual(error["code"], "server_error")
        self.assertNotIn("secret", error["detail"])
        self.assertNotIn("sk-ant", str(events))

    async def test_chat_stays_usable_after_an_error(self):
        llm = FakeLLM(fail_step="judge")
        graph, _ = self.graph(llm, self.ids)
        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        llm.fail_step = None

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(names(events)[-1], "message.done")
        self.assertEqual(len(data_of(events, "collection")), 1)
        # Hatalı mesaj sonraki turun bağlamına girmez.
        history_in_prompt = llm.steps("parse")[-1].user
        self.assertNotIn("model_error", history_in_prompt)
        self.assertEqual(await Chat.objects.acount(), 1)
