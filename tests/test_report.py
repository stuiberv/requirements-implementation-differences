import json
from pathlib import Path
import tempfile
import unittest

from evals.report import render_report, write_report


class ReportTests(unittest.TestCase):
    def test_scores_categories_and_untrusted_text_are_displayed_safely(self):
        report = {"model": "test", "cases": [
            {"case": "good", "passed": True, "errors": []},
            {"case": "bad", "passed": False, "errors": [
                "REQ: expected AMBIGUOUS, got UNABLE_TO_VERIFY",
                "Invalid citation: app:L1", "Missing finding: root",
                "REQ: missing clarification",
            ]},
        ]}
        html = render_report(report, {"bad": {"findings": [{
            "requirement_id": "REQ", "status": "UNABLE_TO_VERIFY",
            "evidence": '<script>alert("x")</script>',
            "explanation": "Need evidence", "clarification_question": "Which browser?",
        }]}}, {"bad": {"findings": [{"id": "REQ", "status": "AMBIGUOUS"}]}})
        for fragment in ["1 passed · 1 failed · 2 total", "Verdict mismatch", "Citation",
                         "Finding matching", "Clarification", "Which browser?", "<details>"]:
            self.assertIn(fragment, html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_saved_scores_and_expectations_are_preserved_with_missing_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = {"model": "test", "cases": [{"case": "missing", "passed": False,
                "errors": ["Original error"], "expected": {"findings": [
                    {"id": "ORIGINAL", "status": "SATISFIED"}]}}]}
            original = json.dumps(report)
            (root / "report.json").write_text(original, encoding="utf-8")
            output = write_report(root)
            html = output.read_text(encoding="utf-8")
            self.assertIn("ORIGINAL", html)
            self.assertIn("response unavailable", html)
            self.assertIn("Original error", html)
            self.assertEqual(original, (root / "report.json").read_text())

    def test_old_reports_warn_about_current_expectations_and_bad_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "report.json").write_text(json.dumps({"cases": [
                {"case": "satisfied", "passed": True, "errors": []}]}))
            (root / "satisfied.json").write_text("not json")
            html = write_report(root).read_text(encoding="utf-8")
            self.assertIn("1 passed", html)
            self.assertIn("displaying current fixture expectations", html)
            self.assertIn("response unavailable", html)

    def test_case_paths_cannot_escape_run_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["../outside", "..\\outside", "C:outside"]:
                (root / "report.json").write_text(json.dumps({"cases": [
                    {"case": name, "passed": True, "errors": []}]}))
                with self.assertRaises(ValueError):
                    write_report(root)
