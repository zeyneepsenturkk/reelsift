"""Gemini kipinde reddedilen film / aday kümesi turu düşürmez (`AGENT["skip_refused"]`).

Ayar kapalıyken (Claude yolu) ret bugünkü gibi turu bitirir; açıkken yazımda reddedilen film
"alıntısı doğrulanamayan film" yolundan düşer, değerlendirmede reddedilen küme ikiye bölünür."""

from django.conf import settings
from django.test import override_settings

from apps.agent.services import llm as llm_module
from apps.agent.tests.base import FakeLLM, data_of, names, request_lm, run_turn, understood
from apps.agent.tests.test_editor_texts import notes_of
from apps.agent.tests.test_flow import FlowTestCase
from apps.curation.models import CollectionFilm

ASK = "Karlı kasabalar, 5 film"


def gemini_like(**extra):
    """Gemini kipi ayarları: ret atlanır, gerekçe çağrısı film başına."""
    return override_settings(
        AGENT={**settings.AGENT, "skip_refused": True, "write_chunk": 1, **extra}
    )


class RefusedBase(FlowTestCase):
    async def film_ids_in_draft(self) -> list[int]:
        rows = CollectionFilm.objects.filter(collection__chat=self.chat).order_by("position")
        return [row.film_id async for row in rows]

    def assert_ended_with_the_refusal_message(self, events):
        self.assertEqual(names(events)[-1], "error")
        self.assertEqual(
            data_of(events, "error")[0],
            {"detail": llm_module.MSG_REFUSED, "code": "model_error"},
        )


class SkipRefusedOffKeepsTheCurrentBehaviourTests(RefusedBase):
    """Varsayılan (Claude): ret, turu bugünkü ret mesajıyla bitirir."""

    def test_the_setting_is_off_by_default(self):
        self.assertIs(settings.AGENT["skip_refused"], False)

    async def test_a_refused_write_ends_the_turn(self):
        llm = FakeLLM(refused_write_ids={self.ids[1]})
        graph, _ = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, ASK)

        self.assert_ended_with_the_refusal_message(events)
        self.assertEqual(await self.film_ids_in_draft(), [])
        self.assertFalse(any("<problems>" in call.user for call in llm.steps("write")))

    async def test_a_refused_write_ends_the_turn_even_with_one_film_per_call(self):
        llm = FakeLLM(refused_write_ids={self.ids[1]})
        with override_settings(AGENT={**settings.AGENT, "write_chunk": 1}):
            graph, _ = self.graph(llm, self.ids)
            events = await run_turn(graph, self.chat, self.user, ASK)

        self.assert_ended_with_the_refusal_message(events)

    async def test_a_refused_judge_chunk_ends_the_turn_without_splitting(self):
        llm = FakeLLM(refused_judge_ids={self.ids[7]})
        graph, _ = self.graph(llm, self.ids)

        events = await run_turn(graph, self.chat, self.user, ASK)

        self.assert_ended_with_the_refusal_message(events)
        self.assertEqual(len(llm.steps("judge")), 1)

    async def test_a_refused_replacement_candidate_ends_the_turn(self):
        llm = FakeLLM()
        graph, _ = self.graph(llm, self.ids)
        first = data_of(await run_turn(graph, self.chat, self.user, ASK), "collection")[0]
        first_ids = [film["film_id"] for film in first["films"]]
        llm.refused_write_ids = {fid for fid in self.ids if fid not in first_ids}

        events = await run_turn(
            graph,
            self.chat,
            self.user,
            "Bunun yerine başkasını bul",
            action={"type": "replace_film", "film_id": first_ids[1]},
        )

        self.assert_ended_with_the_refusal_message(events)


