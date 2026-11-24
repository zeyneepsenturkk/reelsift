"""Faz 1 düzeltme turu: düzeltmede kişi kısıtı taslağın eski filmlerine de uygulanır, sayı
söylenmemiş kişi isteğinde hedef kişinin film sayısıdır, notlarda yönerge yoktur, varlık
sorusu taslak üretmez, kişi + tema isteğinde kişi evreni tümüyle okunur, filtre notu, önceki
kişi korunur."""

import re

from asgiref.sync import sync_to_async
from django.conf import settings
from django.test import override_settings

from apps.agent import prompts
from apps.agent.schemas import PersonLM
from apps.agent.services import texts
from apps.agent.tests.base import FakeLLM, data_of, request_lm, run_turn, understood
from apps.agent.tests.test_editor_texts import notes_of
from apps.agent.tests.test_faz1 import LYNCH, PersonFlowCase
from apps.curation.models import Collection
from apps.curation.tests.base import make_story_film
from apps.films.models import Film

# Yönerge ya da "söylemem gerekmiyor" türü cümleler olgu notlarında bulunmaz.
DIRECTIVE_WORDS = (
    "missing",
    "compar",
    "never",
    "do not",
    "don't",
    "need not",
    "should not",
    "no need",
    "not stated",
    "unstated",
    "not required",
)


def film_ids_of(events) -> list[int]:
    return [film["film_id"] for film in data_of(events, "collection")[0]["films"]]


class RefineKeepsThePersonConstraintTests(PersonFlowCase):
    """Taslakta 2 Lynch + 3 başka yönetmen filmi; düzeltme `people=[Lynch]` ile gelir."""

    async def start_with_a_mixed_draft(self, llm, second=None):
        others = self.ids[2:5]
        await sync_to_async(Film.objects.filter(pk__in=others).update)(directors=["Other Director"])
        first = self.ids[:5]
        second = second or [self.ids[5], self.ids[6], self.ids[7], self.ids[0], self.ids[1]]
        lynch_films = [self.ids[0], self.ids[1], self.ids[5], self.ids[6], self.ids[7]]
        graph, retrieval_double = self.graph(
            llm,
            first,
            second,
            people_found=[("David Lynch", 5)],
            people_index={"David Lynch": lynch_films},
        )
        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        self.assertEqual(set(film_ids_of(events)), set(first))
        return graph, set(lynch_films)

    async def test_themed_refine_keeps_only_the_persons_films(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=5)))
        graph, lynch = await self.start_with_a_mixed_draft(llm)
        llm.understand = understood(
            "refine",
            request=request_lm(target_count=5, theme_present=True),
            instruction="Only the films of David Lynch.",
            people=[LYNCH],
        )

        events = await run_turn(graph, self.chat, self.user, "Sadece David Lynch filmleri kalsın")

        shown = film_ids_of(events)
        self.assertEqual(len(shown), 5)
        self.assertLessEqual(set(shown), lynch)
        read = list(map(int, re.findall(r'<film id="(\d+)">', llm.steps("judge")[-1].user)))
        self.assertTrue(set(read) <= lynch)  # kişi dışı eski film hiç okunmaz

    async def test_person_only_refine_without_a_theme_keeps_only_the_persons_films(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=5)))
        # Aramanın getirdiği az film: taslağın eski filmleri boşluğu doldurmasın.
        graph, lynch = await self.start_with_a_mixed_draft(llm, second=[self.ids[5], self.ids[0]])
        llm.understand = understood(
            "refine",
            request=request_lm(target_count=5, theme_present=False),
            instruction="",
            people=[LYNCH],
        )
        judge_calls_before = len(llm.steps("judge"))

        events = await run_turn(graph, self.chat, self.user, "David Lynch filmleri olsun")

        self.assertEqual(len(llm.steps("judge")), judge_calls_before)  # eleme atlandı
        self.assertEqual(set(film_ids_of(events)), {self.ids[5], self.ids[0], self.ids[1]})

    async def test_refine_without_people_still_rereads_the_old_films(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=5)))
        graph, _ = await self.start_with_a_mixed_draft(llm)
        llm.understand = understood(
            "refine", request=request_lm(target_count=5), instruction="Make it darker."
        )

        await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        read = set(map(int, re.findall(r'<film id="(\d+)">', llm.steps("judge")[-1].user)))
        self.assertTrue(set(self.ids[2:5]) <= read)

    async def test_the_previous_people_and_ranking_are_in_the_understanding_input(self):
        request = request_lm(target_count=3, rank_by="rating", theme_present=False)
        llm = FakeLLM(understand=understood(request=request, people=[LYNCH]))
        graph, _ = self.graph(
            llm, self.ids, people_found=[("David Lynch", 8)], people_index={"David Lynch": self.ids}
        )
        await run_turn(graph, self.chat, self.user, "David Lynch en iyi 3 filmi")
        llm.understand = understood(
            "refine", request=request_lm(target_count=3, rank_by="rating"), people=[LYNCH]
        )

        await run_turn(graph, self.chat, self.user, "daha karanlık olsun")

        user = llm.steps("parse")[-1].user
        self.assertIn('"people": [{"name": "David Lynch", "role": "director"}]', user)
        self.assertIn('"rank_by": "rating"', user)

    def test_understanding_prompt_keeps_people_and_ranking_on_refine(self):
        self.assertIn(
            "Keep the people and rank_by of <previous_request> exactly as they are unless the "
            "editor changes them",
            prompts.UNDERSTAND_SYSTEM,
        )


