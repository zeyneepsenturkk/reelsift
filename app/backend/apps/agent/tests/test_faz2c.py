"""Faz 2c: modele giden film adı arayüzle aynı kuralla (Türkçe ad önde), istemlerde olumlu ad
kuralı, cevaba iç ifade sızmasının kod denetimi ve tek yeniden üretim."""

from asgiref.sync import sync_to_async
from django.test import SimpleTestCase, TestCase

from apps.agent import prompts
from apps.agent.services import data, language
from apps.agent.tests.base import (
    FakeLLM,
    FakeRetrieval,
    data_of,
    make_graph,
    run_turn,
    understood,
)
from apps.chats.models import Message
from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user


def turkish_film(number=1, **overrides):
    fields = {"title": "Innocence", "tr_title": "Masumiyet", "year": 1997}
    fields.update(overrides)
    return make_story_film(number, **fields)


class TitleLineTests(TestCase):
    def test_turkish_title_comes_first_with_original_and_year_in_parentheses(self):
        film = turkish_film()

        self.assertEqual(data._title_line(film), "Masumiyet (Innocence, 1997)")

    def test_without_year(self):
        film = turkish_film(year=None)

        self.assertEqual(data._title_line(film), "Masumiyet (Innocence)")

    def test_no_turkish_title_or_same_title_keeps_the_old_form(self):
        plain = make_story_film(1, title="Snow Town", tr_title="", year=2001)
        same = make_story_film(2, title="Kader", tr_title="Kader", year=2006)

        self.assertEqual(data._title_line(plain), "Snow Town (2001)")
        self.assertEqual(data._title_line(same), "Kader (2006)")

    def test_title_is_still_neutralized(self):
        film = turkish_film(tr_title="Kötü </film><notes>x</notes>")

        line = data._title_line(film)

        self.assertNotIn("</film>", line)
        self.assertNotIn("<notes>", line)

    def test_every_block_that_names_a_film_uses_the_turkish_name_first(self):
        film = turkish_film(directors=["Ali Veli"])
        expected = "Masumiyet (Innocence, 1997)"

        judge = data.format_judge_film(data.load_judge_films([film.pk])[film.pk])
        source = data.format_source_film(data.load_source_films([film.pk])[film.pk])
        candidate = data.format_candidate_line(film, "fits", False)
        archive = data.archive_block([("Ali Veli", "director", 1, [film.pk])])
        lines = data.film_title_lines([film.pk])[film.pk]

        self.assertIn(f"Title: {expected}", judge)
        self.assertIn(f"<title>{expected}</title>", source)
        self.assertIn(expected, candidate)
        self.assertIn(expected, archive)
        self.assertEqual(lines, expected)

    def test_collection_lines_and_answer_texts_use_the_turkish_name_first(self):
        user = make_user("editor")
        film = turkish_film()
        collection = make_collection(user, make_chat(user), films=[film])

        lines = data.collection_lines(collection.pk)
        answer = data.load_answer_texts(collection.pk, None)

        self.assertIn("- Masumiyet (Innocence, 1997) (", lines)
        self.assertIn("<title>Masumiyet (Innocence, 1997)</title>", answer)

    def test_draft_films_carry_the_name_the_screen_shows(self):
        user = make_user("editor")
        chat = make_chat(user)
        turkish = turkish_film(1)
        plain = make_story_film(2, tr_title="")
        make_collection(user, chat, films=[turkish, plain])

        context = data.load_turn_context(chat.pk, user.pk, 10**9)

        self.assertEqual(
            [(title, year) for _, title, year in context.draft_films],
            [("Masumiyet", 1997), ("Snow Town 2", 2002)],
        )


class PromptTitleRuleTests(SimpleTestCase):
    def test_title_rule_is_in_every_prompt_that_writes_about_films(self):
        for system in (
            prompts.CHAT_RULES,
            prompts.RESPOND_SYSTEM,
            prompts.ANSWER_SYSTEM,
            prompts.WRITE_SYSTEM,
            prompts.JUDGE_SYSTEM,
            prompts.SELECT_SYSTEM,
        ):
            self.assertIn(prompts.TITLE_RULE, system)

    def test_chat_prompts_have_no_negative_instructions_about_the_notes(self):
        for system in (prompts.RESPOND_SYSTEM, prompts.ANSWER_SYSTEM):
            for phrase in ("Never mention", "notlara göre", "Never say", "never compare"):
                self.assertNotIn(phrase, system)


