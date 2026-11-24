import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.agent import runtime, scenarios
from apps.agent.runtime import get_graph
from apps.agent.services import eval_run
from apps.agent.tests.base import FakeRetrieval, make_graph
from apps.agent.tests.eval_base import MeteredLLM, make_eval_request
from apps.chats.models import Chat, Message
from apps.core.exceptions import ServiceError
from apps.curation.models import Collection
from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user

MODEL = "claude-haiku-5-5"


class EvalRunBase(TestCase):
    def setUp(self):
        self.user = eval_run.get_eval_user()
        self.films = [make_story_film(n) for n in range(1, 9)]  # Q1..Q8
        self.ids = [film.pk for film in self.films]
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        self.out = directory / "out.json"
        self.llm = MeteredLLM()
        self.retrieval = FakeRetrieval(self.ids)
        self.install(self.llm, self.retrieval)

    def install(self, llm, retrieval):
        """Komutun kurduğu gibi: arama, kaydedici sarmalayıcıyla grafa verilir."""
        runtime.set_graph(make_graph(llm, eval_run.RecordingRetrieval(retrieval)))
        self.addCleanup(runtime.set_graph, None)

    async def run_eval(self, requests, **overrides):
        options = {
            "model": MODEL,
            "sets": sorted({request.set_name for request in requests}),
            "out_path": self.out,
            "prices": scenarios.PRICES,
        } | overrides
        return await eval_run.run_evaluation(self.user, requests, **options)