class AutomaticTargetTests(PersonFlowCase):
    def person_only(self, **overrides):
        return understood(request=self.person_request(**overrides), people=[LYNCH])

    async def more_films(self, count: int) -> list[int]:
        extra = [await sync_to_async(make_story_film)(n) for n in range(9, 9 + count)]
        return self.ids + [film.pk for film in extra]

    async def test_unstated_number_takes_every_film_of_the_person(self):
        ids = await self.more_films(4)  # 12 film
        llm = FakeLLM(understand=self.person_only())
        graph, _ = self.graph(llm, ids, people_found=[("David Lynch", 12)])

        events = await run_turn(graph, self.chat, self.user, "David Lynch filmleri")

        self.assertEqual(len(film_ids_of(events)), 12)
        self.assertIn("target_count: 12", llm.steps("select")[0].user)
        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn("The archive has 12 film(s) for David Lynch.", notes)
        self.assertIn("All 12 films of the archive for this request are in the collection.", notes)
        collection = await Collection.objects.filter(chat=self.chat).afirst()
        self.assertFalse(collection.request["target_stated"])

    async def test_the_target_is_capped_at_twenty_and_the_note_says_so(self):
        ids = await self.more_films(17)  # 25 film
        llm = FakeLLM(understand=self.person_only())
        graph, _ = self.graph(llm, ids, people_found=[("David Lynch", 25)])

        events = await run_turn(graph, self.chat, self.user, "David Lynch filmleri")

        self.assertEqual(len(film_ids_of(events)), 20)
        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn("The archive has 25 film(s) for David Lynch.", notes)
        self.assertIn("Only the first 20 of the 25 films are in the collection.", notes)

    async def test_a_stated_number_is_left_alone(self):
        ids = await self.more_films(4)
        llm = FakeLLM(understand=self.person_only(target_count=3))
        graph, _ = self.graph(llm, ids, people_found=[("David Lynch", 12)])

        events = await run_turn(graph, self.chat, self.user, "David Lynch'in 3 filmi")

        self.assertEqual(len(film_ids_of(events)), 3)
        notes = notes_of(llm.steps("respond")[-1])
        self.assertNotIn("All 12", notes)

    async def test_a_themed_person_request_keeps_the_default_ten(self):
        ids = await self.more_films(4)
        llm = FakeLLM(understand=self.person_only(theme_present=True))
        graph, _ = self.graph(llm, ids, people_found=[("David Lynch", 12)])

        events = await run_turn(graph, self.chat, self.user, "David Lynch'in karanlık filmleri")

        self.assertEqual(len(film_ids_of(events)), 10)

    async def test_a_request_without_people_keeps_the_default_ten(self):
        ids = await self.more_films(4)
        llm = FakeLLM(understand=understood(request=request_lm(target_count=None)))
        graph, _ = self.graph(llm, ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(len(film_ids_of(events)), 10)

    def test_universe_note_only_states_facts_it_can_back(self):
        self.assertEqual(
            texts.universe_note(12, 12),
            "All 12 films of the archive for this request are in the collection.",
        )
        self.assertEqual(
            texts.universe_note(20, 31), "Only the first 20 of the 31 films are in the collection."
        )
        self.assertIsNone(texts.universe_note(10, 12))  # kaynak doğrulaması film düşürdü
        self.assertIsNone(texts.universe_note(18, 31))


class NotesAreFactsOnlyTests(PersonFlowCase):
    def assert_no_directive(self, notes: str):
        lowered = notes.lower()
        for word in DIRECTIVE_WORDS:
            self.assertNotIn(word, lowered, notes)

    async def test_unstated_number_turn_sends_no_directive_or_comparison_notes(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=None)))
        graph, _ = self.graph(llm, self.ids)

        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn("Films in the saved collection: 8.", notes)
        self.assert_no_directive(notes)

    async def test_unstated_person_only_turn_sends_no_directive_or_comparison_notes(self):
        request = self.person_request()
        llm = FakeLLM(understand=understood(request=request, people=[LYNCH]))
        graph, _ = self.graph(llm, self.ids, people_found=[("David Lynch", 8)])

        await run_turn(graph, self.chat, self.user, "David Lynch filmleri")

        self.assert_no_directive(notes_of(llm.steps("respond")[-1]))

    def test_the_respond_prompt_does_not_talk_about_whether_a_number_was_stated(self):
        self.assertNotIn("stated a number", prompts.RESPOND_SYSTEM)
        self.assertNotIn("did the editor state", prompts.RESPOND_SYSTEM)


