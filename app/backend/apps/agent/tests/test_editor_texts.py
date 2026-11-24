"""Editöre söylenen metinler: dil kuralı, söylenmemiş film sayısı, onaylı seçki bildirimi ve
tek film değiştirme cevabının notları. Model sahtedir; seçim davranışı başka testlerde sınanır."""

import re

from django.test import SimpleTestCase, TestCase

from apps.agent import graph as agent_graph
from apps.agent import prompts, streaming
from apps.agent.schemas import ParsedRequest, sanitize_request
from apps.agent.services import llm as llm_service
from apps.agent.services import relax, texts
from apps.agent.tests.base import (
    FakeLLM,
    FakeRetrieval,
    data_of,
    make_graph,
    request_lm,
    run_turn,
    understood,
)
from apps.chats.models import Message
from apps.curation.models import Collection, CollectionFilm
from apps.curation.tests.base import make_chat, make_story_film, make_user


def notes_of(call) -> str:
    return re.search(r"<notes>(.*?)</notes>", call.user, re.DOTALL).group(1)


class PromptLanguageRuleTests(SimpleTestCase):
    def test_chat_rules_demand_turkish_even_for_english_sources(self):
        rules = prompts.CHAT_RULES

        self.assertIn("ALWAYS write your reply in Turkish", rules)
        self.assertIn(
            "even when the editor's message, the notes or the source texts are in English", rules
        )
        self.assertIn("quotation marks", rules)
        self.assertIn(prompts.TITLE_RULE, rules)

    def test_task_sentences_repeat_the_language_rule(self):
        self.assertIn("ALWAYS write your reply in Turkish", prompts.RESPOND_SYSTEM)
        self.assertIn("announce, in Turkish,", prompts.RESPOND_SYSTEM)
        self.assertIn("ALWAYS write your reply in Turkish", prompts.ANSWER_SYSTEM)
        self.assertIn("answer the editor's message, in Turkish", prompts.ANSWER_SYSTEM)
        self.assertIn("explain them in Turkish", prompts.ANSWER_SYSTEM)

    def test_respond_prompt_forbids_talking_about_an_unstated_number(self):
        self.assertIn("The facts decide what is said about counts", prompts.RESPOND_SYSTEM)
        # Faz 1 düzeltme: "sayıyı söylemişti/söylememişti" kavramı istemde geçmez (modelin cevaba
        # "sayı belirtmemiştin, karşılaştırma yapmıyorum" diye sızdırdığı kaynak buydu).
        self.assertNotIn("stated a number", prompts.RESPOND_SYSTEM)


class AddressFormTests(SimpleTestCase):
    FORMAL = re.compile(
        r"(erseniz|arsanız|iniz|ınız|unuz|ünüz|siniz|sınız|sunuz|sünüz|\bsiz\b)", re.IGNORECASE
    )

    def test_request_summary_names_genres_in_turkish(self):
        request = ParsedRequest(en_query="x", hyde="y", genres=["Comedy", "crime", "Space Opera"])

        self.assertEqual(texts.request_summary(request), "komedi, suç, Space Opera")

    def fixed_texts(self) -> list[str]:
        sample = ParsedRequest(
            en_query="x", hyde="y", filters={"year_min": 2000, "countries": ["France"]}
        )
        return [
            agent_graph.REPLACE_FAILED_TEXT,
            *agent_graph.GENERIC_SUGGESTIONS,
            *agent_graph.EMPTY_SUGGESTIONS,
            *agent_graph.OTHER_SUGGESTIONS,
            *relax.RELAX_NOTICES.values(),
            relax.ALT_QUERY_NOTICE,
            texts.APPROVED_UNTOUCHED_NOTICE,
            texts.relaxed_filter_notice(("year_min", "countries")),
            *texts.search_done(3),
            *texts.read_done(0),
            *texts.read_done(4),
            texts.request_summary(sample),
            texts.request_summary(ParsedRequest(en_query="x", hyde="y", target_stated=False)),
            llm_service.MSG_UNAVAILABLE,
            llm_service.MSG_BUSY,
            llm_service.MSG_CONFIG,
            llm_service.MSG_BAD_OUTPUT,
            llm_service.MSG_TRUNCATED,
            llm_service.MSG_REFUSED,
            streaming.MSG_SERVER_ERROR,
            streaming.MSG_INCOMPLETE,
        ]

    def test_fixed_texts_address_the_editor_informally(self):
        for text in self.fixed_texts():
            with self.subTest(text=text):
                self.assertIsNone(self.FORMAL.search(text))

    def test_the_check_catches_formal_address(self):
        for formal in ("İsterseniz deneyelim.", "Bunu yapabilirsiniz.", "Siz seçin."):
            self.assertIsNotNone(self.FORMAL.search(formal), formal)

    def test_chat_rules_demand_informal_address(self):
        self.assertIn("speak to the editor directly in the second person", prompts.CHAT_RULES)
        self.assertIn('never the formal "siz"', prompts.CHAT_RULES)


