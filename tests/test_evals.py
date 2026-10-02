import copy
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from evals.run import ROOT, create_run_directory, load_case, main, render, score
from models import ValidationResult
from validator import validate_repository
import agent


def response(identifier="REQ-001", status="SATISFIED"):
    return {
        "findings": [{
            "requirement_id": identifier,
            "status": status,
            "requirement": "The HTML must contain an h1 with text Welcome.",
            "evidence": '[requirements.md:L1] "The HTML must contain an h1 with text Welcome."; [app.txt:L1] "<h1>Welcome</h1>"',
            "explanation": "The supplied HTML contains the requested heading.",
            "severity": "none" if status == "SATISFIED" else "medium",
            "confidence": 0.9,
            "clarification_question": None,
        }],
        "engineering_risks": [],
    }


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case, self.files, self.expected = load_case(ROOT / "evals/cases/satisfied")

    def errors(self, data):
        return score(ValidationResult.model_validate(data), self.files, self.expected)

    def test_valid_evidence_passes(self):
        self.assertEqual([], self.errors(response()))

    def test_check_comparisons_include_citation_source_and_actual_excerpt(self):
        data = response()
        data["findings"][0]["evidence"] = '[requirements.md:L1] "REQ-001"; [app.txt:L1] "<h1>Goodbye</h1>"'
        checks = []
        errors = score(ValidationResult.model_validate(data), self.files, self.expected, checks)
        citation = next(c for c in checks if c["kind"] == "Citation excerpt" and "app.txt:L1" in c["target"])
        self.assertIn("<h1>Welcome</h1>", citation["expected"])
        self.assertIn("<h1>Goodbye</h1>", citation["actual"])
        self.assertEqual(data["findings"][0]["evidence"], citation["evidence"])
        self.assertFalse(citation["passed"])
        self.assertEqual(errors, self.errors(data))

    def test_check_comparisons_cover_all_scored_rule_types(self):
        expected = copy.deepcopy(self.expected)
        expected["findings"][0]["clarification"] = True
        checks = []
        score(ValidationResult.model_validate(response()), self.files, expected, checks)
        self.assertTrue({"Unique ID", "Citation presence", "Citation excerpt", "Finding coverage",
                         "Finding matching", "Verdict", "Evidence sources", "Clarification",
                         "Engineering risks"} <= {c["kind"] for c in checks})
        self.assertTrue(all("expected" in c and "actual" in c for c in checks))

    def test_repeated_live_runs_preserve_old_results_and_report_new_path(self):
        class FakeClient:
            def validate(self, instructions, input_text):
                return ValidationResult.model_validate(response())

        with tempfile.TemporaryDirectory() as directory:
            requested = Path(directory) / "run-001"
            requested.mkdir()
            previous = requested / "satisfied.json"
            previous.write_text("previous result", encoding="utf-8")
            for suffix in [2, 3]:
                output, logs = io.StringIO(), io.StringIO()
                with patch("llm.agent_factory.create_llm_client", return_value=FakeClient()), contextlib.redirect_stdout(output), contextlib.redirect_stderr(logs):
                    code = main(["--live", "--model", "fake", "--output", str(requested), "--case", "satisfied"])
                self.assertEqual(0, code)
                report = json.loads(output.getvalue())
                actual = requested.with_name(f"run-001-{suffix}")
                self.assertEqual(str(actual.resolve()), report["output_directory"])
                self.assertIn(str(actual.resolve()), logs.getvalue())
                self.assertEqual(report, json.loads((actual / "report.json").read_text()))
                self.assertTrue((actual / "satisfied.json").is_file())
                self.assertIn("1 passed", (actual / "report.html").read_text(encoding="utf-8"))
                self.assertIn("expected", report["cases"][0])
                self.assertEqual("previous result", previous.read_text())
            self.assertTrue((requested.with_name("run-001-2") / "report.json").is_file())

    def test_new_output_directory_uses_requested_name(self):
        with tempfile.TemporaryDirectory() as directory:
            requested = Path(directory) / "nested" / "run"
            self.assertEqual(requested, create_run_directory(requested))
            self.assertTrue(requested.is_dir())

    def test_output_file_collision_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            requested = Path(directory) / "run"
            requested.write_text("keep me", encoding="utf-8")
            self.assertEqual(requested.with_name("run-2"), create_run_directory(requested))
            self.assertEqual("keep me", requested.read_text())

    def test_output_permission_error_does_not_retry_forever(self):
        with patch.object(Path, "mkdir", side_effect=PermissionError("denied")) as mkdir:
            with self.assertRaises(PermissionError):
                create_run_directory(Path("run"))
            self.assertEqual(1, mkdir.call_count)

    def inferred_result(self, case_name="inferred-root-satisfied", identifier="scope.md::L1"):
        _, files, expected = load_case(ROOT / "evals/cases" / case_name)
        data = response(identifier, expected["findings"][0]["status"])
        finding = data["findings"][0]
        finding["requirement"] = "Entry point location inferred from hosting scope."
        finding["explanation"] = "The supplied publishing location determines the expected entry point."
        finding["clarification_question"] = "Which directory is published?" if finding["status"] == "AMBIGUOUS" else None
        finding["evidence"] = "; ".join(
            f'[{path}:L{line}] "{text}"'
            for path in ["scope.md", "repo-tree.txt"]
            for line, text in enumerate(files[path].splitlines(), 1)
        )
        return files, expected, data

    def test_inferred_constraint_matches_premises_not_generated_label(self):
        for identifier in ["scope.md::L1", "scope.md::L2", "inferred-entry-point"]:
            with self.subTest(identifier=identifier):
                files, expected, data = self.inferred_result(identifier=identifier)
                self.assertEqual([], score(ValidationResult.model_validate(data), files, expected))

    def test_inference_requires_every_premise_and_implementation_evidence(self):
        for omitted in ["scope.md:L1", "scope.md:L2", "scope.md:L3", "repo-tree.txt"]:
            with self.subTest(omitted=omitted):
                files, expected, data = self.inferred_result()
                finding = data["findings"][0]
                finding["evidence"] = "; ".join(c for c in finding["evidence"].split("; ") if omitted not in c)
                self.assertTrue(score(ValidationResult.model_validate(data), files, expected))

    def test_inference_with_fabricated_premise_fails(self):
        files, expected, data = self.inferred_result()
        data["findings"][0]["evidence"] = data["findings"][0]["evidence"].replace("repository root", "docs directory")
        self.assertTrue(score(ValidationResult.model_validate(data), files, expected))

    def test_duplicate_inferred_constraint_under_different_ids_fails(self):
        files, expected, data = self.inferred_result()
        duplicate = copy.deepcopy(data["findings"][0])
        duplicate["requirement_id"] = "another-label"
        data["findings"].append(duplicate)
        self.assertTrue(any("Non-unique" in e for e in score(ValidationResult.model_validate(data), files, expected)))

    def test_missing_publishing_root_requires_clarification_not_a_violation(self):
        files, expected, data = self.inferred_result("unknown-publishing-root")
        self.assertEqual([], score(ValidationResult.model_validate(data), files, expected))
        data["findings"][0]["status"] = "NOT_SATISFIED"
        self.assertTrue(any("expected AMBIGUOUS" in e for e in score(ValidationResult.model_validate(data), files, expected)))

    def test_optional_context_findings_still_require_correct_verdict_and_evidence(self):
        files, expected, data = self.inferred_result()
        expected["findings"][0]["optional"] = True
        self.assertEqual([], score(ValidationResult(findings=[], engineering_risks=[]), files, expected))
        self.assertEqual([], score(ValidationResult.model_validate(data), files, expected))
        data["findings"][0].update(status="NOT_SATISFIED", severity="medium")
        self.assertTrue(score(ValidationResult.model_validate(data), files, expected))

    def test_original_scope_statements_are_preserved(self):
        _, files, expected = load_case(ROOT / "evals/cases/static-site-wrong-root")
        scope = files["docs/product-scope.md"]
        self.assertIn('- The site will be hosted using GitHub Pages.\n- GitHub Pages will publish from the repository root.\n- The site entry point is `index.html`.', scope)
        self.assertNotIn("SCOPE-TECH-001", scope)
        rule = next(r for r in expected["findings"] if r["id"] == "inferred-root-entry-point")
        self.assertEqual([19, 20, 21], rule["match_source_lines"])

    def test_wrong_verdict_fails(self):
        self.assertTrue(any("expected SATISFIED" in e for e in self.errors(response(status="NOT_SATISFIED"))))

    def test_missing_requirement_fails(self):
        self.assertTrue(any("Missing finding" in e for e in self.errors({"findings": [], "engineering_risks": []})))

    def test_invented_requirement_fails(self):
        self.assertTrue(any("Unsupported requirement ID" in e for e in self.errors(response("REQ-999"))))

    def test_duplicate_requirement_fails(self):
        data = response()
        data["findings"].append(copy.deepcopy(data["findings"][0]))
        self.assertTrue(any("Duplicate finding" in e for e in self.errors(data)))

    def test_fabricated_citations_fail(self):
        for citation in ['[missing.py:L1] "Welcome"', '[app.txt:L0] "Welcome"', '[app.txt:L9] "Welcome"', '[app.txt:L1] "Goodbye"', 'No citation']:
            with self.subTest(citation=citation):
                data = response()
                data["findings"][0]["evidence"] = citation
                self.assertTrue(self.errors(data))

    def test_requirement_citation_alone_is_insufficient(self):
        data = response()
        data["findings"][0]["evidence"] = '[requirements.md:L1] "REQ-001"'
        self.assertTrue(any("missing source or implementation" in e for e in self.errors(data)))

    def test_unexpected_risk_fails(self):
        data = response()
        data["engineering_risks"] = [{"risk": "Invented concern", "evidence": '[app.txt:L1] "Welcome"', "explanation": "Unsupported", "confidence": 0.8}]
        self.assertTrue(any("Unexpected engineering risks" in e for e in self.errors(data)))

    def test_contract_constraints(self):
        for changes in [{"confidence": -0.1}, {"confidence": 1.1}, {"confidence": float("nan")}, {"severity": "high"}, {"status": "AMBIGUOUS", "severity": "medium", "clarification_question": " "}]:
            with self.subTest(changes=changes):
                data = response()
                data["findings"][0].update(changes)
                with self.assertRaises(ValueError):
                    ValidationResult.model_validate(data)

    def test_all_fixtures_load(self):
        paths = list((ROOT / "evals/cases").glob("*/case.json"))
        self.assertGreaterEqual(len(paths), 9)
        for path in paths:
            with self.subTest(case=path.parent.name):
                load_case(path.parent)

    def test_generated_id_is_scored_without_inventing_semantic_id(self):
        _, files, expected = load_case(ROOT / "evals/cases/unnumbered-constraint")
        data = response("requirements.md::L1", "NOT_SATISFIED")
        data["findings"][0]["evidence"] = '[requirements.md:L1] "The HTML must contain an h1 with text Welcome."; [app.txt:L1] "<h1>Goodbye</h1>"'
        self.assertEqual([], score(ValidationResult.model_validate(data), files, expected))
        data["findings"][0]["requirement_id"] = "GENERATED-001"
        self.assertTrue(score(ValidationResult.model_validate(data), files, expected))

    def test_required_clarification_is_scored(self):
        expected = copy.deepcopy(self.expected)
        expected["findings"][0]["clarification"] = True
        self.assertTrue(any("missing clarification" in e for e in score(ValidationResult.model_validate(response()), self.files, expected)))

    def test_malformed_saved_response_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "satisfied.json").write_text('{"findings":', encoding="utf-8")
            run = subprocess.run([sys.executable, "-m", "evals.run", "--results", directory, "--case", "satisfied"], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(1, run.returncode)
            self.assertIn("ValidationError", run.stdout)

    def test_simulated_paths_are_preserved(self):
        case, files, _ = load_case(ROOT / "evals/cases/static-site-wrong-root")
        self.assertIn("FILE: requirements/index.html", render(files, case["implementation"]))
        self.assertNotIn("FILE: input/index.html", render(files, case["implementation"]))

    def test_validator_passes_contract_and_evidence_to_client(self):
        captured = {}
        expected_result = ValidationResult.model_validate(response())

        class FakeClient:
            def validate(self, instructions, input_text):
                captured.update(instructions=instructions, input_text=input_text)
                return expected_result

        result = validate_repository(FakeClient(), self.files["repo-tree.txt"], "", render(self.files, [self.case["requirements"]]), render(self.files, self.case["implementation"]))
        self.assertIs(result, expected_result)
        self.assertIn("Finding contract, version 2", captured["instructions"])
        self.assertIn("untrusted evidence", captured["instructions"])
        self.assertIn("FILE: app.txt\nL1: <h1>Welcome</h1>", captured["input_text"])

    def test_local_agent_cli_with_fake_client(self):
        captured = {}

        class FakeClient:
            def validate(self, instructions, input_text):
                captured.update(instructions=instructions, input_text=input_text)
                return ValidationResult.model_validate(response())

        with tempfile.TemporaryDirectory() as directory:
            for path, content in self.files.items():
                (Path(directory) / path).write_text(content, encoding="utf-8")
            (Path(directory) / "scope.md").write_text("A static HTML example.", encoding="utf-8")
            argv = ["agent.py", "--local-repo", directory, "--requirements", "requirements.md", "--implementation", "app.txt", "--context", "scope.md"]
            output = io.StringIO()
            with patch.object(sys, "argv", argv), patch.object(agent, "create_llm_client", return_value=FakeClient()), contextlib.redirect_stdout(output):
                agent.main()
            self.assertIn('"SATISFIED"', output.getvalue())
            self.assertIn("FILE: requirements.md", captured["input_text"])
            self.assertIn("FILE: scope.md", captured["input_text"])
            self.assertIn("Finding contract, version 2", captured["instructions"])

    def test_saved_result_cli_pass_and_failure_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "satisfied.json"
            command = [sys.executable, "-m", "evals.run", "--results", directory, "--case", "satisfied"]
            for data, code in [(response(), 0), (response("REQ-999"), 1)]:
                path.write_text(json.dumps(data), encoding="utf-8")
                run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(code, run.returncode, run.stderr)
                self.assertEqual(code == 0, json.loads(run.stdout)["cases"][0]["passed"])

    def test_missing_saved_result_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run([sys.executable, "-m", "evals.run", "--results", directory, "--case", "satisfied"], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(1, run.returncode)
            self.assertIn("FileNotFoundError", run.stdout)


if __name__ == "__main__":
    unittest.main()
