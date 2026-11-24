from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.search.services import lexical
from apps.search.tests.base import make_film, search_settings


class BuildSearchIndexCommandTests(TestCase):
    def test_builds_index_and_reports_film_count(self):
        make_film("Q1")
        make_film("Q2")
        out = StringIO()
        with search_settings():
            call_command("build_search_index", stdout=out)
            self.assertTrue(lexical.index_exists())
        self.assertIn("2 film", out.getvalue())


class EvaluateSearchCommandTests(TestCase):
    def test_unknown_doc_mode_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("evaluate_search", "--set", "known50", "--doc", "C")

    def test_blend_must_be_between_zero_and_one(self):
        with self.assertRaises(CommandError):
            call_command("evaluate_search", "--set", "known50", "--blend", "1.5")

    def test_missing_evaluation_data_is_reported_not_crashed(self):
        with search_settings(eval_data_dir="/nonexistent"), self.assertRaises(CommandError) as ctx:
            call_command("evaluate_search", "--set", "known50")
        self.assertIn("eval_data_missing", str(ctx.exception))