class TargetStatedTests(SimpleTestCase):
    def raw(self, target):
        return request_lm(target_count=target)

    def test_number_said_by_the_editor_is_marked_stated(self):
        request = sanitize_request(self.raw(12))

        self.assertTrue(request.target_stated)
        self.assertEqual(request.target_count, 12)

    def test_missing_number_is_not_stated_and_selection_default_is_unchanged(self):
        request = sanitize_request(self.raw(None))

        self.assertFalse(request.target_stated)
        self.assertEqual(request.target_count, 10)  # seçimde kullanılan varsayılan aynı

    def test_missing_number_inherits_the_flag_of_the_previous_request(self):
        stated = sanitize_request(self.raw(None), fallback_target=12, fallback_stated=True)
        unstated = sanitize_request(self.raw(None), fallback_target=10, fallback_stated=False)

        self.assertEqual((stated.target_count, stated.target_stated), (12, True))
        self.assertEqual((unstated.target_count, unstated.target_stated), (10, False))

    def test_count_and_flag_matrix_for_first_requests_and_refinements(self):
        cases = [
            # ad, ham sayı, önceki (sayı, söylendi mi), beklenen (sayı, söylendi mi)
            ("a: ilk istek, sayı yok", None, (10, False), (10, False)),
            ("b: ilk istek, 8 film", 8, (10, False), (8, True)),
            ("c: düzeltme, sayı yok, önceki 8 söylenmiş", None, (8, True), (8, True)),
            ("d: düzeltme, sayı yok, önceki 10 söylenmemiş", None, (10, False), (10, False)),
            ("e: düzeltme, 15 film olsun", 15, (8, True), (15, True)),
        ]
        for name, raw_target, (prev_count, prev_stated), expected in cases:
            with self.subTest(name):
                request = sanitize_request(
                    self.raw(raw_target), fallback_target=prev_count, fallback_stated=prev_stated
                )

                self.assertEqual((request.target_count, request.target_stated), expected)

    def test_understanding_prompt_asks_for_null_when_the_message_states_no_number(self):
        line = next(
            line for line in prompts.UNDERSTAND_SYSTEM.splitlines() if "target_count:" in line
        )

        self.assertIn("CURRENT message", line)
        self.assertIn("otherwise null", line)
        self.assertIn("Never copy the number from <previous_request>", line)
        self.assertNotIn("10 if not stated", prompts.UNDERSTAND_SYSTEM)

    def test_records_without_the_field_count_as_stated(self):
        old = ParsedRequest.model_validate({"en_query": "x", "hyde": "y", "target_count": 7})

        self.assertTrue(old.target_stated)

    def test_summary_does_not_attribute_an_unstated_number_to_the_editor(self):
        stated = ParsedRequest(en_query="x", hyde="y", target_count=12)
        unstated = ParsedRequest(en_query="x", hyde="y", target_stated=False)

        self.assertEqual(texts.request_summary(stated), "12 filmlik bir seçki istiyorsun.")
        self.assertEqual(texts.request_summary(unstated), "Bir film seçkisi istiyorsun.")
        self.assertNotIn("10", texts.request_summary(unstated))

    def test_count_note_gives_exact_facts_and_compares_only_when_a_number_was_stated(self):
        stated = ParsedRequest(en_query="x", hyde="y", target_count=8)
        unstated = ParsedRequest(en_query="x", hyde="y", target_stated=False)

        met = texts.count_note(8, stated)
        self.assertEqual(
            met,
            "Requested number of films: 8. Films in the saved collection: 8. "
            "The request is fully met; nothing is missing.",
        )
        for forbidden in ("fewer", "only", "short"):
            self.assertNotIn(forbidden, met.lower())
        self.assertIn("Missing: 2", texts.count_note(6, stated))
        free = texts.count_note(7, unstated)
        self.assertEqual(free, "Films in the saved collection: 7.")


