"""Render a saved evaluation as a standalone HTML page without calling a model."""

import argparse
from html import escape
import json
from pathlib import Path


def text(value):
    return escape(str(value if value is not None else "—"), quote=True)


def category(error):
    message = error.lower()
    if "citation" in message:
        return "Citation"
    if "expected " in message and ", got " in message:
        return "Verdict mismatch"
    if "clarification" in message:
        return "Clarification"
    if any(word in message for word in ("missing finding", "requirement id", "non-unique", "duplicate finding")):
        return "Finding matching"
    if "risk" in message:
        return "Engineering risk"
    return "Execution / validation"


def finding_details(finding):
    title = finding.get("requirement_id", finding.get("risk", "Finding"))
    fields = ("status", "requirement", "risk", "evidence", "explanation",
              "severity", "confidence", "clarification_question")
    body = "".join(
        f"<dt>{text(field.replace('_', ' ').capitalize())}</dt><dd>{text(finding[field])}</dd>"
        for field in fields if field in finding
    )
    return f"<details><summary>{text(title)}</summary><dl>{body}</dl></details>"


def check_table(checks):
    if not checks:
        return "<p>No check comparisons available.</p>"
    rows = []
    for check in checks:
        status = "PASS" if check["passed"] else "FAIL"
        evidence = ("<details><summary>Full model evidence</summary><pre>"
                    + text(check["evidence"]) + "</pre></details>") if check.get("evidence") else ""
        def value(item):
            return text(json.dumps(item, ensure_ascii=False, indent=2) if isinstance(item, (list, dict)) else item)
        rows.append(f'<tr><td>{text(check["kind"])}<br>{text(check["target"])}</td>'
                    f'<td class="{status.lower()}">{status}</td>'
                    f'<td><pre>{value(check["expected"])}</pre></td>'
                    f'<td><pre>{value(check["actual"])}</pre>{evidence}</td></tr>')
    return ('<div class="table-wrap"><table><thead><tr><th>Check / finding</th>'
            '<th>Result</th><th>Expected</th><th>Actual</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></div>')


def render_report(report, responses, expectations, warnings=()):
    cases = report.get("cases", [])
    passed = sum(case.get("passed") is True for case in cases)
    rows = []
    sections = []
    for index, case in enumerate(cases):
        name = case["case"]
        success = case.get("passed") is True
        status = "PASS" if success else "FAIL"
        errors = "".join(
            f"<li><strong>{text(category(error))}:</strong> {text(error)}</li>"
            for error in case.get("errors", [])
        )
        reasons = f"<ul>{errors}</ul>" if errors else "No recorded errors"
        if errors:
            reasons += f'<p><a href="#checks-{index}">Compare expected and actual checks</a></p>'
        expected = expectations.get(name)
        expected_list = "<ul>" + "".join(
            f"<li>{text(rule['id'])}: {text(rule['status'])}"
            + (" (optional)" if rule.get("optional") else "") + "</li>"
            for rule in expected.get("findings", [])
        ) + "</ul>" if expected is not None else "Not available"
        response = responses.get(name, {})
        actual_list = "<ul>" + "".join(
            f"<li>{text(finding.get('requirement_id'))}: {text(finding.get('status'))}</li>"
            for finding in response.get("findings", [])
        ) + "</ul>" if response.get("findings") else "No findings available"
        rows.append(
            f'<tr><th scope="row"><a href="#case-{index}">{text(name)}</a></th>'
            f'<td class="{status.lower()}">{status}</td><td>{expected_list}</td>'
            f'<td>{actual_list}</td><td>{reasons}</td></tr>'
        )
        details = "".join(finding_details(item) for item in response.get("findings", []))
        risks = "".join(finding_details(item) for item in response.get("engineering_risks", []))
        checks = case.get("checks", [])
        failed_checks = [check for check in checks if not check["passed"]]
        passed_checks = [check for check in checks if check["passed"]]
        comparisons = (f'<h3 id="checks-{index}">Expected vs actual checks</h3>'
                       + ("<p>Comparisons reconstructed using current evaluator and fixture sources; saved score unchanged.</p>" if case.get("checks_reconstructed") else "")
                       + check_table(failed_checks)
                       + f'<details><summary>Passed checks ({len(passed_checks)})</summary>{check_table(passed_checks)}</details>')
        sections.append(
            f'<section id="case-{index}"><h2>{text(name)} · {status}</h2>'
            f'{comparisons}'
            f'<h3>Findings</h3>{details or "<p>No response findings available.</p>"}'
            f'<h3>Engineering risks</h3>{risks or "<p>None reported.</p>"}</section>'
        )
    notices = "".join(f"<li>{text(warning)}</li>" for warning in warnings)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Evaluation results</title>
