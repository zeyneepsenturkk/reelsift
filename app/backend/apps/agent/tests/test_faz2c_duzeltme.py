"""Faz 2c düzeltme turu: cevap denetiminde film adları ve alıntılar, göreli film sayısı ("N tane
daha ekle"), cümle düzeyinde akış, anlama istemindeki çift ad ve daraltılmış `talimat` kalıbı."""

from asgiref.sync import sync_to_async
from django.test import SimpleTestCase, TestCase

from apps.agent import prompts
from apps.agent.schemas import PersonLM
from apps.agent.services import data, language
from apps.agent.tests.base import (
    FakeLLM,
    FakeRetrieval,
    data_of,
    make_graph,
    request_lm,
    run_turn,
    understood,
)
from apps.agent.tests.test_editor_texts import notes_of
from apps.chats.models import Message
from apps.curation.models import Collection
from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user

LYNCH = PersonLM(name="David Lynch", role="director")


class LeakCheckTitleTests(SimpleTestCase):
    def test_legitimate_english_titles_are_not_caught(self):
        cases = (
            (
                "Taslakta The Girl with the Dragon Tattoo da var, istersen çıkarırım.",
                ["The Girl with the Dragon Tattoo"],
            ),
            (
                "Seçkide The Man with the Golden Arm ve Kader birbirine yakın duruyor.",
                ["The Man with the Golden Arm", "Kader"],
            ),
            (
                "Seçkiyi The Good, the Bad and the Ugly ile açtım, sonra Kış Uykusu geliyor.",
                ["The Good, the Bad and the Ugly"],
            ),
        )
        for text, titles in cases:
            with self.subTest(text=text):
                self.assertFalse(language.leaks_internal_phrasing(text, titles))

    def test_quoted_passages_are_not_checked(self):
        for text in (
            'Hikâye şöyle başlıyor: "The detective was there with the list that has names".',
            "Alıntı: “The man that was there has the list with him” cümlesi öne çıkıyor.",
            "Şu cümle dikkat çekiyor: «The list that has the names was there».",
        ):
            with self.subTest(text=text):
                self.assertFalse(language.leaks_internal_phrasing(text))

    def test_rewrite_note_keeps_titles_and_quotes_untouched(self):
        self.assertIn(
            "film titles and quoted passages stay exactly as they are", prompts.REWRITE_NOTE
        )
        self.assertNotIn("entirely in Turkish", prompts.REWRITE_NOTE)


class InstructionPatternTests(SimpleTestCase):
    def test_only_references_to_the_internal_instructions_are_caught(self):
        for text in (
            "Talimatlara göre seçkide altı film var.",
            "Talimatıma uymak için ayrıntıya girmiyorum.",
            "Talimatlarım gereği bunu söyleyemem.",
            "Bana verilen talimat bu yöndeydi.",
        ):
            with self.subTest(text=text):
                self.assertTrue(language.leaks_internal_phrasing(text))

    def test_story_sentences_with_the_word_pass(self):
        for text in (
            "Filmde komutanın talimatıyla köyün bütün yolları kapatılıyor.",
            "Hikâyede ajan, talimat bekleyen bir muhbirle tanışıyor.",
        ):
            with self.subTest(text=text):
                self.assertFalse(language.leaks_internal_phrasing(text))


class SentenceSplitTests(SimpleTestCase):
    def test_pops_only_completed_sentences(self):
        self.assertIsNone(language.pop_sentence("Seçki hazır"))
        self.assertIsNone(language.pop_sentence("Puanı 3.5"))
        self.assertEqual(
            language.pop_sentence("Seçki hazır. Altı film"), ("Seçki hazır. ", "Altı film")
        )
        self.assertEqual(language.pop_sentence("Hazır mı? Evet."), ("Hazır mı? ", "Evet."))