class RefusedWriteTests(RefusedBase):
    async def test_the_refused_film_is_dropped_and_the_others_keep_their_rationale(self):
        llm = FakeLLM(refused_write_ids={self.ids[1]})
        with gemini_like():
            graph, _ = self.graph(llm, self.ids)
            with self.assertLogs("apps.agent.graph", level="WARNING") as logs:
                events = await run_turn(graph, self.chat, self.user, ASK)

        self.assertNotIn("error", names(events))
        kept = await self.film_ids_in_draft()
        self.assertEqual(kept, [self.ids[0], *self.ids[2:5]])
        rows = [row async for row in CollectionFilm.objects.filter(collection__chat=self.chat)]
        for row in rows:
            self.assertEqual(
                row.rationale, f"{row.film_id} numaralı film kasvetli bir kış polisiyesidir."
            )
        log = "\n".join(logs.output)
        self.assertIn(
            f"llm step=write film_id={self.ids[1]} reddedildi, taslaga girmedi "
            "block_reason=PROHIBITED_CONTENT",
            log,
        )

    async def test_it_goes_through_the_same_dropped_film_path_as_an_unverifiable_quote(self):
        llm = FakeLLM(refused_write_ids={self.ids[1]})
        with gemini_like():
            graph, _ = self.graph(llm, self.ids)
            events = await run_turn(graph, self.chat, self.user, ASK)

        select_done = data_of(events, "step.done")[-1]
        self.assertIn(
            "1 film, alıntısı doğrulanamadığı için dışarıda kaldı.", select_done["detail"]
        )
        self.assertEqual(len(data_of(events, "collection")[0]["films"]), 4)
        notes = notes_of(llm.steps("respond")[0])
        self.assertIn("1 film(s) were left out", notes)
        # Sayı olgusu kaydedilen taslaktan: 5 istendi, 4 var, 1 eksik.
        self.assertIn("Requested number of films: 5. Films in the saved collection: 4.", notes)
        self.assertIn("Missing: 1.", notes)

    async def test_several_refused_films_are_counted_together(self):
        llm = FakeLLM(refused_write_ids={self.ids[0], self.ids[3]})
        with gemini_like():
            graph, _ = self.graph(llm, self.ids)
            events = await run_turn(graph, self.chat, self.user, ASK)

        self.assertEqual(await self.film_ids_in_draft(), [self.ids[1], self.ids[2], self.ids[4]])
        self.assertIn("2 film, alıntısı", data_of(events, "step.done")[-1]["detail"])
        notes = notes_of(llm.steps("respond")[0])
        self.assertIn("2 film(s) were left out", notes)
        self.assertIn("Films in the saved collection: 3.", notes)
        self.assertIn("Missing: 2.", notes)

    async def test_a_refused_chunk_drops_every_film_in_it(self):
        llm = FakeLLM(refused_write_ids={self.ids[1]})
        with gemini_like(write_chunk=2):
            graph, _ = self.graph(llm, self.ids)
            with self.assertLogs("apps.agent.graph", level="WARNING") as logs:
                await run_turn(graph, self.chat, self.user, ASK)

        self.assertEqual(await self.film_ids_in_draft(), self.ids[2:5])
        self.assertIn(f"film_id={self.ids[0]},{self.ids[1]} reddedildi", "\n".join(logs.output))

    async def test_when_every_chosen_film_is_refused_the_turn_ends_with_the_refusal_message(self):
        llm = FakeLLM(refused_write_ids=set(self.ids))
        with gemini_like():
            graph, _ = self.graph(llm, self.ids)
            events = await run_turn(graph, self.chat, self.user, ASK)

        self.assert_ended_with_the_refusal_message(events)
        self.assertEqual(await self.film_ids_in_draft(), [])

    async def test_other_errors_still_end_the_turn(self):
        llm = FakeLLM(fail_step="write")
        with gemini_like():
            graph, _ = self.graph(llm, self.ids)
            events = await run_turn(graph, self.chat, self.user, ASK)

        self.assertEqual(names(events)[-1], "error")
        self.assertEqual(data_of(events, "error")[0]["detail"], llm_module.MSG_UNAVAILABLE)
        self.assertEqual(await self.film_ids_in_draft(), [])

    async def test_a_refused_refine_keeps_the_films_already_in_the_draft(self):
        llm = FakeLLM()
        with gemini_like():
            graph, _ = self.graph(llm, self.ids)
            first = data_of(await run_turn(graph, self.chat, self.user, ASK), "collection")[0]
            first_ids = [film["film_id"] for film in first["films"]]
            new_ids = [fid for fid in self.ids if fid not in first_ids[2:]][:2]
            llm.fit_ids = set(self.ids) - set(first_ids[:2])
            llm.refused_write_ids = set(self.ids) - set(first_ids)
            llm.understand = understood("refine", instruction="darker")

            events = await run_turn(graph, self.chat, self.user, "Daha karanlık olsun")

        self.assertNotIn("error", names(events))
        self.assertTrue(new_ids)
        updated = data_of(events, "collection")[0]
        self.assertEqual([film["film_id"] for film in updated["films"]], first_ids[2:])

    async def test_replacement_goes_on_with_the_next_candidate(self):
        llm = FakeLLM()
        with gemini_like():
            graph, _ = self.graph(llm, self.ids)
            first = data_of(await run_turn(graph, self.chat, self.user, ASK), "collection")[0]
            first_ids = [film["film_id"] for film in first["films"]]
            remaining = [fid for fid in self.ids if fid not in first_ids]
            llm.refused_write_ids = {remaining[0]}

            events = await run_turn(
                graph,
                self.chat,
                self.user,
                "Bunun yerine başkasını bul",
                action={"type": "replace_film", "film_id": first_ids[1]},
            )

        new_ids = [film["film_id"] for film in data_of(events, "collection")[0]["films"]]
        self.assertEqual(new_ids[1], remaining[1])
        self.assertNotIn(remaining[0], new_ids)
        self.assertIn(
            "1 aday, alıntısı doğrulanamadığı için elendi",
            data_of(events, "step.done")[-1]["detail"],
        )
        self.assertIn("1 replacement candidate(s) were skipped", notes_of(llm.steps("respond")[-1]))

    async def test_a_replacement_where_every_candidate_is_refused_leaves_the_draft_unchanged(self):
        llm = FakeLLM()
        with gemini_like():
            graph, _ = self.graph(llm, self.ids)
            first = data_of(await run_turn(graph, self.chat, self.user, ASK), "collection")[0]
            first_ids = [film["film_id"] for film in first["films"]]
            llm.refused_write_ids = {fid for fid in self.ids if fid not in first_ids}

            events = await run_turn(
                graph,
                self.chat,
                self.user,
                "Bunun yerine başkasını bul",
                action={"type": "replace_film", "film_id": first_ids[1]},
            )

        self.assertNotIn("error", names(events))
        self.assertEqual(await self.film_ids_in_draft(), first_ids)
        self.assertEqual(data_of(events, "step.done")[-1]["title"], "Seçkiyi güncelleyemedim.")