class MeasurementTests(EvalRunBase):
    async def test_each_set_is_measured_from_the_final_draft(self):
        film = {f.wikidata_id: f.pk for f in self.films}
        requests = [
            make_eval_request(
                "known50",
                "a",
                target_wikidata_id="Q2",
                target_film_id=film["Q2"],
                known=True,
            ),
            make_eval_request(
                "known50", "b", target_wikidata_id="Q8", target_film_id=film["Q8"], known=False
            ),
            make_eval_request("konu30", "a", answer_qids=frozenset({"Q1", "Q2", "Q9"})),
            make_eval_request(
                "tone25",
                "a",
                gains={film["Q1"]: 0.9, film["Q2"]: 0.85, film["Q3"]: 0.2, film["Q7"]: 0.99},
                relevant=frozenset({film["Q1"], film["Q2"], film["Q7"]}),
            ),
        ]

        report = await self.run_eval(requests, concurrency=2)

        self.assertEqual(len(report["requests"]), 4)
        for record in report["requests"].values():
            self.assertEqual(record["status"], "ok")
            self.assertEqual(record["film_count"], 5)  # taslak: arama sırasının ilk 5'i (Q1..Q5)
            self.assertEqual(record["quote_match_rate"], 1.0)
            self.assertEqual(record["dropped_films"], 0)
            self.assertEqual(
                [f["wikidata_id"] for f in record["draft"]], [f"Q{n}" for n in range(1, 6)]
            )

        hit = report["requests"]["known50:a"]["metrics"]
        self.assertEqual(
            (hit["hit_draft"], hit["draft_rank"], hit["first_search_rank"]), (True, 2, 2)
        )
        miss = report["requests"]["known50:b"]["metrics"]
        # Hedef aday listesinde 8. ama taslağa girmedi; turlar aynı anda koşsa da kayıt karışmaz.
        self.assertEqual(
            (miss["hit_draft"], miss["draft_rank"], miss["first_search_rank"]), (False, None, 8)
        )
        konu = report["requests"]["konu30:a"]["metrics"]
        self.assertEqual((konu["matched"], konu["precision_draft"]), (2, 0.4))
        tone = report["requests"]["tone25:a"]["metrics"]
        # Taslakta Q1..Q5: Q1, Q2, Q3 yargılı (Q1, Q2 uygun); Q4, Q5 kapsam dışı.
        self.assertEqual((tone["covered"], tone["uncovered"], tone["appropriate"]), (3, 2, 2))
        self.assertAlmostEqual(tone["precision_covered"], 2 / 3)
        hit_rate = report["summary"]["known50"]["hit_draft_defined"]
        self.assertEqual(
            (hit_rate["value"], hit_rate["n"], hit_rate["denominator"]), (0.5, 2, "n_ok")
        )

    async def test_tokens_calls_and_ranks_stay_apart_while_turns_truly_overlap(self):
        # Bariyer 4 turun `parse` adımını birbirini bekletir: seri koşarsa 5 sn sonra zaman aşımı
        # (tur "hata" olur ve aşağıdaki durum denetimi kırılır).
        llm = MeteredLLM(
            weights={"istek a": 1, "istek b": 2, "istek c": 3, "istek d": 4},
            barrier=asyncio.Barrier(4),
        )
        self.install(llm, self.retrieval)
        film = {f.wikidata_id: f.pk for f in self.films}
        requests = [
            make_eval_request(
                "known50",
                name,
                target_wikidata_id=f"Q{rank}",
                target_film_id=film[f"Q{rank}"],
                known=True,
            )
            for rank, name in enumerate("abcd", start=1)
        ]

        report = await self.run_eval(requests, concurrency=4)

        records = report["requests"]
        self.assertEqual({r["status"] for r in records.values()}, {"ok"})
        per_turn = records["known50:a"]["calls"]
        self.assertGreater(per_turn, 3)
        self.assertEqual(len(llm.calls), 4 * per_turn)
        for weight, name in enumerate("abcd", start=1):
            record = records[f"known50:{name}"]
            self.assertEqual(record["calls"], per_turn)
            self.assertEqual(record["input_tokens"], per_turn * 1000 * weight)
            self.assertEqual(record["output_tokens"], per_turn * 500 * weight)
            self.assertAlmostEqual(
                record["cost_usd"], weight * per_turn * (1000 * 0.10 + 500 * 0.50) / 1_000_000
            )
            self.assertIn("parse", record["step_seconds"])
            self.assertEqual(record["search_calls"], 1)
            # Her tur kendi hedefinin aday sırasını görür (a: 1, b: 2, c: 3, d: 4).
            self.assertEqual(record["metrics"]["first_search_rank"], weight)

    async def test_request_text_is_sent_alone_and_nothing_from_the_answer_key(self):
        request = make_eval_request(
            "known50",
            "a",
            text="Karlı kasabada geçen ağır tempolu bir polisiye",
            target_wikidata_id="Q2",
            target_film_id=self.ids[1],
            known=True,
        )

        report = await self.run_eval([request], keep=True)

        prompt = self.llm.steps("parse")[0].user
        self.assertEqual(prompt, f"<user_message>{request.text}</user_message>")
        message = await Message.objects.aget(
            chat_id=report["requests"][request.key]["chat_id"], role="user"
        )
        self.assertEqual(message.text, request.text)

    async def test_failed_turn_is_reported_with_its_error_and_excluded_from_rates(self):
        self.llm.fail_step = "parse"

        report = await self.run_eval(
            [make_eval_request("konu30", "a", answer_qids=frozenset({"Q1"}))]
        )

        record = report["requests"]["konu30:a"]
        self.assertEqual(record["status"], "hata")
        self.assertEqual(record["error"]["code"], "model_error")
        self.assertEqual(record["metrics"], {})
        summary = report["summary"]["konu30"]
        defined, every = summary["precision_draft_defined"], summary["precision_draft_all"]
        self.assertEqual(summary["failed"], 1)
        # Hatalı tur tanımlı kümede yok (payda 0); bütün isteklerde ıska (0 / 1).
        self.assertEqual((defined["value"], defined["n"]), (None, 0))
        self.assertEqual((every["value"], every["n"]), (0.0, 1))

    async def test_turn_without_a_draft_is_marked_and_relaxed_filters_are_recorded(self):
        self.install(self.llm, FakeRetrieval(([], ("year",))))
        request = make_eval_request(
            "known50", "a", target_wikidata_id="Q2", target_film_id=self.ids[1], known=True
        )

        report = await self.run_eval([request])

        record = report["requests"]["known50:a"]
        self.assertEqual(record["status"], "taslak yok")
        self.assertEqual(record["film_count"], 0)
        self.assertEqual(record["search_calls"], 3)  # ilk arama + iki gevşetme denemesi
        self.assertEqual(record["relaxed_by_agent"], ["country"])
        self.assertEqual(record["relaxed_by_search"], ["year"])
        self.assertFalse(record["metrics"]["hit_draft"])
        self.assertTrue(record["metrics"]["searched"])
        self.assertIsNone(record["metrics"]["first_search_rank"])  # arandı, hedef yok

    async def test_unknown_model_price_gives_unknown_spend_and_never_stops(self):
        requests = [
            make_eval_request("konu30", name, answer_qids=frozenset({"Q1"})) for name in "ab"
        ]

        report = await self.run_eval(requests, model="bilinmeyen-model", budget_usd=0.000001)

        self.assertIsNone(report["spent_usd"])
        self.assertIsNone(report["summary"]["konu30"]["total_cost_usd"])
        self.assertEqual(len(report["requests"]), 2)
        self.assertFalse(report["stopped_at_budget"])


