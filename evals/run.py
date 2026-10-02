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
        for line in finding.get("match_source_lines", []):
            if not isinstance(line, int) or not 1 <= line <= len(files[finding["source"]].splitlines()):
                raise ValueError("Source matching line is outside supplied evidence")
    for path in [case["requirements"], *case.get("context", []), *case["implementation"]]:
        if path not in files:
            raise ValueError(f"Missing input: {path}")
    return case, files, expected


def render(files, paths):
    return "\n\n".join(
        f"FILE: {path}\n" + "\n".join(f"L{i}: {line}" for i, line in enumerate(files[path].splitlines(), 1))
        for path in paths
    )


def score(result, files, expected, checks=None):
    errors = []
    def check(kind, target, wanted, observed, passed, error, evidence=None):
        if checks is not None:
            checks.append({"kind": kind, "target": target, "expected": wanted,
                           "actual": observed, "passed": bool(passed), "evidence": evidence})
        if not passed:
            errors.append(error)

    actual = {}
    for finding in result.findings:
        check("Unique ID", finding.requirement_id, "One finding per ID",
              "Duplicate" if finding.requirement_id in actual else "Unique",
              finding.requirement_id not in actual, f"Duplicate finding: {finding.requirement_id}")
        actual[finding.requirement_id] = finding
    valid_paths = {}
    valid_lines = {}
    for item in [*result.findings, *result.engineering_risks]:
        paths = set()
        locations = set()
        citations = CITATION.findall(item.evidence)
        target = getattr(item, "requirement_id", getattr(item, "risk", "Evidence"))
        check("Citation presence", target, "At least one parseable citation",
              f"{len(citations)} parsed", bool(citations), "Evidence has no checkable citation", item.evidence)
        for path, line, quote in citations:
            lines = files.get(path, "").splitlines()
            index = int(line) - 1
            source_line = lines[index] if 0 <= index < len(lines) else None
            valid = source_line is not None and quote in source_line
            check("Citation excerpt", f"{target} / {path}:L{line}",
                  "An exact excerpt of this source line:\n" + source_line if source_line is not None else "An existing file and line (source line not found)",
                  "Parsed excerpt:\n" + quote, valid, f"Invalid citation: {path}:L{line}", item.evidence)
            if valid:
                paths.add(path)
                locations.add((path, int(line)))
        if hasattr(item, "requirement_id"):
            valid_paths[item.requirement_id] = paths
            valid_lines[item.requirement_id] = locations
    matched = set()
    # Exact source IDs are reserved for their own rules. Inferred findings instead
    # match all cited premises, independently of the model's generated label.
    explicit_ids = {rule["id"] for rule in expected["findings"] if not rule.get("match_source_lines")}
    for rule in expected["findings"]:
        label = rule["id"]
        if rule.get("match_source_lines"):
            premises = {(rule["source"], line) for line in rule["match_source_lines"]}
            candidates = [identifier for identifier in actual
                          if identifier not in explicit_ids
                          and premises <= valid_lines.get(identifier, set())]
        else:
            candidates = [label] if label in actual else []
        match_description = (f"Citations to {rule['source']} lines {rule['match_source_lines']}"
                             if rule.get("match_source_lines") else f"ID {label}")
        check("Finding coverage", label,
              ("Optional: " if rule.get("optional") else "Required: ") + match_description,
              candidates, bool(candidates) or rule.get("optional", False), f"Missing finding: {label}")
        if not candidates:
            continue
        unique = len(candidates) == 1 and candidates[0] not in matched
        check("Finding matching", label, "Exactly one previously unmatched finding",
              candidates, unique, f"Non-unique finding match: {label}")
        if not unique:
            continue
        identifier = candidates[0]
        matched.add(identifier)
        finding = actual[identifier]
        check("Verdict", identifier, rule["status"], finding.status,
              finding.status == rule["status"], f"{identifier}: expected {rule['status']}, got {finding.status}")
        required_paths = {rule["source"], *rule.get("evidence_paths", [])}
        observed_paths = valid_paths.get(identifier, set())
        check("Evidence sources", identifier, sorted(required_paths), sorted(observed_paths),
              required_paths <= observed_paths, f"{identifier}: missing source or implementation citations")
        if rule.get("clarification"):
            check("Clarification", identifier, "A nonempty clarification question",
                  finding.clarification_question, bool((finding.clarification_question or "").strip()),
                  f"{identifier}: missing clarification")
    for identifier in sorted(actual.keys() - matched):
        check("Unexpected finding", identifier, "A finding matching one of the fixture rules",
              identifier, False, f"Unsupported requirement ID: {identifier}")
    if expected.get("no_risks"):
        check("Engineering risks", "case", "No engineering risks",
              [risk.risk for risk in result.engineering_risks], not result.engineering_risks,
              "Unexpected engineering risks")
    return errors


def create_run_directory(requested):
    """Reserve a fresh directory atomically, preserving previous runs."""
    candidate = requested
    suffix = 2
    while True:
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            candidate = requested.with_name(f"{requested.name}-{suffix}")
            suffix += 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Validate fixtures only; no model call")
    mode.add_argument("--results", type=Path, help="Score saved <case-name>.json responses")
    mode.add_argument("--live", action="store_true", help="Call the configured model (incurs API usage)")
    parser.add_argument("--model", help="Required for live evaluations")
    parser.add_argument("--output", type=Path, help="Live output directory; append -2, -3, etc. if it exists")
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
        try:
            args.output = create_run_directory(args.output)
        except (OSError, ValueError) as exc:
            parser.error(f"Cannot create output directory: {exc}")
        print(f"Saving evaluation results to: {args.output.resolve()}", file=sys.stderr)
    reports = []
    for path in directories:
        name = path.parent.name
        if args.case and name not in args.case:
            continue
        expected = None
        checks = []
        try:
            case, files, expected = load_case(path.parent)
            errors = []
            if args.live:
                with contextlib.redirect_stdout(sys.stderr):
                    result = validate_repository(client, files["repo-tree.txt"], render(files, case.get("context", [])), render(files, [case["requirements"]]), render(files, case["implementation"]))
                (args.output / f"{name}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
                errors = score(result, files, expected, checks)
            elif args.results:
                result = ValidationResult.model_validate_json((args.results / f"{name}.json").read_text(encoding="utf-8"))
                errors = score(result, files, expected, checks)
            reports.append({"case": name, "passed": not errors, "errors": errors, "expected": expected, "checks": checks})
        except Exception as exc:
            checks.append({"kind": "Execution / validation", "target": name, "expected": "Readable inputs and a response satisfying the finding schema", "actual": f"{type(exc).__name__}: {exc}", "passed": False})
            reports.append({"case": name, "passed": False, "errors": [f"{type(exc).__name__}: {exc}"], "expected": expected, "checks": checks})
    digest = hashlib.sha256()
    for path in [ROOT / "instructions/requirements-validator.md", ROOT / "docs/finding-contract.md"]:
        digest.update(path.read_bytes())
    report = {"mode": "fixtures" if args.check else "live" if args.live else "saved", "model": args.model, "instructions_sha256": digest.hexdigest(), "cases": reports}
    if args.live:
        report["output_directory"] = str(args.output.resolve())
    output = json.dumps(report, indent=2)
    print(output)
    if args.live:
        (args.output / "report.json").write_text(output, encoding="utf-8")
        from evals.report import write_report
        html_path = write_report(args.output)
        print(f"HTML report: {html_path.resolve()}", file=sys.stderr)
    return 0 if reports and all(item["passed"] for item in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
