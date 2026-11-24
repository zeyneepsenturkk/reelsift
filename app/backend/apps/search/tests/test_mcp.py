import asyncio
import json
from unittest import mock

import httpx
from django.test import SimpleTestCase, TestCase, override_settings

from apps.search import mcp_server
from apps.search.mcp_server import McpToolError
from apps.search.services.types import Candidate, SearchResult
from apps.search.tests.base import make_film

ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


class KeepConnectionMixin:
    """Araç fonksiyonları iş parçacığı bağlantısını kapatır; testte aynı iş parçacığı olduğu için
    test bağlantısı açık kalmalı."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(mcp_server.connections, "close_all")
        patcher.start()
        self.addCleanup(patcher.stop)


def fake_result(film_ids, relaxed=()):
    candidates = tuple(
        Candidate(pk, 0.9 - i / 100, i + 1, ("dense",)) for i, pk in enumerate(film_ids)
    )
    return SearchResult(candidates, tuple(relaxed), len(candidates), {"total": 0.1})


@override_settings(SEARCH={"warmup": False})
class SearchFilmsTests(KeepConnectionMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_film(
            "M1", title="Alpha", year=1999, directors=("Dir One",), overview="A quiet story."
        )
        cls.b = make_film("M2", title="Beta", year=2005, tr_title="Beta TR")

    def run_search(self, ids, **kwargs):
        with mock.patch(
            "apps.search.services.pipeline.search", return_value=fake_result(ids)
        ) as search:
            result = mcp_server.search_films(**kwargs)
        return result, search

    def test_returns_rows_in_rank_order_with_expected_fields(self):
        result, _ = self.run_search([self.b.pk, self.a.pk], sorgu="a quiet drama")
        self.assertEqual([f["film_id"] for f in result["filmler"]], [self.b.pk, self.a.pk])
        row = result["filmler"][1]
        self.assertEqual(row["sira"], 2)
        self.assertEqual(row["ad"], "Alpha")
        self.assertEqual(row["yil"], 1999)
        self.assertEqual(row["yonetmenler"], ["Dir One"])
        self.assertEqual(row["ozet"], "A quiet story.")
        self.assertEqual(result["filmler"][0]["turkce_ad"], "Beta TR")

    def test_limit_is_clamped_to_1_25(self):
        _, search = self.run_search([self.a.pk], sorgu="x", adet=500)
        self.assertEqual(search.call_args.kwargs["limit"], 25)
        _, search = self.run_search([self.a.pk], sorgu="x", adet=0)
        self.assertEqual(search.call_args.kwargs["limit"], 1)

    def test_arguments_become_query_filters(self):
        _, search = self.run_search(
            [self.a.pk], sorgu="  sea   story ", yil_en_az=1990, yil_en_cok=2000, ulke="Japan"
        )
        query = search.call_args.args[0]
        self.assertEqual(query.en_query, "sea story")
        self.assertEqual(query.filters.year_min, 1990)
        self.assertEqual(query.filters.year_max, 2000)
        self.assertEqual(query.filters.countries, ("Japan",))

    def test_invalid_arguments_raise_clear_errors(self):
        with self.assertRaises(McpToolError):
            mcp_server.search_films(sorgu="   ")
        with self.assertRaises(McpToolError):
            mcp_server.search_films(sorgu="x", yil_en_az=2000, yil_en_cok=1990)

    def test_search_failure_returns_plain_error(self):
        with mock.patch(
            "apps.search.services.pipeline.search", side_effect=RuntimeError("secret path")
        ):
            with self.assertRaises(McpToolError) as ctx:
                mcp_server.search_films(sorgu="x")
        self.assertNotIn("secret", str(ctx.exception))

    def test_cold_search_returns_warming_up_error_without_searching(self):
        with (
            override_settings(SEARCH={"warmup": True}),
            mock.patch("apps.search.services.pipeline.search") as search,
            mock.patch.object(mcp_server, "search_ready", return_value=False),
        ):
            with self.assertRaises(McpToolError) as ctx:
                mcp_server.search_films(sorgu="x")
        self.assertEqual(str(ctx.exception), mcp_server.MSG_WARMING_UP)
        search.assert_not_called()

    def test_search_ready_reflects_loaded_models(self):
        from apps.search.services import lexical, neural

        with override_settings(SEARCH={"warmup": True}):
            with (
                mock.patch.object(lexical, "_loaded", None),
                mock.patch.object(neural, "_embedder", None),
                mock.patch.object(neural, "_reranker", None),
            ):
                self.assertFalse(mcp_server.search_ready())
            with (
                mock.patch.object(lexical, "_loaded", object()),
                mock.patch.object(neural, "_embedder", object()),
                mock.patch.object(neural, "_reranker", object()),
            ):
                self.assertTrue(mcp_server.search_ready())


class GetFilmTests(KeepConnectionMixin, TestCase):
    def test_detail_clips_plot_and_lists_links(self):
        film = make_film("G1", title="Gamma", plot="word " * 600)
        film.tmdb_id = 42
        film.imdb_id = "tt0000042"
        film.save()
        detail = mcp_server.get_film(film.pk)
        self.assertEqual(detail["ad"], "Gamma")
        self.assertLessEqual(len(detail["hikaye"]), mcp_server.PLOT_CHARS + 1)
        self.assertTrue(detail["hikaye"].endswith("…"))
        self.assertEqual(detail["baglantilar"]["tmdb"], "https://www.themoviedb.org/movie/42")
        self.assertIn("imdb", detail["baglantilar"])
        self.assertNotIn("card_embedding", detail)

    def test_unknown_film_raises_clear_error(self):
        with self.assertRaises(McpToolError) as ctx:
            mcp_server.get_film(987654321)
        self.assertIn("987654321", str(ctx.exception))


def parse_body(response):
    text = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        text = next(line[5:] for line in text.splitlines() if line.startswith("data:"))
    return json.loads(text)


class McpAsgiTests(SimpleTestCase):
    def test_mcp_path_answers_initialize_and_tools_list_and_rest_goes_to_django(self):
        from config.asgi import with_mcp

        async def django_stub(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b'{"status":"ok"}'})

        mcp_app, manager = mcp_server.create_asgi_app()
        app = with_mcp(django_stub, mcp_app)

        async def scenario():
            async with manager.run():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://localhost:8000"
                ) as client:
                    init = await client.post(
                        "/mcp",
                        headers=ACCEPT,
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-06-18",
                                "capabilities": {},
                                "clientInfo": {"name": "test", "version": "1"},
                            },
                        },
                    )
                    health = await client.get("/api/health")
                    foreign = await client.post(
                        "/mcp", headers={**ACCEPT, "Host": "evil.example"}, json={}
                    )
                    return init, health, foreign, client

        init, health, foreign, _ = asyncio.run(scenario())
        self.assertEqual(init.status_code, 200)
        self.assertIn("serverInfo", parse_body(init)["result"])
        self.assertEqual(health.json(), {"status": "ok"})
        self.assertIn(foreign.status_code, (400, 403, 421))

    def test_tool_error_message_reaches_the_client(self):
        server = mcp_server.create_server()
        with mock.patch.object(mcp_server, "get_film", side_effect=McpToolError("film yok")):
            with self.assertRaises(Exception) as ctx:
                asyncio.run(server.call_tool("film_getir", {"film_id": 1}))
        self.assertIn("film yok", str(ctx.exception))

    def test_tools_list_names(self):
        server = mcp_server.create_server()
        tools = asyncio.run(server.list_tools())
        self.assertEqual({tool.name for tool in tools}, {"film_ara", "film_getir"})

    def test_disabled_setting_skips_mcp(self):
        from config.asgi import load_mcp

        with override_settings(MCP_ENABLED=False):
            self.assertIsNone(load_mcp())

    def test_load_failure_does_not_break_startup(self):
        from config.asgi import load_mcp

        with mock.patch.object(mcp_server, "create_asgi_app", side_effect=ImportError("yok")):
            self.assertIsNone(load_mcp())