class FailureAndCoverageTests(EvalRunBase):
    async def test_unexpected_error_in_one_turn_is_recorded_and_does_not_stop_the_others(self):
        self.llm.input_tokens, self.llm.output_tokens = 1_000_000, 0
        graph = get_graph()
        original = graph.aget_state
        failures = []

        async def flaky(config, *args, **kwargs):
            # Ölçümün turdan sonraki okuması (akışın kendi okumasında recursion_limit vardır).
            if "recursion_limit" not in config and not failures:
                failures.append(config)
                raise RuntimeError("veritabanı koptu")
            return await original(config, *args, **kwargs)

        requests = [
            make_eval_request("konu30", name, answer_qids=frozenset({"Q1"})) for name in "abc"
        ]
        with mock.patch.object(graph, "aget_state", flaky):
            report = await self.run_eval(requests, concurrency=3)

        records = list(report["requests"].values())
        failed = [r for r in records if r["status"] == "hata"]
        self.assertEqual(len(records), 3)
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["error"]["code"], "eval_exception")
        self.assertEqual([r["status"] for r in records if r is not failed[0]], ["ok", "ok"])
        # Hata turunun harcaması kayıtta ve toplamda; üç tur de tam akışı koştu (6 çağrı x 0,10).
        self.assertGreater(failed[0]["calls"], 0)
        self.assertAlmostEqual(failed[0]["cost_usd"], 0.6)
        self.assertAlmostEqual(report["spent_usd"], 1.8)

    async def test_retried_turn_keeps_the_spend_of_the_failed_attempt(self):
        self.llm.input_tokens, self.llm.output_tokens = 1_000_000, 0
        requests = [make_eval_request("konu30", "a", answer_qids=frozenset({"Q1"}))]
        self.llm.fail_step = "select"  # parse ve judge harcanır, tur hata ile biter
        first = await self.run_eval(requests)
        record = first["requests"]["konu30:a"]
        self.assertEqual((record["status"], record["attempts"]), ("hata", 1))
        self.assertAlmostEqual(record["total_cost_usd"], 0.2)

        self.llm.fail_step = None
        second = await self.run_eval(requests)

        record = second["requests"]["konu30:a"]
        self.assertEqual((record["status"], record["attempts"]), ("ok", 2))
        self.assertAlmostEqual(record["cost_usd"], 0.6)  # yalnız son deneme
        self.assertAlmostEqual(record["total_cost_usd"], 0.8)  # eski deneme düşmedi
        self.assertAlmostEqual(second["spent_usd"], 0.8)
        self.assertAlmostEqual(second["summary"]["konu30"]["total_cost_usd"], 0.8)

    async def test_budget_counts_the_spend_of_earlier_failed_attempts(self):
        self.llm.input_tokens, self.llm.output_tokens = 1_000_000, 0
        requests = [
            make_eval_request("konu30", name, answer_qids=frozenset({"Q1"})) for name in "ab"
        ]
        self.llm.fail_step = "select"
        await self.run_eval(requests[:1], concurrency=1)  # a: hata, 0,2 harcandı
        self.llm.fail_step = None

        report = await self.run_eval(requests, budget_usd=0.7, concurrency=1)

        # a yeniden koşar (0,2 + 0,6 = 0,8 >= 0,7): b sınırda başlamaz.
        self.assertEqual(report["skipped"], ["konu30:b"])
        self.assertAlmostEqual(report["spent_usd"], 0.8)

    async def test_konu30_answer_list_coverage_is_recorded_even_when_the_turn_fails(self):
        self.llm.fail_step = "parse"
        request = make_eval_request(
            "konu30", "b", answer_qids=frozenset({"Q1", "Q2", "Q999"}), answer_in_db=2
        )

        report = await self.run_eval([request])

        record = report["requests"]["konu30:b"]
        self.assertEqual(record["status"], "hata")
        self.assertEqual(record["answer_key"], {"size": 3, "in_db": 2, "missing": 1})
        summary = report["summary"]["konu30"]
        self.assertEqual(
            (summary["answer_ids"], summary["answer_in_db"], summary["answer_missing"]), (3, 2, 1)
        )


