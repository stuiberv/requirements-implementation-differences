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

from evals.run import ROOT, load_case, render, score
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
        self.assertIn("Finding contract, version 1", captured["instructions"])
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
            self.assertIn("Finding contract, version 1", captured["instructions"])

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
