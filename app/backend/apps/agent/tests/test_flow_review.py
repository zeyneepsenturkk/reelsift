"""İnceleme düzeltmeleri: deneme birikimi, film değiştirme doğrulaması, asıl istek, hata kodları."""

from apps.agent.graph import REPLACE_FAILED_TEXT
from apps.agent.schemas import FiltersLM
from apps.agent.streaming import STREAM_ERROR_CODES
from apps.agent.tests.base import (
    FakeLLM,
    FakeRetrieval,
    data_of,
    make_graph,
    request_lm,
    run_turn,
    understood,
)
from apps.agent.tests.test_flow import FlowTestCase
from apps.chats.models import Message
from apps.core.exceptions import ServiceError
from apps.curation.models import Collection, CollectionFilm


class RetryKeepsEarlierFitsTests(FlowTestCase):
    async def test_fit_film_from_first_search_stays_when_later_searches_find_nothing(self):
        llm = FakeLLM(fit_ids=set(self.ids[:3]))
        graph, retrieval = self.graph(llm, self.ids[:3], self.ids[3:6], [])

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        self.assertEqual(len(retrieval.calls), 3)
        films = data_of(events, "collection")[0]["films"]
        self.assertEqual([film["film_id"] for film in films], self.ids[:3])

    async def test_selection_order_follows_search_order_earlier_attempts_first(self):
        fit = {self.ids[0], self.ids[1], self.ids[5], self.ids[6], self.ids[7]}
        llm = FakeLLM(fit_ids=fit)
        graph, _ = self.graph(
            llm, self.ids[:4], [self.ids[5], self.ids[0], self.ids[6]], self.ids[5:]
        )

        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")

        films = [film["film_id"] for film in data_of(events, "collection")[0]["films"]]
        self.assertEqual(films, [self.ids[0], self.ids[1], self.ids[5], self.ids[6], self.ids[7]])
        self.assertEqual(len(films), len(set(films)))  # aynı film iki kez girmez


class ReplaceFilmVerificationTests(FlowTestCase):
    async def draft(self, llm):
        graph, retrieval = self.graph(llm, self.ids)
        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        return graph, data_of(events, "collection")[0]

    async def replace(self, graph, target):
        return await run_turn(
            graph,
            self.chat,
            self.user,
            "Bunun yerine başkasını bul",
            action={"type": "replace_film", "film_id": target},
        )

    async def rows(self, collection_id):
        return [
            (row.film_id, row.rationale, row.position)
            async for row in CollectionFilm.objects.filter(collection_id=collection_id).order_by(
                "position"
            )
        ]

    async def test_second_candidate_is_used_when_the_first_cannot_be_verified(self):
        llm = FakeLLM()
        graph, first = await self.draft(llm)
        first_ids = [film["film_id"] for film in first["films"]]
        remaining = [fid for fid in self.ids if fid not in first_ids]
        llm.bad_quote_ids = {remaining[0]}
        writes_before = len(llm.steps("write"))

        events = await self.replace(graph, first_ids[1])

        updated = data_of(events, "collection")[0]
        new_ids = [film["film_id"] for film in updated["films"]]
        self.assertEqual(new_ids[0], first_ids[0])
        self.assertEqual(new_ids[1], remaining[1])  # ikinci aday hedefin yerine girdi
        self.assertNotIn(remaining[0], new_ids)
        self.assertNotIn(first_ids[1], new_ids)
        self.assertEqual(new_ids[2:], first_ids[2:])
        self.assertEqual(len(llm.steps("write")) - writes_before, 2)  # ilk aday + ikinci aday
        self.assertEqual(updated["version"], 2)
        step = data_of(events, "step.done")[-1]
        self.assertEqual(step["title"], "Seçkiyi güncelledim.")
        self.assertIn("1 aday, alıntısı doğrulanamadığı için elendi", step["detail"])

    async def test_target_stays_and_draft_is_unchanged_when_no_candidate_verifies(self):
        llm = FakeLLM()
        graph, first = await self.draft(llm)
        first_ids = [film["film_id"] for film in first["films"]]
        remaining = [fid for fid in self.ids if fid not in first_ids]
        llm.bad_quote_ids = set(remaining)
        before = await self.rows(first["id"])
        writes_before = len(llm.steps("write"))
        responds_before = len(llm.steps("respond"))

        events = await self.replace(graph, first_ids[1])

        self.assertEqual(len(data_of(events, "collection")), 0)
        collection = await Collection.objects.aget(pk=first["id"])
        self.assertEqual(collection.version, 1)  # sürüm artmadı
        self.assertEqual(await self.rows(first["id"]), before)
        self.assertEqual(len(llm.steps("write")) - writes_before, 3)  # en çok 3 aday
        step = data_of(events, "step.done")[-1]
        self.assertEqual(step["title"], "Seçkiyi güncelleyemedim.")
        self.assertIn("seçki aynı kaldı", step["detail"])
        text = "".join(data["delta"] for data in data_of(events, "text.delta")).strip()
        self.assertEqual(text, REPLACE_FAILED_TEXT)
        done = data_of(events, "message.done")[0]["message"]
        self.assertIsNone(done["collection_id"])
        self.assertEqual(len(llm.steps("respond")), responds_before)  # cevap kodla yazıldı


class OriginalRequestIsKeptTests(FlowTestCase):
    async def test_relaxation_applies_to_the_turn_only_and_next_turn_starts_from_original(self):
        request = request_lm(
            filters=FiltersLM(year_min=None, year_max=None, countries=[], max_vote_count=2000)
        )
        llm = FakeLLM(understand=understood(request=request), fit_ids=set(self.ids[3:]))
        graph, retrieval = self.graph(llm, self.ids[:3], self.ids[3:])

        events = await run_turn(graph, self.chat, self.user, "Az bilinen polisiyeler")

        self.assertEqual(len(data_of(events, "notice")), 1)  # oy sayısı sınırı gevşetildi
        self.assertIsNone(retrieval.calls[1]["request"].filters.max_vote_count)
        collection = await self.latest_collection()
        self.assertEqual(collection.request["filters"]["max_vote_count"], 2000)

        await run_turn(graph, self.chat, self.user, "Yeniden araştır", action={"type": "research"})

        self.assertEqual(retrieval.calls[2]["request"].filters.max_vote_count, 2000)


class StreamErrorCodeTests(FlowTestCase):
    async def run_with_error(self, error):
        class Failing(FakeRetrieval):
            async def search(self, *args, **kwargs):
                raise error

        graph = make_graph(FakeLLM(), Failing())
        events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 5 film")
        return events, data_of(events, "error")[0]

    async def test_internal_service_error_codes_become_server_error(self):
        error = ServiceError("iç ayrıntı: tablo x", "quote_unverified", 422)

        events, payload = await self.run_with_error(error)

        self.assertEqual(payload["code"], "server_error")
        self.assertNotIn("iç ayrıntı", payload["detail"])
        self.assertNotIn("quote_unverified", str(events))
        saved = await Message.objects.filter(role="assistant").afirst()
        self.assertEqual(saved.error, payload)

    async def test_allowed_codes_pass_through_unchanged(self):
        for code in sorted(STREAM_ERROR_CODES):
            with self.subTest(code=code):
                _, payload = await self.run_with_error(ServiceError("Sade mesaj.", code, 409))
                self.assertEqual(payload, {"detail": "Sade mesaj.", "code": code})