class BudgetAndResumeTests(EvalRunBase):
    def expensive(self):
        # Çağrı başına 1M girdi tokenı: Haiku fiyatıyla çağrı başına 0,10 dolar.
        self.llm.input_tokens, self.llm.output_tokens = 1_000_000, 0

    def requests(self, names="abcd"):
        return [make_eval_request("konu30", name, answer_qids=frozenset({"Q1"})) for name in names]

    async def test_no_new_turn_starts_once_the_budget_is_spent(self):
        self.expensive()

        report = await self.run_eval(self.requests(), budget_usd=1.0, concurrency=1)

        # Tur başına 6 çağrı = 0,60 dolar: ikinci tur sonunda 1,20 >= 1,0, üçüncü başlamaz.
        self.assertEqual(len(report["requests"]), 2)
        self.assertTrue(report["stopped_at_budget"])
        self.assertEqual(report["skipped"], ["konu30:c", "konu30:d"])
        self.assertAlmostEqual(report["spent_usd"], 1.2)
        self.assertEqual(len(self.retrieval.calls), 2)
        saved = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(set(saved["requests"]), {"konu30:a", "konu30:b"})

    async def test_resume_skips_finished_requests_and_counts_earlier_spend(self):
        self.expensive()
        await self.run_eval(self.requests("abc"), budget_usd=0.5, concurrency=1)
        self.assertEqual(len(self.retrieval.calls), 1)  # yalnız a koştu

        second = await self.run_eval(self.requests("abc"), budget_usd=1.0, concurrency=1)

        # a atlandı (önceki 0,60 sayıldı), b koştu (1,20), c sınırda başlamadı.
        self.assertEqual(len(self.retrieval.calls), 2)
        self.assertEqual(sorted(second["requests"]), ["konu30:a", "konu30:b"])
        self.assertEqual(second["resumed_from"], 1)
        self.assertEqual(second["skipped"], ["konu30:c"])

        third = await self.run_eval(self.requests("abc"), budget_usd=5.0, concurrency=1)

        self.assertEqual(len(self.retrieval.calls), 3)
        self.assertEqual(sorted(third["requests"]), ["konu30:a", "konu30:b", "konu30:c"])
        self.assertFalse(third["stopped_at_budget"])

    async def test_failed_turns_are_retried_on_resume(self):
        self.llm.fail_step = "parse"
        first = await self.run_eval(self.requests("a"))
        self.assertEqual(first["requests"]["konu30:a"]["status"], "hata")

        self.llm.fail_step = None
        second = await self.run_eval(self.requests("a"))

        self.assertEqual(second["requests"]["konu30:a"]["status"], "ok")

    async def test_resume_from_an_older_output_version_is_refused_clearly(self):
        self.out.write_text(
            json.dumps({"version": 1, "model": MODEL, "sets": ["konu30"], "sample": None}),
            encoding="utf-8",
        )

        with self.assertRaises(ServiceError) as ctx:
            await self.run_eval(self.requests("a"))

        self.assertEqual(ctx.exception.code, "eval_resume_incompatible")
        self.assertIn("uyumsuz çıktı sürümü", ctx.exception.message)

    async def test_resume_with_a_different_model_or_sample_is_refused(self):
        await self.run_eval(self.requests("a"))

        with self.assertRaises(ServiceError) as ctx:
            await self.run_eval(self.requests("a"), model="claude-sonnet-5-5")
        self.assertEqual(ctx.exception.code, "eval_resume_mismatch")
        with self.assertRaises(ServiceError):
            await self.run_eval(self.requests("a"), sample=3)

    async def test_report_is_written_after_every_turn_not_only_at_the_end(self):
        seen = []
        out = self.out

        class Snooping(FakeRetrieval):
            async def search(self, request, *, limit, exclude_film_ids=()):
                seen.append(
                    sorted(json.loads(out.read_text(encoding="utf-8"))["requests"])
                    if out.exists()
                    else None
                )
                return await super().search(request, limit=limit, exclude_film_ids=exclude_film_ids)

        self.install(self.llm, Snooping(self.ids))

        await self.run_eval(self.requests("ab"), concurrency=1)

        self.assertEqual(seen, [None, ["konu30:a"]])  # b başlarken a diskte


