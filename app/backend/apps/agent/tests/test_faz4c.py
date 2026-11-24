"""Faz 4c: gerekçe/başlık dili kodla denetlenir, sayı olguları kodla verilir, düzeltme turunda
modelin kopyaladığı sayı "söylendi" sayılmaz, cevap istemi İngilizce arayüz sözcüğü yasaklar."""

from dataclasses import dataclass, field

from django.test import SimpleTestCase, TestCase

from apps.agent import prompts
from apps.agent.schemas import (
    FilmWriting,
    ParsedRequest,
    SelectOutput,
    WriteOutput,
    sanitize_request,
)
from apps.agent.services import language
from apps.agent.services.verification import verify_writings
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
from apps.curation.models import Collection, CollectionFilm
from apps.curation.tests.base import PLOT_QUOTE, make_chat, make_story_film, make_user

INDONESIAN = (
    "Film ini sesuai dengan permintaan karena berlatar luar angkasa dan berpusat pada seorang "
    "ilmuwan yang terisolasi sendirian di pangkalan Arktik setelah bencana global."
)


class LooksTurkishTests(SimpleTestCase):
    def test_turkish_texts_pass(self):
        for text in (
            "Film, karlı bir kasabada geçen ağır tempolu bir polisiye olduğu için seçildi.",
            "Bu film bir kasaba ve cinayet üzerine kurulu.",  # ğ/ı/ş yok; işlev sözcükleri var
            "Yönetmen, suçu çözmeye çalışan bir dedektifi anlatıyor.",
            "KARANLIK BİR HİKÂYE ANLATIYOR.",
        ):
            with self.subTest(text=text):
                self.assertTrue(language.looks_turkish(text))

    def test_turkish_with_film_names_and_english_quotes_passes(self):
        text = (
            "“The Ice Forest” adlı yapım, kutup üssünde yalnız kalan bir bilim insanını anlatıyor; "
            "alıntıda “He was alone in the Arctic base.” cümlesi geçiyor."
        )

        self.assertTrue(language.looks_turkish(text))

    def test_other_languages_are_rejected(self):
        samples = {
            "ingilizce": "This film fits the request because it is set in a snowy small town.",
            "endonezce": INDONESIAN,
            "ispanyolca": "La película encaja con la petición porque transcurre en un pueblo "
            "nevado y está dirigida por un cineasta muy conocido.",
            "almanca": "Der Film passt zur Anfrage, weil er in einer verschneiten Stadt spielt "
            "und über Schuld und Rache handelt.",
            "fransizca": "Le film correspond à la demande parce qu'il se déroule dans une "
            "petite ville française enneigée.",
        }
        for name, text in samples.items():
            with self.subTest(name):
                self.assertFalse(language.looks_turkish(text))

    def test_known_limits_are_documented_by_name(self):
        # Kaçırma: Türkçe film adı geçen yabancı dil metni ğ/ı/ş yüzünden geçer.
        self.assertTrue(language.looks_turkish("Film ini sesuai dengan permintaan: Kış Uykusu."))
        # Yanlış alarm: ğ/ı/ş içermeyen, işlev sözcüğü olmayan 4+ sözcüklü Türkçe metin kalır.
        self.assertFalse(language.looks_turkish("Sessiz gece boyunca kasaba."))

    def test_texts_shorter_than_four_words_are_not_judged(self):
        for text in ("", "Gerekçe.", "Sessiz Gece", "Snowy town crime"):
            with self.subTest(text=text):
                self.assertTrue(language.looks_turkish(text))

    def test_long_foreign_title_is_rejected_but_turkish_title_passes(self):
        self.assertTrue(language.looks_turkish("Karlı kasabalarda cinayet"))
        self.assertFalse(language.looks_turkish("Slow crime stories in snowy small towns"))


def writing(film_id, rationale, quote=PLOT_QUOTE):
    return FilmWriting(film_id=film_id, rationale=rationale, source_kind="plot", source_quote=quote)


class VerifyWritingLanguageTests(TestCase):
    def test_non_turkish_rationale_is_a_problem_with_a_clear_reason(self):
        film = make_story_film(1)

        verified, problems = verify_writings(
            [writing(film.pk, INDONESIAN)], {film.pk}, {film.pk: film}
        )

        self.assertEqual(verified, {})
        self.assertIn("must be written in Turkish", problems[film.pk])

    def test_turkish_rationale_passes(self):
        film = make_story_film(1)

        verified, problems = verify_writings(
            [writing(film.pk, "Kasvetli bir kış polisiyesi olduğu için seçildi.")],
            {film.pk},
            {film.pk: film},
        )

        self.assertEqual(problems, {})
        self.assertIn(film.pk, verified)


