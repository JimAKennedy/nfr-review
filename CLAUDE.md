# CLAUDE.md

## Project

- Python 3.11+ CLI tool for non-functional design reviews
- Uses: Pydantic v2, ruff, pytest, src-layout
- Run tests: `python -m pytest -n auto tests/`
- Lint: `ruff check src/ tests/`
- Format: `ruff format src/ tests/`

## Auto-Mode Code Quality

After writing or modifying any `.py` file, run `ruff format <file>` before finishing the
task. This prevents pre-commit hook reformatting from creating dirty working-tree state
after git commits. This applies to all agents and subagents — format is not a git command
and is safe to run during task execution.

## Branch Discipline

One branch per milestone/PR. Never stack multiple milestones on a single branch — squash-
merge of one milestone causes all remaining commits to conflict on rebase. After any rebase
with conflict resolution, run `pre-commit run --all-files` before pushing.

## Repo Role

- `TheCharlieKennedy/nfr-review` (this repo) — dev. All implementation work happens here.
- `JimAKennedy/nfr-review` — prod. PRs are raised there only when work is complete and to standard.
- Never push directly to JimAKennedy/nfr-review.

## Scope Rules

- All changes must be within scope of the requirements spec (`docs/internal/nfr-PLAN.md` §Requirements Breakdown).
- All changes must account for the enterprise use case: no hard dependency on `nfr-utils[llm]`, `nfr-utils[diagrams]`, `nfr-utils[scancode]` or any LLM SDK in `nfr-core` or any `nfr-lang-*` pack.
- Band 2 (LLM-augmented) rule paths must gracefully skip via `LlmClient.available` — never raise, never produce a false PASS.
- Do not add features, collectors, rules or outputs not covered by the reqs. If something seems missing, flag it — do not implement it.

## Package Architecture

`nfr-review` is a single package. All language support, output formats, collectors, and rules ship in core. The only opt-in extras are:

- `[llm]` — LLM-augmented Band 2 rules, requires API key
- `[otel]` — OpenTelemetry tracing instrumentation
- `[scancode]` — Licence scanning via scancode-toolkit

Do not move language grammars, diagrams, PDF, or monitor into optional extras.

## Test Fix Discipline

Tests are a contract, not an obstacle. Only change a test when the production code
intentionally changed what the test was verifying — a renamed module, a changed API, a
deliberate behaviour shift. Legitimate reasons to update a test: import renames, API
signature changes, environment-specific adapters (e.g. `mix_stderr=False` on Windows),
or skip guards for optional grammars.

Never modify a test fixture, alter expected values, or weaken an assertion to make a
test pass. If a test is failing and none of the above reasons apply, the fix belongs in
the production code, not the test.

## Planning Docs

- Working plans, agentic dev docs: `docs/internal/` (gitignored, do not commit).
- Do not create planning documents in the repo root or outside `docs/internal/`.