class CleanupTests(EvalRunBase):
    def requests(self):
        return [make_eval_request("konu30", name, answer_qids=frozenset({"Q1"})) for name in "ab"]

    async def test_run_data_is_deleted_and_nobody_elses_data_is_touched(self):
        from asgiref.sync import sync_to_async

        def seed():
            other = make_user("baska")
            theirs = make_chat(other)
            their_collection = make_collection(other, theirs, films=self.films[:2])
            mine_before = make_chat(self.user, "eski ölçüm sohbeti")
            my_old_collection = make_collection(self.user, mine_before, films=self.films[:2])
            return theirs, their_collection, mine_before, my_old_collection

        theirs, their_collection, mine_before, my_old_collection = await sync_to_async(seed)()

        report = await self.run_eval(self.requests())

        chat_ids = [record["chat_id"] for record in report["requests"].values()]
        self.assertEqual(len(chat_ids), 2)
        self.assertFalse(await Chat.objects.filter(pk__in=chat_ids).aexists())
        self.assertFalse(await Collection.objects.filter(chat_id__in=chat_ids).aexists())
        self.assertFalse(
            await Collection.objects.filter(owner=self.user, chat__isnull=True).aexists()
        )
        # Başkasının ve ölçüm kullanıcısının önceki verisi yerinde.
        self.assertTrue(await Chat.objects.filter(pk=theirs.pk).aexists())
        self.assertTrue(await Collection.objects.filter(pk=their_collection.pk).aexists())
        self.assertTrue(await Chat.objects.filter(pk=mine_before.pk).aexists())
        self.assertTrue(await Collection.objects.filter(pk=my_old_collection.pk).aexists())

    async def test_keep_leaves_chats_and_drafts_in_place(self):
        report = await self.run_eval(self.requests(), keep=True)

        chat_ids = [record["chat_id"] for record in report["requests"].values()]
        self.assertEqual(await Chat.objects.filter(pk__in=chat_ids).acount(), 2)
        self.assertEqual(await Collection.objects.filter(chat_id__in=chat_ids).acount(), 2)

    async def test_draft_is_never_approved(self):
        report = await self.run_eval(self.requests(), keep=True)

        chat_ids = [record["chat_id"] for record in report["requests"].values()]
        statuses = [
            status
            async for status in Collection.objects.filter(chat_id__in=chat_ids).values_list(
                "status", flat=True
            )
        ]
        self.assertEqual(statuses, ["draft", "draft"])

    async def test_checkpoint_of_the_run_threads_is_removed(self):
        report = await self.run_eval(self.requests()[:1], keep=True)
        chat = await Chat.objects.aget(pk=report["requests"]["konu30:a"]["chat_id"])
        config = {"configurable": {"thread_id": str(chat.thread_id)}}
        self.assertTrue((await get_graph().aget_state(config)).values)

        await eval_run.cleanup(self.user, [(chat.pk, str(chat.thread_id))])

        self.assertFalse((await get_graph().aget_state(config)).values)
        self.assertFalse(await Chat.objects.filter(pk=chat.pk).aexists())


class EvalUserTests(TestCase):
    def test_existing_user_gets_an_unusable_password_on_every_run(self):
        user = get_user_model().objects.create_user(username="eval_runner", password="aciksifre")
        self.assertTrue(user.has_usable_password())

        eval_run.get_eval_user()

        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())

    def test_privileged_eval_user_stops_the_run(self):
        for flag in ("is_staff", "is_superuser"):
            with self.subTest(flag=flag):
                get_user_model().objects.filter(username="eval_runner").delete()
                get_user_model().objects.create_user(username="eval_runner", **{flag: True})

                with self.assertRaises(ServiceError) as ctx:
                    eval_run.get_eval_user()

                self.assertEqual(ctx.exception.code, "eval_user_privileged")

    def test_eval_user_is_created_once_with_an_unusable_password(self):
        user = eval_run.get_eval_user()

        self.assertEqual(user.username, "eval_runner")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(eval_run.get_eval_user().pk, user.pk)
