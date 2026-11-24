"""Bug grubu B: `keep_draft` ile mevcut filmleri koruyup üstüne ekleme, boş istek + dolu
`instruction` için anlama adımının bir kez yeniden sorulması, "kara film" terim notu."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.agent import prompts
from apps.agent.graph import Deps, Nodes
from apps.agent.schemas import FiltersLM, ParsedRequest, RequestFilters
from apps.agent.services.llm import MSG_BAD_OUTPUT, LLMError
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
from apps.agent.tests.test_faz2c_duzeltme import FlowCase
from apps.curation.models import Collection

KOREA = FiltersLM(year_min=None, year_max=None, countries=["South Korea"], max_vote_count=None)


def base_request(**overrides) -> ParsedRequest:
    fields = {
        "en_query": "slow crime stories set in snowy small towns",
        "hyde": "A detective investigates a disappearance in a snowbound town.",
        "filters": RequestFilters(countries=["Finland"]),
        "target_count": 6,
    }
    fields.update(overrides)
    return ParsedRequest(**fields)


def draft_context(count=6, status="draft"):
    return SimpleNamespace(
        draft_films=[(n, f"Film {n}", 2000) for n in range(1, count + 1)],
        draft_status=status,
        draft_model_names=(),
        draft_id=1,
        draft_title="Karlı kasabalar",
        history=[],
    )


def nodes(llm=None) -> Nodes:
    return Nodes(Deps(llm=llm, retrieval=None))


class KeepDraftNormalizeTests(SimpleTestCase):
    def normalize(self, out, text, count=6):
        return nodes()._normalize(out, draft_context(count), base_request(), text)

    def test_keep_draft_with_the_same_criteria_continues_the_previous_request(self):
        # Model sorgu cümlesini yeniden yazsa da ölçütler aynıysa önceki istek aynen sürer.
        out = understood(
            "refine",
            request=request_lm(
                target_count=8,
                filters=FiltersLM(
                    year_min=None, year_max=None, countries=["Finland"], max_vote_count=None
                ),
                en_query="finnish crime films in the snow",
            ),
            keep_draft=True,
        )

        result = self.normalize(out, "toplam 8 film olsun")

        self.assertTrue(result.add_only)
        self.assertEqual(result.exclude_ids, (1, 2, 3, 4, 5, 6))
        self.assertEqual(result.delta, 2)
        self.assertEqual(result.draft_count, 6)
        self.assertEqual(result.request.en_query, base_request().en_query)
        self.assertEqual(result.request.filters.countries, ["Finland"])
        self.assertEqual(result.request.target_count, 8)

    def test_keep_draft_with_a_changed_criterion_and_no_instruction_adds_with_the_new_request(self):
        # Gerçek modelde görülen durum (2026-11-18): ülke değişti ama `instruction` boş kaldı.
        out = understood(
            "refine",
            request=request_lm(
                target_count=None, target_delta=3, filters=KOREA, en_query="korean thrillers"
            ),
            keep_draft=True,
        )

        result = self.normalize(out, "3 tane daha ekle ama bu sefer Güney Kore olsun")

        self.assertTrue(result.add_only)
        self.assertEqual(result.exclude_ids, (1, 2, 3, 4, 5, 6))
        self.assertEqual(result.delta, 3)
        self.assertEqual(result.request.en_query, "korean thrillers")
        self.assertEqual(result.request.filters.countries, ["South Korea"])
        self.assertEqual(result.request.target_count, 9)

    def test_keep_draft_with_an_instruction_adds_with_the_new_request(self):
        out = understood(
            "refine",
            request=request_lm(
                target_count=None, target_delta=3, filters=KOREA, en_query="korean thrillers"
            ),
            instruction="the new films should be South Korean",
            keep_draft=True,
        )

        result = self.normalize(out, "3 tane daha ekle ama bu sefer Güney Kore olsun")

        self.assertTrue(result.add_only)
        self.assertEqual(result.exclude_ids, (1, 2, 3, 4, 5, 6))
        self.assertEqual(result.delta, 3)
        self.assertEqual(result.request.en_query, "korean thrillers")
        self.assertEqual(result.request.filters.countries, ["South Korea"])
        self.assertEqual(result.request.target_count, 9)
        self.assertTrue(result.request.target_stated)
        self.assertEqual(result.instruction, "the new films should be South Korean")

    def test_without_keep_draft_a_changed_criterion_rebuilds_the_selection(self):
        out = understood(
            "refine",
            request=request_lm(target_count=8, filters=KOREA, en_query="korean thrillers"),
        )

        result = self.normalize(out, "toplam 8 film olsun")

        self.assertFalse(result.add_only)
        self.assertEqual(result.exclude_ids, ())
        self.assertEqual(result.request.en_query, "korean thrillers")

    def test_a_target_not_above_the_draft_ignores_keep_draft(self):
        for target in (6, 4):
            with self.subTest(target=target):
                out = understood(
                    "refine",
                    request=request_lm(target_count=target, filters=KOREA),
                    instruction="only South Korean",
                    keep_draft=True,
                )

                result = self.normalize(out, f"toplam {target} film olsun")

                self.assertFalse(result.add_only)
                self.assertEqual(result.exclude_ids, ())

    def test_keep_draft_without_a_target_is_ignored(self):
        out = understood(
            "refine",
            request=request_lm(target_count=None, filters=KOREA),
            instruction="only South Korean",
            keep_draft=True,
        )

        result = self.normalize(out, "bu sefer Güney Kore olsun")

        self.assertFalse(result.add_only)

    def test_a_wrong_keep_draft_does_not_break_the_plain_add_request(self):
        out = understood(
            "refine", request=request_lm(target_count=None, target_delta=2), keep_draft=False
        )

        result = self.normalize(out, "2 tane daha ekle")

        self.assertTrue(result.add_only)
        self.assertEqual(result.delta, 2)
        self.assertEqual(result.exclude_ids, (1, 2, 3, 4, 5, 6))
        self.assertEqual(result.request.target_count, 8)

    def test_keep_draft_is_ignored_when_the_draft_is_not_open(self):
        out = understood(
            "refine", request=request_lm(target_count=8), instruction="x", keep_draft=True
        )

        result = nodes()._normalize(
            out, draft_context(status="approved"), base_request(), "toplam 8 film olsun"
        )

        self.assertFalse(result.add_only)


class SequenceLLM(FakeLLM):
    """`parse` çağrıları sırayla bu cevapları verir."""

    def __init__(self, *outputs):
        super().__init__()
        self.outputs = list(outputs)
        self.understand = lambda user: self.outputs.pop(0)


class EmptyRequestReaskTests(SimpleTestCase):
    async def ask(self, llm, text="2 tane daha ekle, Güney Kore olsun"):
        return await nodes(llm)._ask_model(text, draft_context(), base_request())

    async def test_a_filled_second_answer_is_used(self):
        first = understood("refine", instruction="only South Korean")
        first.request = None
        second = understood(
            "refine",
            request=request_lm(target_count=None, target_delta=2, en_query="korean thrillers"),
            instruction="only South Korean",
        )
        llm = SequenceLLM(first, second)

        result = await self.ask(llm)

        self.assertEqual(len(llm.steps("parse")), 2)
        self.assertNotIn("complete request", llm.steps("parse")[0].user)
        self.assertIn(prompts.REASK_NOTE, llm.steps("parse")[1].user)
        self.assertEqual(result.request.en_query, "korean thrillers")
        self.assertEqual(result.instruction, "only South Korean")

    async def test_a_second_empty_answer_with_a_number_continues_with_the_previous_request(self):
        first = understood(
            "refine", request=request_lm(en_query="", target_delta=2), instruction="x"
        )
        second = understood(
            "refine", request=request_lm(en_query=" ", target_delta=2), instruction="x"
        )
        llm = SequenceLLM(first, second)

        result = await self.ask(llm)

        self.assertEqual(len(llm.steps("parse")), 2)
        self.assertEqual(result.request.en_query, base_request().en_query)
        self.assertEqual(result.delta, 2)

    async def test_a_second_empty_answer_without_a_number_is_an_error(self):
        first = understood("refine", instruction="only South Korean")
        first.request = None
        second = understood("refine", instruction="only South Korean")
        second.request = None
        llm = SequenceLLM(first, second)

        with self.assertRaises(LLMError) as ctx:
            await self.ask(llm, text="bu sefer Güney Kore olsun")

        self.assertEqual(ctx.exception.message, MSG_BAD_OUTPUT)
        self.assertEqual(len(llm.steps("parse")), 2)

    async def test_an_empty_request_with_an_empty_instruction_is_not_asked_again(self):
        first = understood("refine", request=request_lm(en_query="", target_delta=2))
        llm = SequenceLLM(first)

        result = await self.ask(llm, text="2 tane daha ekle")

        self.assertEqual(len(llm.steps("parse")), 1)
        self.assertEqual(result.request.en_query, base_request().en_query)

    async def test_a_filled_request_is_not_asked_again(self):
        first = understood("refine", instruction="only South Korean")
        llm = SequenceLLM(first)

        await self.ask(llm)

        self.assertEqual(len(llm.steps("parse")), 1)


class UnderstandPromptTests(SimpleTestCase):
    def test_kara_film_is_film_noir(self):
        text = prompts.UNDERSTAND_SYSTEM

        self.assertIn('"kara film"', text)
        self.assertIn("film noir", text)

    def test_lesser_known_is_a_vote_cap_not_the_popularity_order(self):
        text = prompts.UNDERSTAND_SYSTEM

        self.assertIn('"az bilinen" asks for the opposite of "en bilinen"', text)
        self.assertIn("leaves rank_by null", text)

    def test_yas_means_mourning(self):
        self.assertIn('"yas" (written with s) means mourning', prompts.UNDERSTAND_SYSTEM)

    def test_keep_draft_is_defined(self):
        self.assertIn("keep_draft", prompts.UNDERSTAND_SYSTEM)

    def test_a_criterion_for_the_added_films_is_written_into_the_request(self):
        self.assertIn("request describes the new films", prompts.UNDERSTAND_SYSTEM)


class QuoteSourceFlowTests(FlowCase):
    async def test_the_collection_event_carries_the_quote_source(self):
        llm = FakeLLM(understand=understood(request=request_lm(target_count=3)))
        graph = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 3 film")

        films = data_of(events, "collection")[0]["films"]
        self.assertEqual(len(films), 3)
        for film in films:
            self.assertEqual(film["quote_source"]["kind"], "plot")
            self.assertEqual(film["quote_source"]["label"], "Wikipedia · hikâye")
            self.assertEqual(film["quote_source"]["url"], film["sources"][0]["url"])


class TitledLLM(FakeLLM):
    def __init__(self, title, description, **kwargs):
        super().__init__(**kwargs)
        self.title, self.description = title, description

    def _select(self, user):
        out = super()._select(user)
        return out.model_copy(update={"title": self.title, "description": self.description})


class SelectionTitleFlowTests(FlowCase):
    async def collection_of(self, title, description):
        llm = TitledLLM(
            title, description, understand=understood(request=request_lm(target_count=3))
        )
        graph = self.graph(llm, self.ids)
        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 3 film")
        return data_of(events, "collection")[0]

    async def test_a_short_turkish_title_is_kept_when_the_description_is_turkish(self):
        # Dil denetimi kısa başlığı tek başına tanıyamıyor (2026-11-18: başlık özete düşüyordu).
        title = "70'lerin Paranoyak Siyasi Gerilimleri"

        collection = await self.collection_of(
            title, "Yetmişlerin komplo ve şüphe dolu siyasi gerilimleri bir arada."
        )

        self.assertEqual(collection["title"], title)

    async def test_an_english_title_with_an_english_description_falls_back(self):
        title = "Paranoid Political Thrillers of the Seventies"

        collection = await self.collection_of(
            title, "A selection of tense political thrillers from the seventies."
        )

        self.assertNotEqual(collection["title"], title)
        self.assertTrue(collection["title"])

    async def test_an_english_title_without_a_description_falls_back(self):
        title = "Paranoid Political Thrillers of the Seventies"

        collection = await self.collection_of(title, "")

        self.assertNotEqual(collection["title"], title)


class KeepDraftFlowTests(FlowCase):
    async def test_new_criterion_add_keeps_the_films_and_searches_with_the_new_request(self):
        llm = FakeLLM()
        retrieval = FakeRetrieval(self.ids)
        retrieval_graph = make_graph(llm, retrieval)
        first = await self.start_draft(retrieval_graph, llm, request=request_lm(target_count=5))
        first_ids = self.film_ids(first)
        llm.understand = understood(
            "refine",
            request=request_lm(
                target_count=None,
                target_delta=3,
                filters=KOREA,
                en_query="korean crime thrillers",
            ),
            instruction="the new films should be South Korean",
            keep_draft=True,
        )

        events = await run_turn(
            retrieval_graph, self.chat, self.user, "3 tane daha ekle ama bu sefer Güney Kore olsun"
        )

        second = data_of(events, "collection")[0]
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(second["films"]), 8)
        self.assertEqual(self.film_ids(second)[:5], first_ids)
        self.assertEqual(
            [f["rationale"] for f in second["films"][:5]],
            [f["rationale"] for f in first["films"]],
        )
        self.assertEqual(second["title"], first["title"])
        self.assertEqual(retrieval.calls[-1]["exclude"], tuple(first_ids))
        self.assertEqual(retrieval.calls[-1]["request"].en_query, "korean crime thrillers")
        self.assertEqual(llm.steps("write")[-1].user.count("<film id="), 3)
        self.assertIn("korean crime thrillers", llm.steps("write")[-1].user)
        self.assertEqual(len(llm.steps("select")), 1)  # yalnız ekleme: yeniden seçim yok
        saved = await Collection.objects.aget(pk=second["id"])
        self.assertEqual(saved.request["en_query"], "korean crime thrillers")
        self.assertEqual(saved.request["filters"]["countries"], ["South Korea"])
        self.assertEqual(saved.request["target_count"], 8)
        self.assertIn(
            "Films requested to add: 3. Films added: 3. Films in the saved collection now: 8.",
            notes_of(llm.steps("respond")[-1]),
        )