<style>
body {{ font: 16px/1.5 system-ui, sans-serif; margin: 2rem auto; padding: 0 1.5rem; max-width: 1500px; color: #172b3a; background: #f7f9fb; }}
h1, h2 {{ line-height: 1.2; }} .summary {{ font-size: 1.35rem; font-weight: 650; }}
.pass {{ color: #146238; font-weight: bold; }} .fail {{ color: #a12020; font-weight: bold; }}
.table-wrap {{ overflow-x: auto; }} table {{ border-collapse: collapse; width: 100%; background: white; }}
th, td {{ padding: .8rem; border: 1px solid #cbd5df; text-align: left; vertical-align: top; overflow-wrap: anywhere; }}
thead {{ background: #e7edf3; }} ul {{ padding-left: 1.2rem; margin: 0; }}
section {{ margin-top: 2rem; padding: 1rem; background: white; border: 1px solid #cbd5df; border-radius: .4rem; }}
details {{ padding: .6rem; border-bottom: 1px solid #dce3e9; }} summary {{ cursor: pointer; font-weight: 600; }}
dt {{ font-weight: 600; margin-top: .65rem; }} dd {{ margin-left: 0; white-space: pre-wrap; overflow-wrap: anywhere; }}
.notice {{ background: #fff2ce; padding: 1rem; margin: 1rem 0; }} code {{ overflow-wrap: anywhere; }}
pre {{ white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; font-size: .9rem; }}
a {{ color: #1559a0; }} @media print {{ body {{ max-width: none; margin: 0; }} }}
</style></head><body>
<h1>Evaluation results</h1>
<p class="summary">{passed} passed · {len(cases) - passed} failed · {len(cases)} total</p>
<p>Model: <strong>{text(report.get('model'))}</strong> · Mode: {text(report.get('mode'))}</p>
<p>Run: <code>{text(report.get('output_directory'))}</code><br>
Instruction fingerprint: <code>{text(report.get('instructions_sha256'))}</code></p>
<p>Results are the saved automated scores, not human review verdicts. A failure can
reflect a scoring limitation; inspect the reasons and evidence before judging the model.</p>
{'<aside class="notice"><ul>' + notices + '</ul></aside>' if notices else ''}
<div class="table-wrap"><table><thead><tr><th>Case</th><th>Result</th><th>Expected verdicts</th><th>Actual verdicts</th><th>Failure reasons</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p>Expected and actual findings are listed separately because inferred findings may use different IDs.</p>
{''.join(sections)}
</body></html>"""


def write_report(directory):
    directory = Path(directory)
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    report.setdefault("output_directory", str(directory.resolve()))
    responses, expectations, warnings = {}, {}, []
    if report.get("rescoring_note"):
        warnings.append(report["rescoring_note"])
    for case in report["cases"]:
        name = case["case"]
        # Case names must be a single path component, including on Windows.
        if name in ("", ".", "..") or "/" in name or "\\" in name or ":" in name:
            raise ValueError(f"Invalid case name: {name!r}")
        try:
            response = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
            if not isinstance(response, dict) or any(
                not isinstance(response.get(field, []), list)
                or any(not isinstance(item, dict) for item in response.get(field, []))
                for field in ("findings", "engineering_risks")
            ):
                raise ValueError("Invalid response structure")
            responses[name] = response
        except (OSError, ValueError) as exc:
            warnings.append(f"{name}: response unavailable ({exc}). Saved score is unchanged.")
        if "expected" in case:
            expectations[name] = case["expected"]
        else:
            path = Path(__file__).parent / "cases" / name / "expected.json"
            try:
                expectations[name] = json.loads(path.read_text(encoding="utf-8"))
                warnings.append(f"{name}: expectations were not saved with this run; displaying current fixture expectations, which may differ from the original.")
            except (OSError, ValueError):
                warnings.append(f"{name}: expected verdicts unavailable.")
        if "checks" not in case and name in responses and expectations.get(name) is not None:
            try:
                from evals.run import ROOT, ValidationResult, load_case, score
                _, files, _ = load_case(ROOT / "evals" / "cases" / name)
                checks = []
                score(ValidationResult.model_validate(responses[name]), files, expectations[name], checks)
                case["checks"] = checks
                case["checks_reconstructed"] = True
            except (OSError, ValueError, KeyError, TypeError) as exc:
                warnings.append(f"{name}: check comparisons unavailable ({exc}).")
    output = directory / "report.html"
    output.write_text(render_report(report, responses, expectations, warnings), encoding="utf-8")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="Directory containing report.json and case responses")
    args = parser.parse_args(argv)
    try:
        output = write_report(args.run)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f"Cannot generate report: {exc}")
    print(f"HTML report: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
