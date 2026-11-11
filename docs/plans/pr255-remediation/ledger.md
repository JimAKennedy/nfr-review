---
class: gated
---

# PR #255 Remediation Ledger

Status: current (2026-11-10)

**Source:** docs/plans/pr255-remediation/input.md

Every finding from the pre-merge review of PR #255 ("fix: v0.5 cross-platform
fixes, typst PDF migration, CI hardening", fork `TheCharlieKennedy/nfr-review:main`)
is one row below. The PR is fixed in place on the local branch `pr255-fixes`;
the owner decides when that branch is pushed to the fork.

Reconciled against `pr255-fixes` at `7d87e67` on 2026-11-10: 7 items already
fixed (S01), 1 deferred by the owner (S12), 1 partly satisfied (P3 — the CLI
disclosure already goes through `LlmConfig.resolve()`; the arch orchestrator
does not), 22 outstanding. Two counts in the input had drifted and are
corrected in the rows: W2 is 18 assertions across 12 test files, and only two
site pages (output formats, arch) still name weasyprint.

## Milestone M001 — PR #255 merge-ready

**Vision:** PR #255 can be merged into main: every finding from its pre-merge
review is fixed and locked by a test or deliberately deferred with a recorded
reason, and the regression suite, coverage and container E2E gate the result.
**Branch:** pr255-fixes
**Status:** in-progress
**Demo:** `gate` and `container-e2e` pass on the head of `pr255-fixes`, and
every slice below is `done` or `accepted`.

### Slice M001/S01 — Landed review fixes

**Plan:** —  <!-- ledger-ok: landed on pr255-fixes before this ledger existed; the commits are the plan of record -->
**Validation:** format, unit, regression
**Evidence:** evidence/M001-S01.md
**Status:** done

**Definition of Done**

- [x] The nightly workflow that runs the regression suite exists on the branch
- [x] Java, Spring Boot and script-only Python are detected in subdirectories, with refreshed snapshots
- [x] Typst markup in PDF output is escaped and compilation is confined to a temp-dir root
- [x] `create_llm_client` honours `LlmConfig` defaults, `NFR_LLM_*` overrides and `.env`
- [x] The executive summary sends its full payload to the LLM
- [x] Coverage is measured over all shipped code and LLM-rule tests run in test-core
- [x] Fork-only changes to `CLAUDE.md`, `.gitignore`, `docs/internal/*`, fixture line endings and `rules.json` are reverted

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| A1 | PR deleted the nightly workflow, the only place regression runs | `.github/workflows/nfr-review-nightly.yml` | commit `162f2e0` restores the file | `done` |
| A2 | required_tech gate dropped Java findings on monorepos; script-only Python undetected | `src/nfr_review/detect.py` | commit `bb39ff0`; regression snapshots refreshed in the same commit | `done` |
| A3 | Unescaped Typst markup, mermaid fallback injection, unsandboxed compile | `output/pdf.py`, `arch_report_render.py` | `tests/test_pdf_typst_safety.py` | `done` |
| A4 | LLM client ignored `LlmConfig` defaults, `NFR_LLM_*` and `.env` | `llm_integration.py` | `tests/test_llm_config.py` | `done` |
| A5 | Executive-summary payload over 8 KB replaced with `[]` | `output/summarize.py` | commit `f307a2a` | `done` |
| A6 | ~40 coverage omits and test-core `--ignore`s hid untested code | `.github/workflows/ci.yml`, `pyproject.toml` | commit `828beaf`; 91% over 27,047 statements | `done` |
| A7 | Fork-specific edits to upstream files, CRLF fixtures, stale `rules.json` | `CLAUDE.md`, `.gitignore`, `docs/internal/`, fixtures, `rules.json` | commit `67cfc95` | `done` |

### Slice M001/S13 — Regression baseline current

**Plan:** M001-S13-plan.md
**Validation:** regression, format
**Evidence:** evidence/M001-S13.md
**Status:** done

**Definition of Done**

- [x] The regression suite passes on the branch before any other slice's change lands
- [x] The only snapshot lines that change are time-based `dep-freshness` findings for `gin` and `httpx`

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| X1 | `gin` (+2) and `httpx` (+1) snapshots fail on time-based `dep-freshness` findings unrelated to PR #255 (found while planning, 2026-11-10) | `tests/regression/snapshots/` | `regression` → 0 failed; snapshot diff contains only `dep-freshness` lines | `done` |

### Slice M001/S02 — Rust collector correctness

**Depends:** M001/S13
**Plan:** M001-S02-plan.md
**Validation:** format, unit, regression, gate
**Evidence:** evidence/M001-S02.md
**Status:** done

**Definition of Done**