class EditorTextFlowTestCase(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.chat = make_chat(self.user)
        self.films = [make_story_film(n) for n in range(1, 9)]
        self.ids = [film.pk for film in self.films]

    def graph(self, llm, *results):
        retrieval = FakeRetrieval(*results)
        return make_graph(llm, retrieval), retrieval


class UnstatedTargetFlowTests(EditorTextFlowTestCase):
    async def test_respond_notes_do_not_mention_a_requested_number_when_editor_gave_none(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=None)))
        graph, _ = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalarda polisiyeler")

        self.assertEqual(len(data_of(events, "collection")[0]["films"]), 8)
        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn("Films in the saved collection: 8", notes)
        for forbidden in ("Requested", "Missing", "10", "did not state", "fit well enough"):
            self.assertNotIn(forbidden, notes)
        self.assertNotIn("10", notes)
        detail = data_of(events, "step.done")[0]["detail"]
        self.assertNotIn("10", detail)

    async def test_model_writing_10_without_a_number_in_the_message_is_not_stated(self):
        # Kod güvencesi: mesajda sayı yoksa modelin yazdığı sayı "söylendi" sayılmaz.
        llm = FakeLLM(understand=understood(request=request_lm(target_count=10)))
        graph, _ = self.graph(llm, self.ids)

        await run_turn(graph, self.chat, self.user, "Karlı kasabalarda polisiyeler")

        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn("Films in the saved collection: 8.", notes)
        self.assertNotIn("Requested", notes)
        self.assertNotIn("Missing", notes)

    async def test_refine_without_a_number_after_an_unstated_request_stays_unstated(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=None)))
        graph, _ = self.graph(llm, self.ids)
        await run_turn(graph, self.chat, self.user, "Karlı kasabalarda polisiyeler")
        llm.understand = understood("refine", request=request_lm(target_count=None))

        await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        collection = await Collection.objects.aget(chat=self.chat)
        self.assertEqual(collection.request["target_count"], 10)
        self.assertFalse(collection.request["target_stated"])
        self.assertNotIn("Requested number", notes_of(llm.steps("respond")[-1]))

    async def test_respond_notes_keep_the_requested_number_when_editor_stated_it(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=10)))
        graph, _ = self.graph(llm, self.ids)

        await run_turn(graph, self.chat, self.user, "10 film istiyorum")

        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn(
            "Requested number of films: 10. Films in the saved collection: 8. Missing: 2.",
            notes,
        )

    async def test_refine_keeps_the_stated_flag_of_the_draft_request(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=10)))
        graph, _ = self.graph(llm, self.ids)
        await run_turn(graph, self.chat, self.user, "10 film istiyorum")
        llm.understand = understood("refine", request=request_lm(target_count=None))

        await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        collection = await Collection.objects.aget(chat=self.chat)
        self.assertEqual(collection.request["target_count"], 10)
        self.assertTrue(collection.request["target_stated"])
        self.assertIn("Requested number of films: 10", notes_of(llm.steps("respond")[-1]))

    async def latest_request(self):
        collection = await Collection.objects.filter(chat=self.chat).order_by("-id").afirst()
        return collection.request["target_count"], collection.request["target_stated"]

    async def test_count_and_flag_carry_over_only_when_the_same_selection_continues(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=8)))
        graph, _ = self.graph(llm, self.ids)

        await run_turn(graph, self.chat, self.user, "8 film istiyorum")
        self.assertEqual(await self.latest_request(), (8, True))
        # Aynı seçkiyi sürdüren düzeltme: önceki istekten devralır.
        llm.understand = understood("refine", request=request_lm(target_count=None))
        await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")
        self.assertEqual(await self.latest_request(), (8, True))
        self.assertEqual(await Collection.objects.acount(), 1)
        # Aynı sohbette sayısız YENİ konu: devralmaz.
        llm.understand = understood(request=request_lm(target_count=None))
        await run_turn(graph, self.chat, self.user, "Bir de Fransız komedileri")
        self.assertEqual(await Collection.objects.acount(), 2)
        self.assertEqual(await self.latest_request(), (10, False))
        # Yeni konunun sayısız düzeltmesi yeni konunun bayrağını sürdürür.
        llm.understand = understood("refine", request=request_lm(target_count=None))
        await run_turn(graph, self.chat, self.user, "Daha eski olsun")
        self.assertEqual(await Collection.objects.acount(), 2)
        self.assertEqual(await self.latest_request(), (10, False))
        self.assertNotIn("Requested number", notes_of(llm.steps("respond")[-1]))

    async def test_previous_request_given_to_the_understanding_prompt_is_unchanged(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, self.ids)
        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        llm.understand = understood("refine", instruction="darker")

        await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        parse_input = llm.steps("parse")[-1].user
        self.assertIn("<previous_request>", parse_input)
        self.assertNotIn("target_stated", parse_input)  # anlama istemi eskisiyle aynı