@dataclass
class WrongLanguageLLM(FakeLLM):
    """`wrong_first`: ilk yazımda Endonezce gerekçe yazan filmler; `wrong_always`: hep."""

    wrong_first: set = field(default_factory=set)
    wrong_always: set = field(default_factory=set)
    english_texts: bool = False

    def _write(self, user):
        out = super()._write(user)
        repairing = "<problems>" in user
        films = []
        for item in out.films:
            if item.film_id in self.wrong_always or (
                item.film_id in self.wrong_first and not repairing
            ):
                item = item.model_copy(update={"rationale": INDONESIAN})
            films.append(item)
        return WriteOutput(films=films)

    def _select(self, user):
        out = super()._select(user)
        if not self.english_texts:
            return out
        return SelectOutput(
            selected_ids=out.selected_ids,
            title="Slow crime stories in snowy small towns",
            description="Slow northern crime films tied together by cold landscapes.",
            suggestions=out.suggestions,
        )


class FlowBase(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.chat = make_chat(self.user)
        self.films = [make_story_film(n) for n in range(1, 9)]
        self.ids = [film.pk for film in self.films]

    def graph(self, llm, *results):
        return make_graph(llm, FakeRetrieval(*results))

    async def latest(self):
        return await Collection.objects.filter(chat=self.chat).order_by("-id").afirst()


class RationaleLanguageFlowTests(FlowBase):
    async def test_wrong_language_rationale_goes_through_the_one_repair_call(self):
        llm = WrongLanguageLLM(wrong_first={self.ids[0]})
        graph = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        repairs = [call for call in llm.steps("write") if "<problems>" in call.user]
        self.assertEqual(len(repairs), 1)
        self.assertIn("must be written in Turkish", repairs[0].user)
        films = data_of(events, "collection")[0]["films"]
        self.assertEqual(len(films), 5)
        self.assertTrue(all("ini sesuai" not in film["rationale"] for film in films))

    async def test_rationale_still_wrong_after_repair_drops_the_film_and_says_so(self):
        llm = WrongLanguageLLM(wrong_always={self.ids[0]})
        graph = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        films = data_of(events, "collection")[0]["films"]
        self.assertNotIn(self.ids[0], [film["film_id"] for film in films])
        self.assertEqual(len(films), 4)
        self.assertIn("1 film(s) were left out", notes_of(llm.steps("respond")[-1]))
        saved = [row.rationale async for row in CollectionFilm.objects.all()]
        self.assertTrue(all("ini sesuai" not in text for text in saved))

    async def test_replace_turn_moves_to_the_next_candidate_when_the_language_is_wrong(self):
        llm = WrongLanguageLLM()
        graph = self.graph(llm, self.ids)
        first = data_of(
            await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film"), "collection"
        )[0]
        first_ids = [film["film_id"] for film in first["films"]]
        remaining = [fid for fid in self.ids if fid not in first_ids]
        llm.wrong_always = {remaining[0]}

        events = await run_turn(
            graph,
            self.chat,
            self.user,
            "Bunun yerine başkasını bul",
            action={"type": "replace_film", "film_id": first_ids[1]},
        )

        new_ids = [film["film_id"] for film in data_of(events, "collection")[0]["films"]]
        self.assertEqual(new_ids[1], remaining[1])  # ilk aday Endonezce, ikinci aday girdi
        self.assertNotIn(remaining[0], new_ids)

    async def test_non_turkish_title_and_description_fall_back_to_safe_defaults(self):
        llm = WrongLanguageLLM(english_texts=True)
        graph = self.graph(llm, self.ids)

        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        collection = await self.latest()
        self.assertEqual(collection.title, "Finlandiya")  # istek özeti (gerçek filtrelerden)
        self.assertEqual(collection.description, "")


class CountFactsFlowTests(FlowBase):
    async def respond_notes(self, target, fit_count):
        llm = FakeLLM(
            understand=understood(request=request_lm(target_count=target)),
            fit_ids=set(self.ids[:fit_count]),
        )
        graph = self.graph(llm, self.ids)
        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        return notes_of(llm.steps("respond")[-1])

    async def test_requested_eight_and_eight_saved_is_reported_as_met(self):
        notes = await self.respond_notes(8, 8)

        self.assertIn("Requested number of films: 8. Films in the saved collection: 8.", notes)
        self.assertIn("fully met", notes)
        for forbidden in ("fewer", "Missing:", "Only"):
            self.assertNotIn(forbidden, notes)

    async def test_requested_eight_and_six_saved_is_two_short(self):
        notes = await self.respond_notes(8, 6)

        self.assertIn("Films in the saved collection: 6", notes)
        self.assertIn("Missing: 2", notes)

    async def test_unstated_number_gets_the_count_only_without_any_comparison(self):
        notes = await self.respond_notes(None, 7)

        self.assertIn("Films in the saved collection: 7.", notes)
        for forbidden in ("Requested", "Missing", "met", "requested"):
            self.assertNotIn(forbidden, notes)

    async def test_count_comes_from_the_saved_collection_not_from_the_selection(self):
        llm = WrongLanguageLLM(
            understand=understood(request=request_lm(target_count=8)), wrong_always={self.ids[0]}
        )
        graph = self.graph(llm, self.ids)

        await run_turn(graph, self.chat, self.user, "8 film istiyorum")

        notes = notes_of(llm.steps("respond")[-1])
        self.assertIn("Films in the saved collection: 7", notes)  # bir film dilden düştü
        self.assertIn("Missing: 1", notes)


class CopiedCountTests(SimpleTestCase):
    def previous(self, count, stated):
        return ParsedRequest(en_query="x", hyde="y", target_count=count, target_stated=stated)

    def test_a_number_equal_to_the_previous_one_inherits_the_previous_flag(self):
        raw = request_lm(target_count=10)

        request = sanitize_request(
            raw, fallback_target=10, fallback_stated=False, previous=self.previous(10, False)
        )

        self.assertEqual((request.target_count, request.target_stated), (10, False))

    def test_a_different_number_is_newly_stated(self):
        request = sanitize_request(
            request_lm(target_count=12),
            fallback_target=10,
            fallback_stated=False,
            previous=self.previous(10, False),
        )

        self.assertEqual((request.target_count, request.target_stated), (12, True))

    def test_an_equal_number_after_a_stated_one_stays_stated(self):
        request = sanitize_request(
            request_lm(target_count=8),
            fallback_target=8,
            fallback_stated=True,
            previous=self.previous(8, True),
        )

        self.assertEqual((request.target_count, request.target_stated), (8, True))

    def test_known_limit_editor_repeating_the_unstated_default_number_stays_unstated(self):
        # Editör önceki (söylenmemiş, 10) sayıyla aynı sayıyı gerçekten söylese de kopyadan
        # ayırt edilemez; bayrak False kalır. Kabul edilen sınır: yalnız metni etkiler.
        request = sanitize_request(
            request_lm(target_count=10),
            fallback_target=10,
            fallback_stated=False,
            previous=self.previous(10, False),
        )

        self.assertFalse(request.target_stated)

    def test_without_a_previous_request_any_number_is_stated(self):
        request = sanitize_request(request_lm(target_count=10))

        self.assertEqual((request.target_count, request.target_stated), (10, True))


class CopiedCountFlowTests(FlowBase):
    async def stored(self):
        collection = await self.latest()
        return collection.request["target_count"], collection.request["target_stated"]

    async def test_refine_copying_an_unstated_default_keeps_the_flag_false(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=None)))
        graph = self.graph(llm, self.ids)
        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        self.assertEqual(await self.stored(), (10, False))
        llm.understand = understood("refine", request=request_lm(target_count=10))

        await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        self.assertEqual(await self.stored(), (10, False))
        self.assertNotIn("Requested number", notes_of(llm.steps("respond")[-1]))

    async def test_refine_with_a_new_number_becomes_stated(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=None)))
        graph = self.graph(llm, self.ids)
        await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        llm.understand = understood("refine", request=request_lm(target_count=7))

        await run_turn(graph, self.chat, self.user, "7 film olsun")

        self.assertEqual(await self.stored(), (7, True))

    async def test_refine_after_approval_copying_the_default_does_not_become_stated(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=None)))
        graph = self.graph(llm, self.ids)
        first = data_of(
            await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film"), "collection"
        )[0]
        await Collection.objects.filter(pk=first["id"]).aupdate(status="approved")
        llm.understand = understood("refine", request=request_lm(target_count=10))

        await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        self.assertEqual(await Collection.objects.acount(), 2)  # yeni taslak
        self.assertEqual(await self.stored(), (10, False))


class ReplyWordingRuleTests(SimpleTestCase):
    def test_chat_rules_ban_english_interface_words_and_tag_names(self):
        rules = prompts.CHAT_RULES

        self.assertIn('"taslak", "seçki", "koleksiyon"', rules)
        self.assertIn("For interface terms use the Turkish words", rules)

    def test_respond_prompt_never_comments_on_whether_a_number_was_stated(self):
        # Faz 1 düzeltme: kural, sızdıran "sayıyı söylemişti mi" cümlesi olmadan konur.
        self.assertIn("The facts decide what is said about counts", prompts.RESPOND_SYSTEM)
        self.assertNotIn("stated a number", prompts.RESPOND_SYSTEM)
        self.assertNotIn("did not state a number", prompts.RESPOND_SYSTEM)