- [x] An io `.write(..)`/`.read(..)` with arguments is not reported as a lock call
- [x] A blocking call inside a closure (e.g. `spawn_blocking(move || …)`) in an async fn is not reported, and one inside an `async {}` block in a sync fn is
- [x] Test-code suppression matches `#[test]`, `#[cfg(test)]` and a `mod tests` name exactly, so `mod attestation` is still scanned
- [x] Imported paths (`use reqwest::Client; Client::new()`, imported `spawn`, `tokio::task::spawn`) are recognised
- [x] Unwrap summaries are single-line and bounded in length
- [x] `rust-mutex-lock-unwrap` does not report calls in test code
- [x] Workspace-inherited, target-cfg and renamed Cargo dependencies resolve to the right crate, and nothing under `target/` is parsed
- [x] The three truncated Rust rule descriptions read as complete sentences
- [x] Each outcome above is locked by a named test case

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| R1 | Rust AST false positives/negatives: lock-method arity, closure/async-block boundary, substring test matching, imported paths, async-block sleep, unbounded unwrap summary, mutex rule ignores `in_test` | `collectors/rust_ast.py`, `rules/rust_unwrap_expect.py`, mutex-lock rule | One case per sub-item in `tests/test_rust_ast_collector.py` / `tests/test_rust_rules.py`, each feeding the snippet from the input | `done` |
| R2 | Cargo.toml parsing misses workspace inheritance, target-cfg tables, renamed deps; rglob enters `target/`; `read_text` has no encoding | `collectors/rust_deps.py` | Cases in `tests/test_rust_deps_collector.py` with a workspace fixture, a `[target.'cfg(..)'.dependencies]` table, a `package =` rename, and a `target/` decoy | `done` |
| R3 | Rust rule descriptions truncated mid-sentence | `rule_metadata.py` | Case in `tests/test_rule_metadata.py` asserting no description ends in a dangling word before the full stop; `rules.json` regenerated | `done` |

### Slice M001/S03 — Grammar loading and its tests

**Depends:** M001/S13
**Plan:** M001-S03-plan.md
**Validation:** format, unit, gate
**Evidence:** evidence/M001-S03.md
**Status:** done

**Definition of Done**

- [x] On a platform without a 0.2 wheel, `tree-sitter-dockerfile` is not installed at all rather than as a placeholder, and aarch64 stays excluded
- [x] Only a failing `getattr(mod, func_name)` is treated as "grammar not installed"; an `AttributeError` raised elsewhere propagates
- [x] Repeated runs on the same collector instance report each grammar warning once
- [x] The tests named "Raises…" assert the recorded warning, and the `BaseASTCollector` warning path is asserted

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| G1 | `tree-sitter-dockerfile>=0.0.0a1` installs an empty placeholder on platforms lacking a 0.2.0 wheel | `pyproject.toml` | Marker matches the platforms with published 0.2 wheels; `pip install --dry-run` resolution recorded in evidence | `done` |
| G2 | `AttributeError` added to the grammar-missing catch hides real bugs | `collectors/ast_common.py`, `collectors/dockerfile.py` | Case in `tests/test_missing_grammar_warning.py` raising `AttributeError` from the parser constructor asserts it propagates | `done` |
| G3 | `grammar_warnings` accumulate on singleton collectors across runs | `collectors/ast_common.py`, `collectors/dockerfile.py`, `engine.py` | Case running the engine twice asserts one warning per run | `done` |
| T1 | Missing-grammar tests assert only `== []`; base-class warning never asserted | `tests/test_missing_grammar_warning.py` | The rewritten cases assert `grammar_warnings` content | `done` |

### Slice M001/S04 — Graphify opt-in and out of tree

**Depends:** M001/S13
**Plan:** M001-S04-plan.md
**Validation:** format, unit, regression, container-e2e, gate
**Evidence:** evidence/M001-S04.md
**Status:** done

**Definition of Done**

- [x] A scan with default config never invokes the `graphify` executable
- [x] With graphify enabled, its output is written to a temp dir and nothing is written into the scanned repo
- [x] A stale `graph.json` in the scanned repo is not reused
- [x] The Container E2E job fails when any collector crashes, and passes on the `:ro` fixture mount

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| GR1 | Graphify runs on every scan (up to 2×300 s), writes `graphify-out/` into the scanned repo, reuses stale output, and crashes silently on a `:ro` mount | `collectors/graphify.py`, `config.py` (`GraphifyConfig`), `.github/workflows/ci.yml` | Cases in `tests/test_graphify_collector.py` asserting no subprocess call by default and temp-dir output when enabled; `container-e2e` exits non-zero on an injected collector crash | `done` |

### Slice M001/S05 — Windows locator stability

**Depends:** M001/S13
**Plan:** M001-S05-plan.md
**Validation:** format, unit, regression, gate
**Evidence:** evidence/M001-S05.md
**Status:** done

