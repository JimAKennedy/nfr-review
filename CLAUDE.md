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

## Modularisation Plan

The package split is documented in `docs/internal/nfr-PLAN.md` §Package Architecture. Summary:

- `nfr-core` — engine, contracts, CLI, infra/platform collectors and rules, hygiene, design change, arch analysis, output renderers, Python/HCL/Dockerfile lang support (no optional deps).
- `nfr-utils[llm|monitor|diagrams|pdf|scancode]` — optional extras, each independently installable.
- `nfr-lang-<name>` — one entry-point package per additive language (Java, Go, Rust, C#, Node.js, C++, Gatling); self-registers into nfr-core registries on import. Python stays in core.
- `nfr-review` meta-package — `nfr-core` + all lang packs (unchanged install UX for existing users).
- `nfr-review[full]` — everything.

When implementing the split, do not move files between packages without updating `_payload_registry.py`, `detect.py`, `collectors/__init__.py`, `rules/__init__.py` and the entry-point declarations in `pyproject.toml`.

## Planning Docs

- Working plans, agentic dev docs: `docs/internal/` (gitignored, do not commit).
- Formal docs, client comms: `C:\Users\charl\Documents\Business\` (separate location, not this repo).
- Do not create planning documents in the repo root or outside `docs/internal/`.