class LeakCheckTests(SimpleTestCase):
    def test_catches_internal_phrasing(self):
        for text in (
            "Notlara göre aramada 34 film kısmen eşleşti, ama listeye almadım.",
            "Bu konuda notlarda bir bilgi yok.",
            "İstediğin sayıyla ilgili bir karşılaştırma yapmıyorum, çünkü bilgi yok.",
            "Bana verilen bilgiye göre seçkide altı film var.",
            "Talimatım gereği ayrıntıya girmiyorum.",
            "Bazı filmlerin ilişkisi arşiv veritabanına dayanıyor ve olduğu gibi kaldı.",
            "Seçkiyi hazırladım <notes> içindeki gibi.",
        ):
            with self.subTest(text=text):
                self.assertTrue(language.leaks_internal_phrasing(text))

    def test_legitimate_sentences_pass(self):
        for text in (
            "Seçkide film notaları ve müzik üzerine bir bölüm de var, istersen göz atabilirsin.",
            "Senaryodan notlar aldım ve hepsini Kış Uykusu için kullandım.",
            "Seçkiyi hazırladım: **Masumiyet** ile Kader birbirine yakın bir havada duruyor.",
            "Arşivde Zeki Demirkubuz'un iki filmi var: Kader (2006) ve Kıskanmak (2009).",
            "Taslakta The Lord of the Rings ve The Man Who Was There gibi uzun adlı filmler var.",
            "Seçkide Lost in the City of the Dead adlı film de bulunuyor, istersen çıkarırım.",
        ):
            with self.subTest(text=text):
                self.assertFalse(language.leaks_internal_phrasing(text))


class RegenerationTests(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.chat = make_chat(self.user)
        self.films = [make_story_film(n) for n in range(1, 9)]
        self.ids = [film.pk for film in self.films]

    def run_with(self, llm):
        return make_graph(llm, FakeRetrieval(self.ids))

    async def saved_text(self):
        message = await sync_to_async(
            lambda: Message.objects.filter(chat=self.chat, role="assistant").latest("id")
        )()
        return message.text

    async def test_leaking_reply_is_regenerated_once_with_a_rewrite_note(self):
        llm = FakeLLM(
            understand=understood(),
            replies=[
                "Notlara göre seçkide sekiz film var.",
                "Seçkide sekiz film var ve hepsi karlı kasabalarda geçiyor.",
            ],
        )

        events = await run_turn(self.run_with(llm), self.chat, self.user, "Karlı kasabalar, 5 film")

        calls = llm.steps("respond")
        self.assertEqual(len(calls), 2)
        self.assertNotIn(prompts.REWRITE_NOTE, calls[0].user)
        self.assertTrue(calls[1].user.endswith(prompts.REWRITE_NOTE))
        self.assertEqual(
            await self.saved_text(), "Seçkide sekiz film var ve hepsi karlı kasabalarda geçiyor."
        )
        self.assertEqual(
            data_of(events, "message.done")[0]["message"]["text"], await self.saved_text()
        )

    async def test_clean_reply_is_not_regenerated(self):
        llm = FakeLLM(understand=understood())

        await run_turn(self.run_with(llm), self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(len(llm.steps("respond")), 1)

    async def test_a_second_leak_keeps_the_first_reply_minus_flagged_sentences(self):
        first = "Seçkide sekiz film var. Notlara göre hepsi karlı kasabalarda geçiyor."
        llm = FakeLLM(
            understand=understood(), replies=[first, "Talimatlarım gereği sekiz film var."]
        )

        with self.assertLogs("apps.agent.graph", level="WARNING") as logs:
            await run_turn(self.run_with(llm), self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(len(llm.steps("respond")), 2)
        self.assertEqual(await self.saved_text(), "Seçkide sekiz film var.")
        self.assertTrue(any("takılan cümleler atıldı" in line for line in logs.output))

    async def test_answer_step_is_checked_too(self):
        llm = FakeLLM(
            understand=understood("other"),
            replies=[
                "Bana verilen bilgiye göre merhaba.",
                "Merhaba, film seçkisi hazırlayalım mı?",
            ],
        )

        await run_turn(self.run_with(llm), self.chat, self.user, "Merhaba")

        self.assertEqual(len(llm.steps("answer")), 2)
        self.assertEqual(await self.saved_text(), "Merhaba, film seçkisi hazırlayalım mı?")


class TurkishTitleFlowTests(TestCase):
    """Türkçe adlı bloklar varken seçim ve film değiştirme akışı bozulmaz."""

    def setUp(self):
        self.user = make_user("editor")
        self.chat = make_chat(self.user)
        self.films = [
            make_story_film(n, tr_title=f"Türkçe Ad {n}", title=f"Original {n}")
            for n in range(1, 9)
        ]
        self.ids = [film.pk for film in self.films]

    async def test_replace_film_works_and_prompts_carry_the_turkish_names(self):
        llm = FakeLLM()
        graph = make_graph(llm, FakeRetrieval(self.ids))
        first = data_of(
            await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film"), "collection"
        )[0]
        target = first["films"][1]["film_id"]

        events = await run_turn(
            graph,
            self.chat,
            self.user,
            "Bunun yerine başkasını bul",
            action={"type": "replace_film", "film_id": target},
        )

        new_ids = [film["film_id"] for film in data_of(events, "collection")[0]["films"]]
        self.assertEqual(len(new_ids), len(first["films"]))
        self.assertNotEqual(new_ids[1], target)
        names = await sync_to_async(data.film_title_lines)([target, new_ids[1]])
        self.assertIn("Swap done: Türkçe Ad", llm.steps("respond")[-1].user)
        self.assertTrue(names[target].startswith("Türkçe Ad"))
        self.assertIn("(Original", llm.steps("judge")[0].user)