class ApprovedCollectionFlowTests(EditorTextFlowTestCase):
    async def approved_draft(self, llm, graph):
        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        first = data_of(events, "collection")[0]
        await Collection.objects.filter(pk=first["id"]).aupdate(status="approved")
        return first

    async def test_new_request_after_approval_tells_the_editor_and_leaves_the_approved_one(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, self.ids)
        first = await self.approved_draft(llm, graph)
        before = [
            (row.film_id, row.rationale, row.position)
            async for row in CollectionFilm.objects.filter(collection_id=first["id"]).order_by(
                "position"
            )
        ]

        events = await run_turn(graph, self.chat, self.user, "Bir de Fransız komedileri")

        notices = data_of(events, "notice")
        self.assertEqual([n["text"] for n in notices], [texts.APPROVED_UNTOUCHED_NOTICE])
        self.assertEqual(notices[0]["text"], "Onayladığın seçkiye dokunmadım; bu yeni bir taslak.")
        order = [name for name, _ in events]
        self.assertLess(order.index("notice"), order.index("collection"))
        saved = await Message.objects.aget(pk=data_of(events, "message.start")[0]["message_id"])
        self.assertIn("notice", [step["key"] for step in saved.steps])
        self.assertIn(
            f"Already told the editor: {texts.APPROVED_UNTOUCHED_NOTICE}",
            notes_of(llm.steps("respond")[-1]),
        )
        # Onaylı koleksiyon değişmedi; yeni istek ayrı bir taslak açtı.
        new = data_of(events, "collection")[0]
        self.assertNotEqual(new["id"], first["id"])
        approved = await Collection.objects.aget(pk=first["id"])
        self.assertEqual((approved.status, approved.version), ("approved", 1))
        after = [
            (row.film_id, row.rationale, row.position)
            async for row in CollectionFilm.objects.filter(collection_id=first["id"]).order_by(
                "position"
            )
        ]
        self.assertEqual(after, before)

    async def test_refine_on_an_approved_collection_is_also_a_new_draft_with_the_notice(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, self.ids)
        await self.approved_draft(llm, graph)
        llm.understand = understood("refine", instruction="darker")

        events = await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        self.assertEqual(
            [n["text"] for n in data_of(events, "notice")], [texts.APPROVED_UNTOUCHED_NOTICE]
        )

    async def test_no_notice_for_a_first_request_or_an_open_draft(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, self.ids)

        first = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        llm.understand = understood("refine", instruction="darker")
        second = await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        self.assertEqual(data_of(first, "notice"), [])
        self.assertEqual(data_of(second, "notice"), [])
        self.assertNotIn("Onayladığın", "".join(notes_of(c) for c in llm.steps("respond")))

    async def test_question_about_an_approved_collection_gets_no_notice(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, self.ids)
        first = await self.approved_draft(llm, graph)
        llm.understand = understood("question", request=None, film_id=first["films"][0]["film_id"])

        events = await run_turn(graph, self.chat, self.user, "Bu film neden seçildi?")

        self.assertEqual(data_of(events, "notice"), [])


class ReplaceFilmNotesTests(EditorTextFlowTestCase):
    async def test_replace_turn_sends_only_notes_about_the_swap(self):
        llm = FakeLLM()
        # İkinci arama (film değiştirme) filtre gevşetme bildirimi üretir.
        graph, _ = self.graph(llm, self.ids, (self.ids, ("year_min", "countries")))
        first = data_of(
            await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film"), "collection"
        )[0]
        first_ids = [film["film_id"] for film in first["films"]]
        remaining = [fid for fid in self.ids if fid not in first_ids]
        llm.fit_ids = set(self.ids) - {remaining[2]}
        llm.partial_ids = {remaining[2]}  # kısmi eşleşme notu da tetiklenebilirdi

        events = await run_turn(
            graph,
            self.chat,
            self.user,
            "Bunun yerine başkasını bul",
            action={"type": "replace_film", "film_id": first_ids[1]},
        )

        self.assertEqual(len(data_of(events, "notice")), 1)  # bildirim editöre yine gösterilir
        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn("Swap done", notes)
        self.assertNotIn("Already told", notes)
        self.assertNotIn("Requested number", notes)
        self.assertNotIn("Films in the saved collection", notes)
        self.assertNotIn("partly", notes)

    async def test_replace_turn_still_reports_candidates_dropped_for_their_quote(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, self.ids)
        first = data_of(
            await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film"), "collection"
        )[0]
        first_ids = [film["film_id"] for film in first["films"]]
        remaining = [fid for fid in self.ids if fid not in first_ids]
        llm.bad_quote_ids = {remaining[0]}

        await run_turn(
            graph,
            self.chat,
            self.user,
            "Bunun yerine başkasını bul",
            action={"type": "replace_film", "film_id": first_ids[1]},
        )

        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn("1 replacement candidate(s) were skipped", notes)
        self.assertIn("Swap done", notes)

    async def test_non_replace_turns_keep_their_general_notes(self):
        llm = FakeLLM(partial_ids={self.ids[6], self.ids[7]}, fit_ids=set(self.ids[:6]))
        graph, _ = self.graph(llm, (self.ids, ("year_min",)))

        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn("Already told the editor", notes)
        self.assertIn("2 more films matched only partly", notes)