**Definition of Done**

- [x] A baseline and legacy issue markers recorded with `\` locators match the same findings after the forward-slash change
- [x] No test normalises the locator it is asserting on
- [x] A test feeds a Windows-style relative path and asserts the raw `/` locator

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| W1 | Forward-slash locators change fingerprints for existing Windows baselines and issue markers | `baseline.py` (`load_baseline`), `issues.py` (`_finding_key`) | Cases in `tests/test_baseline.py` and `tests/test_issues.py` loading `\`-locator records and asserting a match | `done` |
| W2 | 18 assertions across 12 test files apply `.replace("\\", "/")` to the actual value | the 12 test modules (`test_*_deps_collector.py`, `test_path_filter*.py`, …) | `grep` for that pattern over `tests/` returns no assertion-side hits; new Windows-path case passes | `done` |

### Slice M001/S06 — Report fidelity and LLM payloads

**Depends:** M001/S13
**Plan:** M001-S06-plan.md
**Validation:** format, unit, gate
**Evidence:** evidence/M001-S06.md
**Status:** done

**Definition of Done**

- [x] The Typst PDF contains the Scoring Methodology appendix, including the LLM usage disclosure, that its body text refers to
- [x] Architecture diagrams in the PDF render at scale 4 / width 2400
- [x] The arch report's disclosed model equals the model the LLM client resolved from config
- [x] An architecture profile over 8 KB still reaches the market-comparison LLM call

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| P1 | Methodology/LLM-usage appendix dropped from Typst PDF; `llm_info` unused | `output/pdf.py` | Case in `tests/test_pdf.py` asserting the appendix heading and model name in the generated Typst source | `done` |
| P2 | Arch diagram `scale=4`, `width=2400` render lost in the typst migration | `output/pdf.py` (`_render_mermaid_for_typst`) | Case in `tests/test_arch_report_render.py` asserting the render call's scale and width | `done` |
| P3 | Arch report discloses `NFR_LLM_MODEL` or a hard-coded default instead of the resolved config model (CLI half already correct) | `arch_orchestrator.py` | Case setting the model in config only and asserting `ArchReportMetadata.llm_model` | `done` |
| L1 | Market comparison wraps the profile as one bundle item under an 8 KB cap, so an oversized profile becomes `[]` (also on main) | `arch_market_comparison.py` | Case in `tests/test_arch_market_comparison.py` with a >8 KB profile asserting a non-empty payload | `done` |

### Slice M001/S07 — Scan scope

**Depends:** M001/S13
**Plan:** M001-S07-plan.md
**Validation:** format, unit, regression, gate
**Evidence:** evidence/M001-S07.md
**Status:** done

**Definition of Done**

- [x] Config-integration discovery honours the configured test-path exclusion
- [x] Detection does not descend into `node_modules`, `target` or other excluded directories

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| C1 | `discover_config_integrations` gained `exclude_test_paths`, but its only caller never passes it | `arch_integrations.py` | Case in `tests/test_arch_integrations.py` with exclusion off, asserting a test-path integration is discovered | `done` |
| C2 | Detection `rglob`s traverse `node_modules`/`target` before exclusion | `detect.py` (`_safe_rglob`) | Case in `tests/test_detect.py` asserting excluded directories are never listed | `done` |

### Slice M001/S08 — Privacy SCM-username filter

**Depends:** M001/S13
**Plan:** M001-S08-plan.md
**Validation:** format, unit, gate
**Evidence:** evidence/M001-S08.md
**Status:** done

**Definition of Done**

- [x] `github@acme-corp.com` and `deploy@acme.com` in prose are reported
- [x] `git@github.com:org/repo` in an SSH remote is not reported
- [x] Both are locked by tests

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| PV1 | SCM-username suppression is domain-agnostic and untested | `hygiene/collectors/privacy.py` | Cases in `tests/test_hygiene_privacy.py` for both directions | `done` |

### Slice M001/S09 — Real LLM isolation in tests

**Depends:** M001/S13
**Plan:** M001-S09-plan.md
**Validation:** format, unit, gate
**Evidence:** evidence/M001-S09.md
**Status:** done

**Definition of Done**

- [x] No test patches `_AI_TOOLING_AVAILABLE`; tests needing a fake or absent LLM patch `create_llm_client`
- [x] The suite passes with `ANTHROPIC_API_KEY` set in the environment

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| T2 | No-op `_AI_TOOLING_AVAILABLE` patches; the unavailable-client test fails when `ANTHROPIC_API_KEY` is set | `tests/test_baseline.py`, `tests/test_pilot_validation.py`, `tests/test_llm_client.py` | `grep _AI_TOOLING_AVAILABLE tests/` is empty; `unit` run with a dummy `ANTHROPIC_API_KEY` recorded in evidence | `done` |

### Slice M001/S10 — Lockfiles, base image and CI hygiene

**Depends:** M001/S03, M001/S04, M001/S13
**Plan:** M001-S10-plan.md
**Validation:** format, unit, container-e2e, gate
**Evidence:** evidence/M001-S10.md
**Status:** done

**Definition of Done**

- [x] `requirements.txt` and `requirements-dev.txt` are pip-compiled from the final `pyproject.toml` and install cleanly
- [x] `.trivyignore` has no zlib entries and the image scan reports neither CVE
- [x] CI again has the "Test summary" step and the `scanners: vuln` explanation, and test-llm coverage is measured and uploaded as its own report

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| H1 | Lockfiles lack typst, graphviz, graphifyy, networkx, aiohttp; `tree-sitter==0.26.0` conflicts with the graphifyy cap; `anthropic` still in dev | `requirements.txt`, `requirements-dev.txt` | `pip-compile` rerun produces no diff; `pip install -r` into a fresh venv succeeds | `done` |
| H4 | zlib1g CVE-2026-76844 and CVE-2026-85091 ignored globally with no expiry | `Dockerfile` runtime stage, `.trivyignore` | Trivy image scan with the entries removed reports neither CVE | `done` |
| H5 | "Test summary" step and `scanners: vuln` comment removed; test-llm runs without coverage | `.github/workflows/ci.yml` | Workflow diff against main for the restored step and comment; test-llm job uses `--cov --cov-append` | `done` |

The base-image digest pin in H4 is a "consider" in the input; the plan decides
it.

### Slice M001/S11 — Docs and CHANGELOG

**Depends:** M001/S04, M001/S13
**Plan:** M001-S11-plan.md
**Validation:** format, discipline, gate
**Evidence:** evidence/M001-S11.md
**Status:** in-progress

**Definition of Done**

- [ ] No user-facing doc mentions weasyprint, the removed extras, or openai as a core dependency
- [ ] Historical CHANGELOG entries (0.3.1, 0.2.0, 0.1.x) match main
- [ ] `[Unreleased]` records the typst migration, Rust support, extras consolidation, the detection/required_tech change, graphify becoming opt-in, and the breaking LLM refactor
- [ ] The package version agrees with the CHANGELOG, and the PR-title correction is recorded as an owner action in the milestone report

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| H2 | Docs describe weasyprint or removed extras; README, CHANGELOG and dependencies doc claim openai is core | `ARCHITECTURE.md`, `docs/dependencies.md`, `docs/install.md`, `scripts/setup-all.sh`, `README.md`, site pages (output formats, arch, first scan, faq, advanced) | `grep -ri weasyprint` and `grep -i "openai.*core"` over those paths return nothing | `done` |
| H3 | Historical CHANGELOG entries rewritten; `[Unreleased]` empty; version 0.3.1 vs "v0.5" in the PR title | `CHANGELOG.md`, `pyproject.toml` | `git diff main -- CHANGELOG.md` touches only `[Unreleased]`; version decision recorded in the plan | `open` |

### Slice M001/S12 — ai-tooling packaging (deferred)

**Plan:** —  <!-- ledger-ok: deliberately not actioned in this programme; owner decision due 2026-11-11, re-run /jk:assess afterwards -->
**Validation:** discipline
**Evidence:** evidence/M001-S12.md
**Status:** accepted

**Definition of Done**

- [ ] The owner's naming and publishing decision for ai-tooling is recorded and this slice is re-assessed

| ID | Item | Lands in | Verification | Status |
|---|---|---|---|---|
| D1 | `[llm]` extra points at `file:///${PROJECT_ROOT}/../ai-tooling` and cannot be installed or published; PyPI name taken. Dependants: working `[llm]` extra, openai support, Docker LLM extras, `action.yml` `[llm]` path, CI `ai-tooling @ git+…` pins, ai-tooling licence, `config.py` no-op `ProviderConfig` import block | `pyproject.toml`, `Dockerfile`, `action.yml`, `.github/workflows/ci.yml`, `config.py` | Owner decision recorded in the input document | `accepted` |

## Sequencing

S10 depends on S03 and S04 because it pip-compiles the lockfiles from
`pyproject.toml`, which S03 changes (the `tree-sitter-dockerfile` pin) and S04
may change (whether `graphifyy` stays a core dependency); compiling before both
land means compiling twice. Every slice depends on S13 because each owes
`regression` or `gate`, and both are red on the unchanged tree until the
`gin`/`httpx` snapshot drift is refreshed. S11 depends on S04 because the docs and
`[Unreleased]` must describe graphify as opt-in. Every other slice touches
disjoint files and can land in any order.