class RefusedJudgeTests(RefusedBase):
    def request(self):
        return understood(request=request_lm(target_count=3))

    async def test_a_refused_chunk_is_split_in_two_and_the_refused_half_does_not_fit(self):
        llm = FakeLLM(understand=self.request(), refused_judge_ids={self.ids[7]})
        with gemini_like():
            graph, _ = self.graph(llm, self.ids)
            with self.assertLogs("apps.agent.graph", level="WARNING") as logs:
                events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 3 film")

        self.assertNotIn("error", names(events))
        judge = llm.steps("judge")
        self.assertEqual(len(judge), 3)  # bütün küme + iki yarı
        self.assertEqual(judge[1].user.count("<film id="), 4)
        self.assertEqual(judge[2].user.count("<film id="), 4)
        # İlk yarı geçti, ikinci yarı (ret yinelendi) "uymuyor": taslak yalnız ilk yarıdan.
        self.assertEqual(await self.film_ids_in_draft(), self.ids[:3])
        self.assertIn("read", [data["key"] for data in data_of(events, "step.done")])
        self.assertIn("4 aday reddedildiği için elendi", "\n".join(logs.output))

    async def test_the_halves_are_sorted_by_position_and_each_half_is_asked_once(self):
        llm = FakeLLM(understand=self.request(), refused_judge_ids={self.ids[0]})
        with gemini_like():
            graph, _ = self.graph(llm, self.ids)
            await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 3 film")

        judge = llm.steps("judge")
        self.assertEqual(len(judge), 3)  # tek düzey: yarılar yeniden bölünmez
        # İlk yarı reddedildi (4 aday elendi), ikinci yarı geçti.
        self.assertEqual(await self.film_ids_in_draft(), self.ids[4:7])

    async def test_a_single_refused_candidate_is_eliminated_and_the_turn_goes_on(self):
        llm = FakeLLM(understand=self.request(), refused_judge_ids={self.ids[0]})
        with gemini_like(judge_chunk=1):
            graph, _ = self.graph(llm, self.ids)
            events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 3 film")

        self.assertNotIn("error", names(events))
        self.assertEqual(len(llm.steps("judge")), 8)  # tek adayda bölme yok, yeniden sorma yok
        self.assertEqual(await self.film_ids_in_draft(), self.ids[1:4])

    async def test_a_non_refusal_judge_error_still_ends_the_turn(self):
        llm = FakeLLM(understand=self.request(), fail_step="judge")
        with gemini_like():
            graph, _ = self.graph(llm, self.ids)
            events = await run_turn(graph, self.chat, self.user, "Karlı kasabalar, 3 film")

        self.assertEqual(names(events)[-1], "error")
        self.assertEqual(data_of(events, "error")[0]["detail"], llm_module.MSG_UNAVAILABLE)
        self.assertEqual(len(llm.steps("judge")), 1)
