# PR #255 remediation — remaining findings (input for /jk:assess)

Status: open (2026-11-10)

Source: pre-merge review of PR #255 ("fix: v0.5 cross-platform fixes, typst PDF
migration, CI hardening", fork `TheCharlieKennedy/nfr-review:main`). The review
used four independent agents plus a local verification of each serious claim.
Line references below were observed during that review at PR head `acff057`.
Re-verify each one before changing code.

## Already fixed (branch `pr255-fixes`, local, not pushed)

1. Reverted the PR's deletion of `.github/workflows/nfr-review-nightly.yml`.
   That workflow is the only place the regression suite runs.
2. `detect.py`: Java and Spring Boot are detected in subdirectories, and
   script-only Python is detected. The required_tech gate had been silently
   dropping all Java findings on monorepos. Regression snapshots refreshed.
3. `output/pdf.py` and `arch_report_render.py`:
   - All Typst markup is escaped.
   - `#raw()` is used for verbatim spans.
   - The mermaid fallback injection is fixed.
   - Compilation is sandboxed in a temp-dir root.
   - Added `tests/test_pdf_typst_safety.py`.
4. `llm_integration.create_llm_client`:
   - Always applies `LlmConfig().resolve()`, so `NFR_LLM_*` overrides and the
     sonnet default hold.
   - `.env` loading is restored.
   - Added `tests/test_llm_config.py`.
5. `output/summarize.py`: the full payload is sent. Previously `run_analysis`'s
   8 KB cap replaced it with `[]`.
6. CI: dropped the ~40 coverage omits and the test-core `--ignore`s for the
   LLM-rule tests. Coverage is 91% over 27,047 statements.
7. Restored upstream `CLAUDE.md`, `.gitignore` and `docs/internal/*`. Converted
   the CRLF fixtures back to LF. Regenerated `rules.json` via `list-rules`.

Verification at that point:
- 6242 passed / 5 skipped / 0 failed.
- All regression tests passed.
- ruff, mypy and `pre-commit run --all-files` were clean.

## Deferred — do NOT action in this programme

- **D1. ai-tooling packaging.** The `[llm]` extra is
  `ai-tooling @ file:///${PROJECT_ROOT}/../ai-tooling` (pyproject.toml). It
  cannot be installed or published. The PyPI name `ai-tooling` is taken by an
  unrelated project.
  - The owner will decide on naming/publishing ai-tooling on 2026-11-11.
  - Dependent items wait on D1: a working `[llm]` extra; restoring `openai`
    support; LLM extras in the Docker image (`Dockerfile:17` installs only `.`);
    the action.yml `[llm]` install path (`action.yml:143`); pinning the CI
    `ai-tooling @ git+…` installs (`ci.yml:52`, `ci.yml:166`); the ai-tooling
    license.
  - Also gated on D1: the no-op `try: from ai_tooling.config import
    ProviderConfig … __all__ = list(__all__)` block in `config.py`.

## Remaining items to fix

### Rust language support
- **R1. False positives and negatives in `collectors/rust_ast.py`:**
  - `_LOCK_METHODS` matches any `.read()` or `.write()`, including io calls
    like `out.write(b"x").unwrap()`. Require zero arguments.
  - `_enclosing_async_function` walks through closures, so
    `spawn_blocking(move || …)` is flagged. Stop at `closure_expression`, and
    treat `async_block` as async.
  - `_is_inside_test` uses substring matching, so `mod attestation`, `latest`
    and the like are suppressed. Match `#[test]` / `#[cfg(test)]` / a
    `mod tests` name exactly.
  - Imported paths are missed: `use reqwest::Client; Client::new()`,
    `tokio::task::spawn`, and an imported `spawn`.
  - `std::thread::sleep` inside an `async {}` block in a sync fn is missed.
  - The unwrap summary embeds the full receiver text (multi-line or very long).
    Truncate it.
  - `rust-mutex-lock-unwrap` ignores `in_test`.
- **R2. `collectors/rust_deps.py` Cargo.toml parsing:**
  - Workspace inheritance (`dep = { workspace = true }` plus
    `[workspace.dependencies]`) is not handled.
  - `[target.'cfg(..)'.dependencies]` tables are not handled.
  - Renamed deps (`package = "…"`) are not handled.
  - Exclude `target/` from the Cargo.toml rglob.
  - `read_text` has no explicit encoding.
- **R3. `rule_metadata.py`:** the Rust rule descriptions are truncated
  mid-sentence ("…panic instead of.", "…inside.", "…bounding the.").

### Grammar handling
- **G1. The `tree-sitter-dockerfile>=0.0.0a1` floor** (pyproject.toml) installs
  an empty "coming soon" placeholder on platforms without a 0.2.0 wheel, so
  Dockerfile analysis is silently lost there.
  - Restore `>=0.2` with a platform marker matching the wheels that actually
    exist.
  - Keep the aarch64 exclusion.
- **G2. Over-broad exception handling.** `AttributeError` was added to the
  "grammar not installed" catch (`collectors/ast_common.py`,
  `collectors/dockerfile.py`). Narrow it to the `getattr(mod, func_name)` call.
- **G3. `grammar_warnings` accumulate** on module-level singleton collectors
  across runs. Record each warning once, or reset per run.

