"""Offline fixture checks, saved-result scoring, and opt-in live evaluations."""

import argparse
import contextlib
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models import ValidationResult
from validator import validate_repository

CITATION = re.compile(r'\[([^\]\n]+):L(\d+)\] "([^"\n]+)"')
STATUSES = {"SATISFIED", "PARTIALLY_SATISFIED", "NOT_SATISFIED", "AMBIGUOUS", "UNABLE_TO_VERIFY"}


def load_case(directory):
    case = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    files = {}
    for path, source in case["files"].items():
        files[path] = source["text"] if "text" in source else (directory / source["file"]).read_text(encoding="utf-8")
    expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    ids = set()
    for finding in expected["findings"]:
        if finding["id"] in ids or finding["status"] not in STATUSES:
            raise ValueError("Duplicate expected ID or invalid status")
        ids.add(finding["id"])
        if finding["source"] not in files:
            raise ValueError("Expected source is not supplied")
        for path in finding.get("evidence_paths", []):
            if path not in files:
                raise ValueError("Expected evidence is not supplied")
    for path in [case["requirements"], *case.get("context", []), *case["implementation"]]:
        if path not in files:
            raise ValueError(f"Missing input: {path}")
    return case, files, expected


def render(files, paths):
    return "\n\n".join(
        f"FILE: {path}\n" + "\n".join(f"L{i}: {line}" for i, line in enumerate(files[path].splitlines(), 1))
        for path in paths
    )


def score(result, files, expected):
    errors = []
    actual = {}
    for finding in result.findings:
        if finding.requirement_id in actual:
            errors.append(f"Duplicate finding: {finding.requirement_id}")
        actual[finding.requirement_id] = finding
    wanted = {item["id"]: item for item in expected["findings"]}
    for identifier in sorted(actual.keys() - wanted.keys()):
        errors.append(f"Unsupported requirement ID: {identifier}")
    valid_paths = {}
    for item in [*result.findings, *result.engineering_risks]:
        paths = set()
        citations = CITATION.findall(item.evidence)
        if not citations:
            errors.append("Evidence has no checkable citation")
        for path, line, quote in citations:
            lines = files.get(path, "").splitlines()
            index = int(line) - 1
            if index < 0 or index >= len(lines) or quote not in lines[index]:
                errors.append(f"Invalid citation: {path}:L{line}")
            else:
                paths.add(path)
        if hasattr(item, "requirement_id"):
            valid_paths[item.requirement_id] = paths
    for identifier, rule in wanted.items():
        finding = actual.get(identifier)
        if finding is None:
            errors.append(f"Missing finding: {identifier}")
            continue
        if finding.status != rule["status"]:
            errors.append(f"{identifier}: expected {rule['status']}, got {finding.status}")
        required_paths = {rule["source"], *rule.get("evidence_paths", [])}
        if not required_paths <= valid_paths.get(identifier, set()):
            errors.append(f"{identifier}: missing source or implementation citations")
        if rule.get("clarification") and not (finding.clarification_question or "").strip():
            errors.append(f"{identifier}: missing clarification")
    if expected.get("no_risks") and result.engineering_risks:
        errors.append("Unexpected engineering risks")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Validate fixtures only; no model call")
    mode.add_argument("--results", type=Path, help="Score saved <case-name>.json responses")
    mode.add_argument("--live", action="store_true", help="Call the configured model (incurs API usage)")
    parser.add_argument("--model", help="Required for live evaluations")
    parser.add_argument("--output", type=Path, help="New directory for live responses and report")
    parser.add_argument("--case", action="append", help="Run named case; repeat to select several")
    args = parser.parse_args(argv)
    directories = sorted((ROOT / "evals" / "cases").glob("*/case.json"))
    known = {path.parent.name for path in directories}
    if args.case and set(args.case) - known:
        parser.error("Unknown case name")
    if args.live and (not args.model or not args.output):
        parser.error("--live requires --model and --output")
    client = None
    if args.live:
        from llm.agent_factory import create_llm_client
        client = create_llm_client("openai", args.model)
        args.output.mkdir(parents=True, exist_ok=False)
    reports = []
    for path in directories:
        name = path.parent.name
        if args.case and name not in args.case:
            continue
        try:
            case, files, expected = load_case(path.parent)
            errors = []
            if args.live:
                with contextlib.redirect_stdout(sys.stderr):
                    result = validate_repository(client, files["repo-tree.txt"], render(files, case.get("context", [])), render(files, [case["requirements"]]), render(files, case["implementation"]))
                (args.output / f"{name}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
                errors = score(result, files, expected)
            elif args.results:
                result = ValidationResult.model_validate_json((args.results / f"{name}.json").read_text(encoding="utf-8"))
                errors = score(result, files, expected)
            reports.append({"case": name, "passed": not errors, "errors": errors})
        except Exception as exc:
            reports.append({"case": name, "passed": False, "errors": [f"{type(exc).__name__}: {exc}"]})
    digest = hashlib.sha256()
    for path in [ROOT / "instructions/requirements-validator.md", ROOT / "docs/finding-contract.md"]:
        digest.update(path.read_bytes())
    report = {"mode": "fixtures" if args.check else "live" if args.live else "saved", "model": args.model, "instructions_sha256": digest.hexdigest(), "cases": reports}
    output = json.dumps(report, indent=2)
    print(output)
    if args.live:
        (args.output / "report.json").write_text(output, encoding="utf-8")
    return 0 if reports and all(item["passed"] for item in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