class FlowCase(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.chat = make_chat(self.user)
        self.films = [make_story_film(n) for n in range(1, 21)]
        self.ids = [film.pk for film in self.films]

    def graph(self, llm, *results, **kwargs):
        return make_graph(llm, FakeRetrieval(*results, **kwargs))

    async def start_draft(self, graph, llm, request=None, **kwargs):
        llm.understand = understood(request=request or request_lm(target_count=10), **kwargs)
        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        return data_of(events, "collection")[0]

    async def refine(self, graph, llm, text="2 tane daha ekle", **overrides):
        request = request_lm(target_count=None, target_delta=2)
        request = request.model_copy(update=overrides)
        llm.understand = understood("refine", request=request)
        events = await run_turn(graph, self.chat, self.user, text)
        return data_of(events, "collection")[0]

    def film_ids(self, collection):
        return [film["film_id"] for film in collection["films"]]


class RelativeCountTests(FlowCase):
    async def test_adding_two_keeps_the_ten_films_and_adds_two(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        first = await self.start_draft(graph, llm)

        second = await self.refine(graph, llm)

        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(second["films"]), 12)
        self.assertEqual(self.film_ids(second)[:10], self.film_ids(first))
        self.assertEqual(
            [f["rationale"] for f in second["films"][:10]],
            [f["rationale"] for f in first["films"]],
        )
        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn(
            "Films requested to add: 2. Films added: 2. Films in the saved collection now: 12.",
            notes,
        )
        self.assertNotIn("Missing", notes)
        self.assertNotIn("Requested number", notes)
        # Yalnız 2 yeni film için gerekçe yazıldı; taslaktaki filmler yeniden elenmedi.
        self.assertEqual(llm.steps("write")[-1].user.count("<film id="), 2)
        self.assertEqual(len(llm.steps("select")), 1)

    async def test_with_one_eligible_new_film_the_one_is_added_and_the_note_says_so(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        first = await self.start_draft(graph, llm)
        first_ids = self.film_ids(first)
        extra = next(fid for fid in self.ids if fid not in first_ids)
        llm.fit_ids = set(first_ids) | {extra}

        second = await self.refine(graph, llm)

        self.assertEqual(self.film_ids(second), [*first_ids, extra])
        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn("Films requested to add: 2. Films added: 1.", notes)
        self.assertIn("Films in the saved collection now: 11.", notes)

    async def test_removing_two_shrinks_the_target_and_reports_the_change(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        await self.start_draft(graph, llm)

        second = await self.refine(graph, llm, text="2 filmi çıkar", target_delta=-2)

        self.assertEqual(len(second["films"]), 8)
        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn(
            "Films requested to remove: 2. Films removed: 2. Films in the saved collection now: 8.",
            notes,
        )

    async def test_the_relative_field_wins_over_a_wrong_total(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        await self.start_draft(graph, llm)

        second = await self.refine(graph, llm, target_count=2)

        self.assertEqual(len(second["films"]), 12)

    async def test_the_target_is_clipped_to_twenty(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        await self.start_draft(graph, llm, request=request_lm(target_count=19))

        second = await self.refine(graph, llm, target_delta=5)

        self.assertEqual(len(second["films"]), 20)

    async def test_without_an_open_draft_the_relative_field_is_ignored(self):
        llm = FakeLLM(
            understand=understood("refine", request=request_lm(target_count=None, target_delta=2))
        )
        graph = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "2 tane daha ekle")

        collection = data_of(events, "collection")[0]
        self.assertEqual(len(collection["films"]), 10)  # varsayılan sayı; 2 değil, 12 değil
        self.assertNotIn("Films requested", notes_of(llm.steps("respond")[-1]))

    async def test_a_new_search_ignores_the_relative_field(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        await self.start_draft(graph, llm)
        llm.understand = understood(
            "new_search", request=request_lm(target_count=4, target_delta=2)
        )

        events = await run_turn(graph, self.chat, self.user, "Başka bir konu, 4 film")

        self.assertEqual(len(data_of(events, "collection")[0]["films"]), 4)

    async def test_a_change_with_a_new_criterion_is_not_add_only(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        await self.start_draft(graph, llm)
        llm.understand = understood(
            "refine",
            request=request_lm(target_count=None, target_delta=2),
            instruction="darker",
        )

        second = await run_turn(graph, self.chat, self.user, "2 tane daha, daha karanlık")

        collection = data_of(second, "collection")[0]
        self.assertEqual(len(collection["films"]), 12)
        # Seçim modele soruldu: yalnız ekleme akışı değil, genel güncelleme.
        self.assertEqual(len(llm.steps("select")), 2)

    async def test_person_request_three_plus_two_gives_five_films_of_the_person(self):
        lynch = [
            await sync_to_async(make_story_film)(n, directors=["David Lynch"])
            for n in range(21, 29)
        ]
        lynch_ids = [film.pk for film in lynch]
        llm = FakeLLM()
        graph = self.graph(
            llm,
            lynch_ids,
            people_found=[("David Lynch", 8)],
            sources={fid: ("person",) for fid in lynch_ids},
            people_index={"David Lynch": lynch_ids},
        )
        request = request_lm(theme_present=False, target_count=3)
        llm.understand = understood(request=request, people=[LYNCH])
        events = await run_turn(graph, self.chat, self.user, "David Lynch'in 3 filmi")
        first = data_of(events, "collection")[0]
        self.assertEqual(len(first["films"]), 3)

        llm.understand = understood(
            "refine",
            request=request_lm(theme_present=False, target_count=None, target_delta=2),
            people=[LYNCH],
        )
        events = await run_turn(graph, self.chat, self.user, "2 tane daha")

        second = data_of(events, "collection")[0]
        self.assertEqual(len(second["films"]), 5)
        self.assertEqual(self.film_ids(second)[:3], self.film_ids(first))
        self.assertTrue(set(self.film_ids(second)) <= set(lynch_ids))
        self.assertEqual(llm.steps("judge"), [])


class StreamingTests(FlowCase):
    async def delivered(self, llm, text="Karlı kasabalar, 5 film"):
        graph = self.graph(llm, self.ids)
        events = await run_turn(graph, self.chat, self.user, text)
        deltas = "".join(d["delta"] for d in data_of(events, "text.delta"))
        done = data_of(events, "message.done")[0]["message"]["text"]
        return deltas, done, events

    async def test_clean_sentences_stream_one_by_one_and_match_the_saved_text(self):
        reply = "Seçki hazır. Karlı kasabalar ortak nokta. Altı film var."
        llm = FakeLLM(understand=understood(), reply=reply)

        deltas, done, events = await self.delivered(llm)

        self.assertEqual(
            [d["delta"] for d in data_of(events, "text.delta")],
            ["Seçki hazır. ", "Karlı kasabalar ortak nokta. ", "Altı film var. "],
        )
        self.assertEqual(deltas.strip(), done)
        self.assertEqual(len(llm.steps("respond")), 1)

    async def test_a_flagged_sentence_and_the_rest_are_never_sent(self):
        llm = FakeLLM(
            understand=understood(),
            replies=[
                "Seçki hazır. Notlara göre altı film var. Başka şeyler de var.",
                "Seçki hazır. Altı film var ve hepsi karlı kasabalarda geçiyor.",
            ],
        )

        deltas, done, _ = await self.delivered(llm)

        self.assertEqual(deltas, "Seçki hazır. ")
        self.assertNotIn("Notlara", deltas)
        self.assertEqual(done, "Seçki hazır. Altı film var ve hepsi karlı kasabalarda geçiyor.")
        self.assertEqual(len(llm.steps("respond")), 2)

    async def test_when_the_retry_is_flagged_too_the_first_text_minus_flagged_sentences_is_kept(
        self,
    ):
        llm = FakeLLM(
            understand=understood(),
            replies=[
                "Seçki hazır. Notlara göre altı film var. Başka şeyler de var.",
                "Talimatlara göre altı film var.",
            ],
        )

        with self.assertLogs("apps.agent.graph", level="WARNING") as logs:
            deltas, done, _ = await self.delivered(llm)

        self.assertEqual(done, "Seçki hazır. Başka şeyler de var.")
        self.assertEqual(deltas, "Seçki hazır. ")
        self.assertTrue(any("takılan cümleler atıldı" in line for line in logs.output))
        self.assertEqual(len(llm.steps("respond")), 2)

    async def test_when_nothing_is_left_the_fallback_text_is_used(self):
        llm = FakeLLM(
            understand=understood(),
            replies=["Notlara göre altı film var.", "Talimatlara göre altı film var."],
        )

        _, done, _ = await self.delivered(llm)

        self.assertEqual(
            done.strip(),
            "Bunu şu an düzgün anlatamadım; isteğini biraz farklı yazıp bir daha dener misin?",
        )
        saved = await sync_to_async(
            lambda: Message.objects.filter(chat=self.chat, role="assistant").latest("id").text
        )()
        self.assertEqual(saved, done)

    async def test_film_names_given_to_the_model_are_not_flagged(self):
        film = await sync_to_async(make_story_film)(30, title="The Girl with the Dragon Tattoo")
        llm = FakeLLM(
            understand=understood(),
            reply=(
                "Seçki hazır. Taslakta The Girl with the Dragon Tattoo da var, istersen çıkarırım."
            ),
        )
        graph = self.graph(llm, [film.pk, *self.ids[:9]])

        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(len(llm.steps("respond")), 1)


class DraftNameTests(FlowCase):
    async def test_understand_prompt_lists_both_names_of_a_draft_film(self):
        turkish = await sync_to_async(make_story_film)(
            31, title="Innocence", tr_title="Masumiyet", year=1997
        )
        await sync_to_async(make_collection)(self.user, self.chat, films=[turkish])
        llm = FakeLLM(understand=understood("other"))
        graph = self.graph(llm, [])

        await run_turn(graph, self.chat, self.user, "Innocence'ı çıkar")

        parse_prompt = llm.steps("parse")[-1].user
        self.assertIn(f"- [{turkish.pk}] Masumiyet (Innocence, 1997)", parse_prompt)

    async def test_the_screen_name_stays_for_the_step_detail(self):
        turkish = await sync_to_async(make_story_film)(
            31, title="Innocence", tr_title="Masumiyet", year=1997
        )
        collection = await sync_to_async(make_collection)(self.user, self.chat, films=[turkish])
        context = await sync_to_async(data.load_turn_context)(self.chat.pk, self.user.pk, 10**9)

        self.assertEqual(context.draft_films[0][1], "Masumiyet")
        self.assertEqual(context.draft_model_names, ("Masumiyet (Innocence, 1997)",))
        self.assertEqual(await Collection.objects.acount(), 1)
        self.assertEqual(collection.status, "draft")


class QuoteAwareSplitTests(SimpleTestCase):
    QUOTE = (
        'Alıntı şöyle: "The man was released from prison. He has the key with the map that was '
        'lost." Bu da yalnızlığı gösteriyor. '
    )

    def test_a_two_sentence_quote_is_not_split(self):
        popped = language.pop_sentence(self.QUOTE)

        self.assertEqual(popped, (self.QUOTE, ""))

    def test_all_quote_styles_hold_the_sentence_together(self):
        for open_, close in (('"', '"'), ("“", "”"), ("«", "»"), ("„", "“")):
            text = f"Şöyle dedi: {open_}Birinci cümle. İkinci cümle.{close} Sonra gitti. Son."
            with self.subTest(open_=open_):
                self.assertEqual(
                    language.pop_sentence(text),
                    ("Şöyle dedi: " + text[12 : text.index("gitti.") + 7], "Son."),
                )

    def test_an_unclosed_quote_waits_for_the_end_of_the_stream(self):
        self.assertIsNone(language.pop_sentence('Şöyle dedi: "Birinci cümle. İkinci cümle. '))


class QuoteStreamTests(FlowCase):
    async def test_the_quoted_example_streams_whole_and_the_saved_text_matches(self):
        reply = QuoteAwareSplitTests.QUOTE.strip()
        llm = FakeLLM(understand=understood(), reply=reply)
        graph = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        deltas = "".join(d["delta"] for d in data_of(events, "text.delta"))
        done = data_of(events, "message.done")[0]["message"]["text"]
        self.assertEqual(len(llm.steps("respond")), 1)
        self.assertEqual(deltas.strip(), reply)
        self.assertEqual(done, reply)

    async def test_a_quote_that_never_closes_is_not_lost(self):
        reply = 'Şöyle dedi: "Birinci cümle burada. İkinci cümle de burada ve bitmiyor.'
        llm = FakeLLM(understand=understood(), reply=reply)
        graph = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        done = data_of(events, "message.done")[0]["message"]["text"]
        self.assertEqual(done, reply)
        self.assertEqual("".join(d["delta"] for d in data_of(events, "text.delta")).strip(), reply)


class ShortTextLanguageTests(SimpleTestCase):
    def test_short_remainder_is_not_judged_for_language(self):
        text = "Seçkide The Good, the Bad and the Ugly var. Hepsi güzel."

        self.assertFalse(language.leaks_internal_phrasing(text, ["The Good, the Bad and the Ugly"]))

    def test_a_long_english_text_is_still_not_turkish(self):
        text = "The selection has eight films and all of them are set in small snowy towns."

        self.assertTrue(language.leaks_internal_phrasing(text))


class NumberGuardTests(SimpleTestCase):
    def test_numbers_and_number_words_count(self):
        from apps.agent.graph import mentions_number

        for text in ("5 film", "beş film", "2 tane daha ekle", "On iki film olsun", "12 Angry Men"):
            with self.subTest(text=text):
                self.assertTrue(mentions_number(text))
        for text in (
            "The Girl with the Dragon Tattoo gibi filmler",
            "birkaç film",
            "Karlı kasabalar",
        ):
            with self.subTest(text=text):
                self.assertFalse(mentions_number(text))


class NumberGuardFlowTests(FlowCase):
    async def test_a_number_the_model_invented_is_not_stated(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=8)))
        graph = self.graph(llm, self.ids)

        events = await run_turn(
            graph, self.chat, self.user, "The Girl with the Dragon Tattoo gibi filmler"
        )

        self.assertEqual(len(data_of(events, "collection")[0]["films"]), 10)  # varsayılan
        notes = notes_of(llm.steps("respond")[-1])
        self.assertNotIn("Requested number", notes)

    async def test_a_stated_number_is_kept(self):
        for text in ("5 film öner", "beş film öner"):
            with self.subTest(text=text):
                llm = FakeLLM(understand=understood(request=request_lm(target_count=5)))
                graph = self.graph(llm, self.ids)
                events = await run_turn(graph, self.chat, self.user, text)
                self.assertEqual(len(data_of(events, "collection")[0]["films"]), 5)
                self.assertIn("Requested number of films: 5", notes_of(llm.steps("respond")[-1]))


class TotalCountAddOnlyTests(FlowCase):
    async def test_total_target_above_the_draft_keeps_films_and_adds_the_difference(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        first = await self.start_draft(graph, llm, request=request_lm(target_count=6))
        llm.understand = understood("refine", request=request_lm(target_count=8))

        events = await run_turn(graph, self.chat, self.user, "toplam 8 film olsun")

        second = data_of(events, "collection")[0]
        self.assertEqual(len(second["films"]), 8)
        self.assertEqual(self.film_ids(second)[:6], self.film_ids(first))
        self.assertIn(
            "Films requested to add: 2. Films added: 2. Films in the saved collection now: 8.",
            notes_of(llm.steps("respond")[-1]),
        )

    async def test_with_too_few_new_candidates_it_adds_what_exists(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        first = await self.start_draft(graph, llm, request=request_lm(target_count=6))
        first_ids = self.film_ids(first)
        extra = next(fid for fid in self.ids if fid not in first_ids)
        llm.fit_ids = set(first_ids) | {extra}
        llm.understand = understood("refine", request=request_lm(target_count=8))

        events = await run_turn(graph, self.chat, self.user, "toplam 8 film olsun")

        second = data_of(events, "collection")[0]
        self.assertEqual(self.film_ids(second), [*first_ids, extra])
        self.assertIn("Films added: 1.", notes_of(llm.steps("respond")[-1]))

    async def test_a_total_below_the_draft_is_the_old_flow(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        await self.start_draft(graph, llm, request=request_lm(target_count=6))
        llm.understand = understood("refine", request=request_lm(target_count=4))

        events = await run_turn(graph, self.chat, self.user, "toplam 4 film olsun")

        self.assertEqual(len(data_of(events, "collection")[0]["films"]), 4)


class EmptyRefineRequestTests(FlowCase):
    async def test_a_blank_en_query_on_refine_continues_with_the_previous_request(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        first = await self.start_draft(graph, llm, request=request_lm(target_count=3))

        second = await self.refine(graph, llm, en_query="", hyde="")

        self.assertEqual(len(second["films"]), 5)
        self.assertEqual(self.film_ids(second)[:3], self.film_ids(first))
        saved = await Collection.objects.aget(pk=second["id"])
        self.assertEqual(saved.request["en_query"], request_lm().en_query)
        self.assertEqual(saved.request["filters"]["countries"], ["Finland"])

    async def test_a_null_request_on_refine_continues_with_the_previous_request(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        first = await self.start_draft(graph, llm, request=request_lm(target_count=3))
        llm.understand = understood("refine")
        llm.understand.request = None

        events = await run_turn(graph, self.chat, self.user, "2 tane daha ekle")

        second = data_of(events, "collection")[0]
        self.assertEqual(self.film_ids(second)[:3], self.film_ids(first))
        saved = await Collection.objects.aget(pk=second["id"])
        self.assertEqual(saved.request["en_query"], request_lm().en_query)
        self.assertEqual(saved.request["target_count"], 3)

    async def test_a_blank_en_query_on_a_new_search_is_still_an_error(self):
        llm = FakeLLM(
            understand=understood(request=request_lm(en_query="  ")),
        )
        graph = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(data_of(events, "error")[0]["code"], "model_error")


class EnglishQuoteStreamTests(FlowCase):
    REPLIES = (
        "Şu sahne bana çok yakın geldi: “The man was released from prison.” Bunu seçkiye ekledim.",
        'Hikâyenin ilk cümlesi şöyle: "The man was released. He has the key with the map." '
        "Bu yüzden seçkiyi buna göre kurdum.",
        "Alıntılar şöyle: “The list that has the names was there” ve "
        '"Previously the list starts with the end." Böylece seçkiyi tamamladım.',
        'Hikâye şöyle açılıyor: “The man was released from prison. He has the key with the map." '
        "Bu yüzden seçkiyi buna göre kurdum.",
        'Hikâye şöyle açılıyor: "The man was released from prison and he walked for many days '
        "across the frozen land. The key that was lost has the map with the names of the "
        "people who were there before the winter came to the town.",
    )

    async def test_english_quotes_are_neither_caught_nor_cut(self):
        for reply in self.REPLIES:
            with self.subTest(reply=reply):
                llm = FakeLLM(understand=understood(), reply=reply)
                graph = self.graph(llm, self.ids)

                events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

                deltas = "".join(d["delta"] for d in data_of(events, "text.delta"))
                done = data_of(events, "message.done")[0]["message"]["text"]
                self.assertEqual(len(llm.steps("respond")), 1)
                self.assertEqual(deltas.strip(), reply)
                self.assertEqual(done, reply)


class FullDraftTests(FlowCase):
    async def test_adding_to_a_twenty_film_draft_leaves_it_as_is_and_says_why(self):
        llm = FakeLLM()
        graph = self.graph(llm, self.ids)
        first = await self.start_draft(graph, llm, request=request_lm(target_count=20))
        self.assertEqual(len(first["films"]), 20)

        second = await self.refine(graph, llm)

        self.assertEqual(self.film_ids(second), self.film_ids(first))
        self.assertEqual(len(llm.steps("select")), 1)  # yeniden seçim yok
        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn("Films added: 0.", notes)
        self.assertIn("A collection holds at most 20 films", notes)