### Graphify
- **GR1. Graphify runs on every scan.** It is now a core dependency and runs
  `graphify update`/`cluster-only` (up to 2×300 s), writes `graphify-out/` into
  the scanned repo, and reuses a stale `graph.json`. It also fails in Container
  E2E on a `:ro` mount, and the job still passes.
  - Gate it behind config (opt-in).
  - Write its output to a temp dir.
  - Make E2E fail on collector crashes.

### Baselines / Windows
- **W1. Windows fingerprints changed.** The forward-slash locator change alters
  fingerprints for existing Windows users (`issues._finding_key`, baseline
  keys). Normalise `\` to `/` when loading baseline records and legacy issue
  markers.
- **W2. Tests cancel out the fix.** About 15 assertions normalise the actual
  value (`.replace("\\", "/")`), which removes the property the fix is meant to
  guarantee. Assert raw locators, and add a test that feeds a Windows-style
  relative path.

### PDF / reports
- **P1. Missing appendix.** The Scoring Methodology / LLM Usage appendix was
  dropped from the Typst PDF; `llm_info` is accepted but unused, yet the text
  still says "See Appendix — Scoring Methodology". Restore it via
  `_md_to_typst(_methodology_appendix(llm_info=…))`.
- **P2. Arch diagram resolution.** The `scale=4`, `width=2400` render was lost
  in the typst migration. Restore it.
- **P3. Methodology disclosure.** `cli._resolve_llm_info` and
  `arch_orchestrator` report `llm_model` from config. Check the disclosure
  matches the model actually used, now that the config fix is in.

### LLM call sites
- **L1. Market comparison drops its payload.** `arch_market_comparison.py`
  wraps the whole profile as one bundle item under an 8 KB cap. An oversized
  profile becomes `[]`. This also exists on main.

### Detection / config wiring
- **C1. Unused parameter.** `arch_integ_config.discover_config_integrations`
  gained `exclude_test_paths`, but its only caller (`arch_integrations.py`)
  never passes it.
- **C2. Detection performance.** Detection `rglob`s traverse
  `node_modules`/`target` before exclusion. Prune during the walk.

### Privacy hygiene
- **PV1. SCM-username filter is too broad.** It is domain-agnostic
  (`hygiene/collectors/privacy.py`): `github@acme-corp.com` and
  `deploy@acme.com` are suppressed. Restrict it to SSH-remote contexts, and add
  tests; the SSH false-positive fix currently has none.

### Tests that do not test
- **T1. Ineffective missing-grammar tests.**
  - `test_missing_grammar_warning.py` tests named "Raises…" only assert `== []`.
  - The `BaseASTCollector` grammar warning is never asserted.
  - Assert `grammar_warnings`, and add an `AttributeError` side-effect case.
- **T2. No-op flag patches.**
  - `monkeypatch.setattr(..., "_AI_TOOLING_AVAILABLE", True)` is a no-op in
    `test_baseline.py`, `test_pilot_validation.py` and `test_llm_client.py`;
    nothing reads that flag.
  - `test_returns_unavailable_client_when_no_ai_tooling` fails if
    `ANTHROPIC_API_KEY` is set.
  - Make LLM isolation real: patch `create_llm_client`.

### Dependencies, docs, release hygiene
- **H1. Lockfiles.** Regenerate `requirements.txt` and `requirements-dev.txt`
  with pip-compile. They currently lack typst, graphviz, graphifyy, networkx,
  aiohttp and their transitive deps. `tree-sitter==0.26.0` conflicts with the
  graphifyy cap, and `anthropic` is still listed in dev.
- **H2. Stale documentation.** Docs still describe weasyprint or the removed
  extras: ARCHITECTURE.md, docs/dependencies.md, docs/install.md,
  scripts/setup-all.sh, and the site mdx pages (output formats, arch, first
  scan, faq, advanced). README, CHANGELOG and docs/dependencies.md also claim
  openai is a core dependency, which is false.
- **H3. CHANGELOG.**
  - The PR rewrote historical release entries (0.3.1, 0.2.0, 0.1.x). Revert
    those.
  - Add `[Unreleased]` entries for the typst migration, Rust support, extras
    consolidation, the detection/required_tech change, and the LLM refactor
    (breaking: `llm_client` removed, `LlmClient.analyze` → `call`,
    `Capabilities.weasyprint` removed).
  - Version is still 0.3.1, while the PR title says v0.5.
- **H4. zlib CVEs.** `.trivyignore` adds zlib1g CVE-2026-76844 and
  CVE-2026-85091 globally with no expiry. A Debian fix exists:
  - Upgrade zlib1g in the Dockerfile runtime stage and drop the ignores.
  - Consider pinning the `python:3.14-slim` base by digest.
- **H5. CI hygiene.**
  - Restore the removed "Test summary" step.
  - Restore the deleted comment explaining `scanners: vuln`.
  - test-llm runs without coverage. Add `--cov --cov-append`, or merge its
    coverage with test-core's.

## Constraints

- Repo rule: one branch per milestone. PR #255 is "fixed in place" on
  `pr255-fixes`, and the owner decides when to push to the fork.
- Run regression snapshots and `pre-commit run --all-files` before every
  commit, not as a follow-up.
- Never weaken a test or fixture to make it pass.
