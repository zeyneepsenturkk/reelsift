"""Bilgi sorularında MCP aracıyla getirilen kaynak özeti: araç, istemci ve cevap yolu."""

import json
from unittest import mock

import httpx2
from asgiref.sync import async_to_sync
from django.test import SimpleTestCase, TestCase, override_settings

from apps.agent import mcp_tools
from apps.agent.services import mcp_client
from apps.agent.tests.base import FakeLLM, FakeRetrieval, data_of, make_graph, run_turn, understood
from apps.curation.tests.base import make_chat, make_user

PAGE = {
    "type": "standard",
    "title": "Zeki Demirkubuz",
    "extract": "Zeki Demirkubuz, Türk yönetmen, senarist ve yapımcıdır.",
    "content_urls": {"desktop": {"page": "https://tr.wikipedia.org/wiki/Zeki_Demirkubuz"}},
}
EN_PAGE = {
    "type": "standard",
    "title": "Film noir",
    "extract": "Film noir is a cinematic term used primarily to describe crime dramas.",
    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Film_noir"}},
}


def fake_wikipedia(routes: dict, calls: list | None = None):
    """`routes`: (alt alan adı, yol parçası) -> JSON; eşleşmeyen istek 404 döner."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if calls is not None:
            calls.append(str(request.url))
        for needle, payload in routes.items():
            if needle in str(request.url):
                if isinstance(payload, Exception):
                    raise payload
                return httpx2.Response(200, json=payload)
        return httpx2.Response(404, json={})

    def factory():
        return httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler), headers={"User-Agent": "ReelSift/1.0"}
        )

    return factory


def run_tool(routes, title, language="tr", calls=None):
    with mock.patch.object(mcp_tools, "_http_client", fake_wikipedia(routes, calls)):
        return async_to_sync(mcp_tools.wikipedia_ozet)(title, language)


class WikipediaToolTests(SimpleTestCase):
    def test_exact_title_returns_summary_and_address(self):
        out = run_tool(
            {"tr.wikipedia.org/api/rest_v1/page/summary/Zeki_Demirkubuz": PAGE}, "Zeki Demirkubuz"
        )

        self.assertEqual(out["bulundu"], True)
        self.assertEqual(out["baslik"], "Zeki Demirkubuz")
        self.assertEqual(out["adres"], "https://tr.wikipedia.org/wiki/Zeki_Demirkubuz")
        self.assertEqual(out["dil"], "tr")
        self.assertIn("yönetmen", out["ozet"])

    def test_falls_back_to_english_when_turkish_has_no_page(self):
        out = run_tool(
            {"en.wikipedia.org/api/rest_v1/page/summary/Film_noir": EN_PAGE}, "Film noir"
        )

        self.assertEqual((out["bulundu"], out["dil"]), (True, "en"))
        self.assertEqual(out["adres"], "https://en.wikipedia.org/wiki/Film_noir")

    def test_closest_page_found_through_title_search(self):
        routes = {
            "tr.wikipedia.org/w/api.php": {"query": {"search": [{"title": "Zeki Demirkubuz"}]}},
            "tr.wikipedia.org/api/rest_v1/page/summary/Zeki_Demirkubuz": PAGE,
        }

        out = run_tool(routes, "Zeki Demirkub")

        self.assertEqual((out["bulundu"], out["baslik"]), (True, "Zeki Demirkubuz"))

    def test_nothing_found_returns_not_found(self):
        out = run_tool({}, "Olmayan Başlık")

        self.assertEqual(out["bulundu"], False)
        self.assertEqual(out["ozet"], "")

    def test_disambiguation_page_is_not_a_result(self):
        page = dict(PAGE, type="disambiguation")

        out = run_tool({"tr.wikipedia.org/api/rest_v1/page/summary/": page}, "Zeki")

        self.assertEqual(out["bulundu"], False)

    def test_timeout_returns_not_found_without_raising(self):
        routes = {"wikipedia.org": httpx2.ReadTimeout("zaman aşımı")}

        out = run_tool(routes, "Zeki Demirkubuz")

        self.assertEqual(out["bulundu"], False)

    def test_empty_title_makes_no_request(self):
        calls: list = []

        out = run_tool({}, "  ", calls=calls)

        self.assertEqual((out["bulundu"], calls), (False, []))


class McpClientTests(SimpleTestCase):
    def test_tool_is_called_through_the_mcp_protocol_in_memory(self):
        routes = {"tr.wikipedia.org/api/rest_v1/page/summary/Zeki_Demirkubuz": PAGE}
        with mock.patch.object(mcp_tools, "_http_client", fake_wikipedia(routes)):
            out = async_to_sync(mcp_client.call_tool)(
                "wikipedia_ozet", {"baslik": "Zeki Demirkubuz", "dil": "tr"}
            )

        self.assertEqual(out["bulundu"], True)
        self.assertEqual(out["adres"], "https://tr.wikipedia.org/wiki/Zeki_Demirkubuz")

    def test_unknown_tool_returns_none(self):
        self.assertIsNone(async_to_sync(mcp_client.call_tool)("yok_boyle_arac", {}))

    def test_every_failure_returns_none_and_logs_no_text(self):
        with (
            mock.patch.object(mcp_client, "_call", side_effect=RuntimeError("gizli metin")),
            self.assertLogs(mcp_client.logger, "WARNING") as logs,
        ):
            out = async_to_sync(mcp_client.call_tool)("wikipedia_ozet", {"baslik": "x"})

        self.assertIsNone(out)
        self.assertNotIn("gizli metin", json.dumps(logs.output))

    def test_total_timeout_returns_none(self):
        async def slow(name, arguments):
            import asyncio

            await asyncio.sleep(1)

        with (
            mock.patch.object(mcp_client, "_call", slow),
            mock.patch.object(mcp_client, "CALL_TIMEOUT_S", 0.01),
        ):
            self.assertIsNone(async_to_sync(mcp_client.call_tool)("wikipedia_ozet", {}))


FOUND = {
    "bulundu": True,
    "baslik": "Zeki Demirkubuz",
    "ozet": "Zeki Demirkubuz, Türk yönetmendir.",
    "adres": "https://tr.wikipedia.org/wiki/Zeki_Demirkubuz",
    "dil": "tr",
}


class AnswerSourceTests(TestCase):
    def setUp(self):
        self.user = make_user("editor")
        self.chat = make_chat(self.user)

    async def turn(self, llm, tool_result, text="Zeki Demirkubuz kimdir?"):
        graph = make_graph(llm, FakeRetrieval([]))
        with mock.patch.object(
            mcp_client, "call_tool", mock.AsyncMock(return_value=tool_result)
        ) as tool:
            events = await run_turn(graph, self.chat, self.user, text)
        return events, tool

    async def test_summary_enters_the_prompt_and_code_appends_the_source_line(self):
        llm = FakeLLM(understand=understood("other"), subject="Zeki Demirkubuz", reply="Yönetmen.")

        events, tool = await self.turn(llm, FOUND)

        tool.assert_awaited_once_with("wikipedia_ozet", {"baslik": "Zeki Demirkubuz", "dil": "tr"})
        prompt = llm.steps("answer")[-1].user
        self.assertIn("<source_summary", prompt)
        self.assertIn("Türk yönetmendir", prompt)
        text = data_of(events, "message.done")[0]["message"]["text"]
        self.assertTrue(
            text.endswith("Kaynak: Wikipedia, https://tr.wikipedia.org/wiki/Zeki_Demirkubuz")
        )

    async def test_no_subject_means_no_tool_call_and_the_usual_answer(self):
        llm = FakeLLM(understand=understood("other"), subject=None, reply="Merhaba.")

        events, tool = await self.turn(llm, FOUND, text="Merhaba")

        tool.assert_not_awaited()
        self.assertNotIn("<source_summary", llm.steps("answer")[-1].user)
        self.assertNotIn("Kaynak:", data_of(events, "message.done")[0]["message"]["text"])

    async def test_tool_returning_none_keeps_the_usual_answer(self):
        llm = FakeLLM(understand=understood("other"), subject="Zeki Demirkubuz", reply="Yönetmen.")

        events, _ = await self.turn(llm, None)

        self.assertNotIn("<source_summary", llm.steps("answer")[-1].user)
        self.assertEqual(data_of(events, "message.done")[0]["message"]["text"].strip(), "Yönetmen.")

    async def test_tool_not_found_keeps_the_usual_answer(self):
        llm = FakeLLM(understand=understood("other"), subject="Zeki Demirkubuz", reply="Yönetmen.")

        events, _ = await self.turn(llm, {"bulundu": False, "ozet": "", "adres": ""})

        self.assertNotIn("Kaynak:", data_of(events, "message.done")[0]["message"]["text"])

    @override_settings(ANSWER_SOURCES=False)
    async def test_switched_off_makes_no_extra_model_call_and_no_tool_call(self):
        llm = FakeLLM(understand=understood("other"), subject="Zeki Demirkubuz", reply="Yönetmen.")

        events, tool = await self.turn(llm, FOUND)

        self.assertEqual(llm.steps("subject"), [])
        tool.assert_not_awaited()
        self.assertNotIn("<source_summary", llm.steps("answer")[-1].user)
        self.assertNotIn("Kaynak:", data_of(events, "message.done")[0]["message"]["text"])

    async def test_failing_subject_call_does_not_break_the_answer(self):
        llm = FakeLLM(
            understand=understood("other"), subject="x", reply="Yönetmen.", fail_step="subject"
        )

        events, tool = await self.turn(llm, FOUND)

        tool.assert_not_awaited()
        self.assertEqual(data_of(events, "message.done")[0]["message"]["text"].strip(), "Yönetmen.")