class ExistenceQuestionTests(PersonFlowCase):
    async def test_a_question_with_an_open_draft_gets_the_archive_fact_and_makes_no_draft(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=3)))
        graph, retrieval_double = self.graph(llm, self.ids, people_index={"Zeki Demirkubuz": []})
        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        llm.understand = understood(
            "question", people=[PersonLM(name="Zeki Demirkubuz", role="any")]
        )

        events = await run_turn(
            graph, self.chat, self.user, "veritabanımızda zeki demirkubuz filmi var mı"
        )

        self.assertEqual(data_of(events, "collection"), [])
        self.assertEqual(await Collection.objects.filter(chat=self.chat).acount(), 1)
        self.assertEqual(len(retrieval_double.calls), 1)  # ikinci tur arama yapmadı
        answer = llm.steps("answer")[-1].user
        self.assertIn("<archive>", answer)
        self.assertIn("Zeki Demirkubuz: no film in the archive is listed under this name.", answer)
        self.assertIn("<draft>", answer)

    def test_understanding_prompt_sends_existence_questions_to_the_question_intent(self):
        text = prompts.UNDERSTAND_SYSTEM

        self.assertIn("asks what the archive holds for a person or film", text)
        self.assertIn("is there a Zeki Demirkubuz film in the database?", text)
        self.assertIn("such a question is question, never new_search", text)


class PersonUniverseReadingTests(PersonFlowCase):
    def small_read_limit(self):
        return override_settings(AGENT={**settings.AGENT, "judge_limit": 3})

    async def test_with_a_person_and_a_theme_the_whole_universe_is_read(self):
        request = self.person_request(theme_present=True, target_count=2)
        llm = FakeLLM(understand=understood(request=request, people=[LYNCH]))
        with self.small_read_limit():
            graph, _ = self.graph(llm, self.ids[:6], people_found=[("David Lynch", 6)])
            await run_turn(graph, self.chat, self.user, "David Lynch'in karanlık filmleri")

        read = list(map(int, re.findall(r'<film id="(\d+)">', llm.steps("judge")[0].user)))
        self.assertEqual(read, self.ids[:6])  # sınır 3 olsa da kişi evreninin tamamı

    async def test_without_a_person_the_read_limit_stays(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=2)))
        with self.small_read_limit():
            graph, _ = self.graph(llm, self.ids[:6])
            await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        read = list(map(int, re.findall(r'<film id="(\d+)">', llm.steps("judge")[0].user)))
        self.assertEqual(read, self.ids[:3])


class PersonFilterNoticeTests(PersonFlowCase):
    async def test_a_filter_that_left_no_film_of_the_person_is_explained_as_such(self):
        request = self.person_request()
        llm = FakeLLM(understand=understood(request=request, people=[LYNCH]))
        graph, _ = self.graph(llm, (self.ids, ("year_min",)), people_found=[("David Lynch", 8)])

        events = await run_turn(graph, self.chat, self.user, "2030 sonrası David Lynch filmleri")

        notice = data_of(events, "notice")[0]["text"]
        self.assertIn("hiç filmi kalmadığı için", notice)
        self.assertIn("filtreyi uygulamadım", notice)
        self.assertNotIn("çok az film", notice)

    async def test_without_a_person_the_old_notice_is_unchanged(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, (self.ids, ("year_min",)))

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertIn("çok az film kaldığı için", data_of(events, "notice")[0]["text"])

    def test_people_filter_notice_texts(self):
        self.assertIsNone(texts.people_filter_notice(()))
        self.assertEqual(
            texts.people_filter_notice(("year_min", "year_max", "countries")),
            "Aradığın kişinin bu yıl, ülke filtresiyle hiç filmi kalmadığı için filtreyi "
            "uygulamadım; sonuçlar bu ölçüte uymayabilir.",
        )
