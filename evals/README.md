# Evaluating the validator

The versioned [finding contract](../docs/finding-contract.md) is loaded by the
production validator as well as the evaluation runner. Cases cover static
satisfaction, violations, partial compliance, ambiguity, missing runtime evidence,
conflicting context, embedded instructions, unnumbered constraints, and deployment attribution.

From the repository root, with the README dependencies installed:

```powershell
python -m unittest discover -s tests -v
python -m evals.run --check
```

These commands are offline. Fixture validation checks input consistency; tests
exercise scoring failures and the real validator with a fake client. Neither
command measures an LLM's accuracy.

To evaluate a model explicitly (requires OPENAI_API_KEY and incurs API usage):

```powershell
python -m evals.run --live --model <model-name> --output .eval-results/run-001
```

You can repeat the same command. If the requested output directory already exists,
the runner creates a sibling with a numeric suffix: `run-001-2`, `run-001-3`, etc.
Existing files and directories are preserved, including partial runs. The actual
output path is printed before evaluation and included in the JSON report as
`output_directory`. Use that path with `--results` to score the new run.

Keep earlier runs while comparing prompt, model, or fixture changes; remove unwanted
run directories manually after review. There is no automatic deletion.
The runner saves each response plus a
report with the model and instruction fingerprint. Repeat runs to assess variance.
Pass `--case satisfied` to select one case; repeat `--case` for multiple cases.
To score responses saved from an earlier run without calling a model:

```powershell
python -m evals.run --results .eval-results/run-001
```

Exit status is zero when all selected cases pass, one on evaluation/fixture errors,
and two on invalid command arguments. Missing responses fail, rather than skip.
Live response logs go to stderr; the report is JSON on stdout.

## Case format and scoring

Each case has case.json and expected.json. A manifest maps repository-relative
paths to inline text or fixture files, preserving the simulated repository layout.
The inventory is supplied as repo-tree.txt. Inputs are labelled with paths and
line numbers before validation. Expected findings specify exact IDs and verdicts,
source paths, required implementation evidence paths, and optional clarification.
Unnumbered constraints use path-and-line IDs as defined in the contract.
For deductions, `match_source_lines` lists every required premise in `source`.
Such a rule's `id` is an evaluator label, not a required model-generated ID:
matching uses valid citations to all premise lines instead. A single response
finding must match uniquely and satisfy the expected verdict and evidence paths.
`optional: true` permits additional recognized context findings without requiring
them; their verdicts and citations are still checked. Unrecognized extra findings
remain failures requiring review, not automatic proof of hallucination.

The original deployment fixture retains its three informal scope statements.
Companion cases cover a matching root layout and an unspecified publishing root,
where declaring a nested entry point defective would require an unsupported
assumption. Review deductions for a complete logical chain, not merely citations.

The scorer rejects missing, duplicate, or unexpected requirement IDs; incorrect
verdicts; absent required clarification; and missing or invalid citations. Quoted
excerpts must occur at the cited line. Simple cases forbid engineering risks.
No exact prose matching or model-based judge is used.

After changing input fixtures or instructions, run a new live evaluation in a new
directory. Saved responses describe the old inputs; rescoring them against modified
fixtures does not evaluate the new behavior. Keep earlier runs for comparison.

These checks detect invented requirement IDs and fabricated citations, but do not
prove that an explanation follows logically from a real quote. Human review is
still required for semantic relevance, unsupported claims within prose, missing
evidence explanations, risk quality, and severity calibration. The deployment case
allows risks without requiring a particular wording or count.
