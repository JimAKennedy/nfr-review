# M001/S11 plan — Docs and CHANGELOG

**Slice:** M001/S11 in `docs/plans/pr255-remediation/ledger.md`
(rows H2, H3; depends on M001/S04)

**Task status**

- [x] Task 1 — H3: restore the historical CHANGELOG entries to main's text
- [x] Task 2 — H2: correct the core docs (dependencies, install, README, ARCHITECTURE)
- [x] Task 3 — H2: correct the site pages and `scripts/setup-all.sh`
- [ ] Task 4 — H2: document graphify opt-in and `--strict-collectors`
- [ ] Task 5 — H3: write `[Unreleased]` and record the version decision
- [ ] Task 6 — Slice gate and evidence

**Definition of Done**

- [ ] No user-facing doc mentions weasyprint, the removed extras, or openai as a core dependency
- [ ] Historical CHANGELOG entries (0.3.1, 0.2.0, 0.1.x) match main
- [ ] `[Unreleased]` records the typst migration, Rust support, extras consolidation, the detection/required_tech change, graphify becoming opt-in, and the breaking LLM refactor
- [ ] The package version agrees with the CHANGELOG, and the PR-title correction is recorded as an owner action in the milestone report

**Validation** (tokens from `.jk/validations.yml`, run from the worktree root
with `.venv/bin` first on `PATH`: `export PATH="$PWD/.venv/bin:$PATH"`)

1. `format` → `pre-commit run --all-files`
2. `discipline` → `jk-standards ledger`
3. `gate` →
   `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`

Also run on every docs task: the CI doc-lint job's command,
`python scripts/lint_docs.py` (checks `site/src/data/rules.json` against the
rule registry, `<CodeSnippet>` regions in the site `.mdx` pages, and the
compliance rule count; it exits 0 on the branch today).

Repo constraint (input.md): run the regression snapshots and
`pre-commit run --all-files` before every commit. Each commit step below runs
`python -m pytest -n auto -m regression --timeout=600 tests/regression` and
`pre-commit run --all-files` first.

**Version decision (H3, recorded here as the ledger row requires):** the
package version stays `0.3.1` (`pyproject.toml` `version` and
`src/nfr_review/__init__.py` `__version__`); every change goes under
`## [Unreleased]`; no release heading is added. Source: M001-decisions,
"S11: what should the version be? — Leave 0.3.1". The PR title's "v0.5" is
not edited by this run (M001-decisions, last decision); the milestone report
recommends that the owner retitle the PR. DoD 4 is checked here for the
package/CHANGELOG half; the PR-title half is the owner's action and is
recorded as such in the evidence file.

---


> **Evidence rule (ledger standard):** evidence is appended per task as it lands and never names a commit SHA; the commits are found with `git log --grep="Slice: M001/S11"`. Earlier wording in this plan that asked for SHAs was removed on 2026-11-11 before execution.

## Preconditions

1. S04 is `done`:
   `grep -n -A6 '^### Slice M001/S04 ' docs/plans/pr255-remediation/ledger.md | grep Status`
   prints `**Status:** done`.
2. The S04 surface exists:
   `nfr-review run --help | grep -- --strict-collectors` prints a line, and
   `grep -n 'enabled: bool = False' src/nfr_review/config.py` prints the
   `GraphifyConfig` field.
3. Record which of S02–S10 are `done` (Task 5 writes `Fixed` entries only for
   those):
   `grep -n -A6 -E '^### Slice M001/S(0[2-9]|10) ' docs/plans/pr255-remediation/ledger.md | grep -E 'Slice|Status'`.

Ground truth for every docs edit (read from the tree, not from the old docs):

- Core dependencies: `pyproject.toml` `[project] dependencies` — click,
  pydantic, ruamel.yaml, tree-sitter and the grammars, graphviz,
  `graphifyy==0.9.97`, networkx, aiohttp, typst, packaging, resolvelib.
  `openai` and `weasyprint` are in neither the core list nor any extra.
- Extras today: `[dev]` (no `anthropic`), `[llm]` (`anthropic>=0.40` plus
  `ai-tooling`, which is installed from a local checkout and is not on PyPI —
  deferred under D1), `[scancode]`, `[otel]`, `[full]` = `[llm,scancode,otel]`.
  Removed relative to main: `[pdf]`, `[diagrams]`, `[monitor]`, `[graphify]`,
  `[llm-anthropic]`, `[llm-openai]`. `[all]` and `[monitor]` named on site
  pages do not exist.
- OpenAI-compatible backend: the `openai` provider is still accepted by
  `LlmConfig` (`config.py`: `LlmProvider = Literal["anthropic", "openai", "claude-cli"]`)
  and is implemented by ai-tooling, whose own `pyproject.toml` lists `openai`
  only under its optional `[openai]` extra (checked at ai-tooling commit
  `613d2ddf37157856146022548e7bc46600dd5afb`). So the docs say: the
  OpenAI-compatible backend needs the `[llm]` extra **and** the `openai`
  package (`pip install openai`), which nfr-review does not install.
- Docker image: the `Dockerfile` builder runs `pip install --no-cache-dir .`
  (no extras), and the runtime stage installs only the apt packages listed in
  its `RUN apt-get install` block. Read that block at execution time
  (`grep -n -A8 'apt-get install' Dockerfile`) and list exactly those. The
  image therefore has no LLM SDK: LLM features are skipped inside the
  container. PDF output is Typst (in core), no Cairo/Pango.
- PDF engine: `typst` (core), used by `output/pdf.py` and
  `arch_report_render.py`.
- LLM module: `src/nfr_review/llm_client.py` no longer exists; the integration
  point is `src/nfr_review/llm_integration.py`; `protocols.py` no longer
  defines `LlmClient`.

---

## Task 1 — H3: restore the historical CHANGELOG entries

**Row:** H3. **Files:** `CHANGELOG.md` (modify). **Consumes:**
`git show main:CHANGELOG.md`. **Produces:** a CHANGELOG identical to main's,
so that the only later diff against main is inside `[Unreleased]`.

The PR rewrote four historical bullets (0.3.1 "CI graphify integration",
0.2.0 "`[monitor]` optional extra", 0.1.0 "PDF report generation" and
"Multi-backend LLM support"); its `[Unreleased]` is empty, as on main.

Steps:

1. **Failing check.** `git diff --quiet main -- CHANGELOG.md && echo changelog-matches-main`
   prints nothing now (exit 1).
2. **Change.** `git checkout main -- CHANGELOG.md`.
3. **Check passes.** Rerun step 1; expected `changelog-matches-main`.
4. **Commit.** Run
   `python -m pytest -n auto -m regression --timeout=600 tests/regression`
   and `pre-commit run --all-files`; both pass. Then:

   ```bash
   git add CHANGELOG.md
   git commit -m "docs(changelog): restore released entries to their published text" \
     -m "Released sections are a historical record; the PR's rewrites of 0.3.1, 0.2.0 and 0.1.0 bullets are reverted. Unreleased changes are recorded separately." \
     -m "Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S11
   Rows: H3
   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```

**Token check:** `format`.

---

## Task 2 — H2: core docs

**Row:** H2. **Files:** `docs/dependencies.md`, `docs/install.md`,
`README.md`, `ARCHITECTURE.md` (modify). **Consumes:** the ground truth above.
**Produces:** core docs with no weasyprint, no removed extras, no "openai is
core", no claim that the image ships LLM SDKs, and no reference to the
removed `llm_client.py`.

Steps:

1. **Failing check** (each `grep` must find nothing; today all find lines):

   ```bash
   bash -c 'F="ARCHITECTURE.md README.md docs/dependencies.md docs/install.md"
   ! grep -niI weasyprint $F &&
   ! grep -niIE "openai.*core|core.*openai|OpenAI SDKs|Anthropic and OpenAI" $F &&
   ! grep -nIE "nfr-review\[(pdf|diagrams|monitor|graphify|llm-anthropic|llm-openai|all)\]|\`\[(pdf|diagrams|monitor|graphify|llm-anthropic|llm-openai)\]\`" $F &&
   ! grep -nIE "llm_client\.py|ruff, anthropic, and build|Anthropic SDK for LLM-augmented rule tests" $F' && echo core-docs-OK
   ```

   Expected now: no `core-docs-OK`.

2. **`docs/dependencies.md`.**
   - Section 1 table: delete the `weasyprint` row and the `openai` row. Add a
     `typst` row: constraint `>=0.15`, purpose "Typst compiler (Python
     wheel) for `report` and `arch` PDF output", notes "Self-contained wheel;
     no system libraries. Use `--no-pdf` to skip PDF output". Update the
     `tree-sitter-dockerfile` row's notes to the S03 truth: installed only on
     macOS arm64 and Linux x86_64 (the platforms with published 0.2 wheels);
     copy the marker from `pyproject.toml`. Update the `graphifyy` row's
     notes: "Runs only when `graphify.enabled: true` (default `false`); see
     the Graphify usage guide".
   - Section 2: the `[llm]` table lists `anthropic>=0.40` and `ai-tooling`
     (LLM provider layer; not yet published on PyPI). Under it, state that the
     OpenAI-compatible backend additionally needs `pip install openai`.
     Delete the `anthropic` row from the `[dev]` table.
   - Section 3 (LLM providers): the OpenAI-compatible row's "SDK / binary"
     cell becomes "`openai>=1.0` (install separately) via the `[llm]` extra".
   - Section 7 (runtime binaries): the `graphify` row's "if absent" cell
     stays; add to its purpose "(only when `graphify.enabled: true`)".
   - Section 9 (container image): replace the "Python extras" row value with
     "none — the image installs the core package only; LLM features are
     skipped in the container". Replace the "System packages in the image"
     paragraph with the apt packages read from the `Dockerfile` (see ground
     truth). Keep the "Not included" paragraph.
3. **`docs/install.md`.**
   - Section 7 table: OpenAI-compatible row's "Extra to install" becomes
     "`[llm]` + `pip install openai`". In "Option B — OpenAI-compatible
     (Ollama)", change `pip install "nfr-review[llm]"` to
     `pip install "nfr-review[llm]" openai`.
   - Section 10 "Optional extras": `[llm]` row describes `anthropic` plus
     ai-tooling and says the OpenAI-compatible backend also needs the
     `openai` package; `[dev]` row drops `anthropic`
     ("pytest, pytest-cov, pytest-timeout, pytest-xdist, pytest-asyncio,
     pytest-aiohttp, filelock, ruff, and build"). The lead-in sentence and the
     "Base install" comment say core includes all languages, Typst PDF,
     diagrams, graphify (off by default) and the monitor.
   - Section 10 "Docker": the first paragraph says the image contains the
     core install (Typst PDF included) plus the apt packages from the
     `Dockerfile`, and no LLM SDK. Change the comment
     `# Full report with PDF (WeasyPrint included in image)` to
     `# Full report with PDF (Typst, included in core)`. Replace the
     "Using LLM features in Docker" paragraph and its three `docker run`
     examples with one paragraph: the image does not include an LLM SDK yet,
     so LLM features (executive summary, ADR drift, PII confirmation) are
     skipped in the container and every static-analysis rule still runs; use
     a pip install with the `[llm]` extra for LLM features.
4. **`README.md`.**
   - "Optional extras" code block under Local CLI: keep `[llm]` and
     `[scancode]` lines (both exist).
   - "Docker" paragraph: replace "The image includes the `[llm]` extra and
     the `gh` CLI. All other features (PDF, diagrams, structural analysis)
     are included in core." with the image truth (core install, apt packages
     from the `Dockerfile`, no LLM SDK). Replace "Using LLM features in
     Docker" and its two `docker run` examples with the same one-paragraph
     statement as install.md.
   - "Optional: LLM features": rewrite the first sentence to: Anthropic API
     (`[llm]` extra), OpenAI-compatible APIs such as Ollama (`[llm]` extra
     plus `pip install openai`), and Claude CLI (no extra).
   - Extras table: `[llm]` row mentions ai-tooling alongside anthropic.
5. **`ARCHITECTURE.md`.**
   - `render_pdf_report()  -->  PDF (weasyprint)` → `PDF (typst)`.
   - `PDF report       -->  {repo}-architecture.pdf  (via weasyprint)` →
     `(via typst)`.
   - Module table: the `output/pdf.py` row becomes "PDF report generation via
     Typst; converts rendered Markdown, diagrams and the summary section to
     Typst markup (escaped) and compiles it in a temporary root".
     Replace the `llm_client.py` row with an `llm_integration.py` row: "Single
     LLM integration point; delegates to ai-tooling when installed, inert stub
     otherwise; `create_llm_client`, `extract_json`, `serialize_bundle`,
     `run_analysis`", same "Not responsible for" cell. In the `protocols.py`
     row remove `LlmClient` from the protocol list (`Band`, `Collector`,
     `Rule` remain — confirm with `grep -n '^class' src/nfr_review/protocols.py`).
6. **Check passes.** Rerun step 1; expected `core-docs-OK`. Then
   `python scripts/lint_docs.py` exits 0.
7. **Commit.** Run
   `python -m pytest -n auto -m regression --timeout=600 tests/regression`
   and `pre-commit run --all-files`; both pass. Then:

   ```bash
   git add docs/dependencies.md docs/install.md README.md ARCHITECTURE.md
   git commit -m "docs: describe typst PDF, the consolidated extras and the real LLM dependencies" \
     -m "Removes weasyprint, the removed extras and the claim that openai is core; the OpenAI-compatible backend needs pip install openai; the Docker image ships no LLM SDK; llm_client.py is replaced by llm_integration.py." \
     -m "Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S11
   Rows: H2
   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```

**Token check:** `format`.

---

## Task 3 — H2: site pages and setup script

**Row:** H2. **Files:** `site/src/content/docs/learn/06-output-formats.mdx`,
`site/src/content/docs/reference/arch.mdx`,
`site/src/content/docs/learn/02-first-scan.mdx`,
`site/src/content/docs/appendices/faq.mdx`,
`site/src/content/docs/learn/10-advanced.mdx`,
`site/src/content/docs/learn/03-the-pipeline.mdx`,
`site/src/content/docs/learn/11-ci-cd.mdx`, `scripts/setup-all.sh` (modify).
**Consumes:** the ground truth above. **Produces:** site pages and the setup
script with no weasyprint and no removed or nonexistent extras.

The ledger names five site pages (output formats, arch, first scan, faq,
advanced). Enumeration while planning found two more that name a removed
extra or a false image claim: `03-the-pipeline.mdx` ("requires `[pdf]`
extra") and `11-ci-cd.mdx` ("pre-built Docker image with all extras"); they
are fixed here too.

Steps:

1. **Failing check:**

   ```bash
   bash -c 'F="site/src/content/docs scripts/setup-all.sh"
   ! grep -rniI weasyprint $F &&
   ! grep -rniIE "openai.*core|core.*openai" $F &&
   ! grep -rnIE "nfr-review\[(pdf|diagrams|monitor|graphify|llm-anthropic|llm-openai|all)\]|\`\[(pdf|diagrams|monitor|graphify|llm-anthropic|llm-openai)\]\`|diagrams, pdf, graphify|image with all extras" $F' && echo site-docs-OK
   ```

   Expected now: no `site-docs-OK`.

2. **`learn/06-output-formats.mdx`:** the PDF `<Aside>` says PDF output is
   rendered with Typst, which is included in the base install; no extra or
   system library is needed.
3. **`reference/arch.mdx`:** "### PDF" paragraph: "Rendered version of the
   Markdown report via Typst (included in the base install)." Drop the extra.
4. **`learn/02-first-scan.mdx`:** "Optional extras" block becomes:

   ```bash
   # LLM-powered executive summaries (Anthropic)
   pip install "nfr-review[llm]"

   # License compliance scanning
   pip install "nfr-review[scancode]"

   # Everything optional (llm + scancode + otel)
   pip install "nfr-review[full]"
   ```

   with a lead-in sentence that PDF output, diagrams, all languages and the
   production monitor are in the base install.
5. **`appendices/faq.mdx`:** the optional-features block lists `[llm]`,
   `[scancode]`, `[otel]`, `[full]` with one-line comments. In "Required
   collector not available": `graphify` line becomes "`graphify` is part of
   the base install and runs only when `graphify.enabled: true`"; the monitor
   line becomes "Monitor mode is part of the base install (aiohttp is a core
   dependency)".
6. **`learn/10-advanced.mdx`:** the monitor `<Aside>` says monitor mode is in
   the base install and uses aiohttp for the OTLP receiver. (The Graphify
   section of this page is Task 4.)
7. **`learn/03-the-pipeline.mdx`:** PDF row's audience cell drops
   "(requires `[pdf]` extra)".
8. **`learn/11-ci-cd.mdx`:** container row: "Runs inside the pre-built Docker
   image (core install)"; the following sentence keeps PDF generation and
   diagram rendering and drops "the `gh` CLI" unless
   `grep -n -A8 'apt-get install' Dockerfile` lists `gh`.
9. **`scripts/setup-all.sh`:** replace the weasyprint probe with a typst probe
   (`python -c "import typst"`, `success "typst: OK"`,
   `MISSING_PKGS+=("typst")`); change
   `echo "  Extras installed: dev, scancode, diagrams, pdf, graphify"` to
   `echo "  Extras installed: dev, full (llm, scancode, otel)"`, matching the
   `pip install -e "$PROJECT_ROOT[dev,full,scancode,otel]"` line, which is not
   changed (the `[llm]` packaging is deferred under D1). Change the graphify
   CLI warning `structural analysis will use pre-generated graph.json only`
   to `graphify.enabled scans need graphify.graph_path`. Then
   `bash -n scripts/setup-all.sh && echo syntax-ok`.
10. **Check passes.** Rerun step 1; expected `site-docs-OK`. Then
    `python scripts/lint_docs.py` exits 0.
11. **Commit.** Run
    `python -m pytest -n auto -m regression --timeout=600 tests/regression`
    and `pre-commit run --all-files`; both pass. Then:

    ```bash
    git add site/src/content/docs scripts/setup-all.sh
    git commit -m "docs(site): drop weasyprint and removed extras from site pages and setup script" \
      -m "Plan: docs/plans/pr255-remediation/ledger.md
    Slice: M001/S11
    Rows: H2
    Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    ```

**Token check:** `format`.

---

## Task 4 — H2: graphify opt-in and `--strict-collectors`

**Row:** H2 (docs must describe graphify as opt-in, ledger Sequencing).
**Files:** `site/src/content/docs/reference/config.mdx`,
`site/src/content/docs/reference/cli.mdx`, `README.md`,
`docs/graphify-guide.md`, `site/src/content/docs/learn/10-advanced.mdx`
(modify). **Consumes:** S04's `GraphifyConfig.enabled` and
`run --strict-collectors`, read from the code. **Produces:** config and CLI
reference entries and a graphify guide that match S04.

Read first, and document what the code does:
`grep -n -B2 -A20 'class GraphifyConfig' src/nfr_review/config.py`,
`grep -n -i 'enabled\|graph_path\|GRAPHIFY_OUT\|TemporaryDirectory' src/nfr_review/collectors/graphify.py`,
`grep -n -A25 'strict.collectors' src/nfr_review/cli.py`, and
`nfr-review run --help`, `nfr-review report --help`, `nfr-review all --help`
(document the flag on each subcommand whose help lists it). S04's approved
behaviour (M001-S04-design.md): `enabled: false` → no subprocess, collector
returns nothing; `enabled: true` + `graph_path` → reads that file, no
subprocess; `enabled: true` without `graph_path` → runs graphify with output
in a temp dir and deletes it; a `graphify-out/` in the scanned repo is never
read; `--strict-collectors` exits non-zero after writing outputs if any
collector failed, and grammar-not-installed warnings do not count.

Steps:

1. **Failing check:**

   ```bash
   bash -c 'set -e
   grep -q "| \`enabled\` | bool | \`false\` |" site/src/content/docs/reference/config.mdx
   grep -q -- "--strict-collectors" site/src/content/docs/reference/cli.mdx
   grep -q -- "--strict-collectors" README.md
   grep -q "enabled: true" docs/graphify-guide.md
   grep -q "graphify.enabled" site/src/content/docs/learn/10-advanced.mdx
   ! grep -nE "auto-detects graphify-out|reuses it without re-running|Checks if \`graphify-out/graph.json\` exists|nfr-review detects it automatically|pip install graphify$" docs/graphify-guide.md site/src/content/docs/learn/10-advanced.mdx' && echo s04-docs-OK
   ```

   Expected now: no `s04-docs-OK`.

2. **`reference/config.mdx`:** in the full example, add `enabled: false` as
   the first key under `graphify:` with comment
   `# run the graphify collector (off by default)`. In the `### graphify`
   table add the first row
   `| \`enabled\` | bool | \`false\` | Run the graphify collector. When \`false\`, no graphify process runs and structural rules report no evidence. |`
   and change the `graph_path` description to "Path to an existing
   `graph.json` to read instead of running graphify (only used when
   `enabled` is `true`)".
3. **`reference/cli.mdx`:** in the `nfr-review run` options table (and in any
   other subcommand table whose `--help` lists it) add
   `| \`--strict-collectors\` | Flag | off | Exit non-zero after writing outputs if any collector failed. Missing-grammar warnings do not count. |`.
   If `cli.py` uses a specific exit code for this, add it to the "Exit Codes"
   table with that meaning.
4. **`README.md`:** add the same `--strict-collectors` row to the `run`
   options table (after `--workers N`, in that table's three-column format).
   In "Optional external tools", the Graphify row's install cell becomes
   "Included in `pip install nfr-review`; enable with `graphify.enabled: true`",
   and the sentence "Without Graphify, structural analysis rules … are
   skipped gracefully" becomes "Structural analysis is off by default; set
   `graphify.enabled: true` in `nfr-review.yaml` to run it."
5. **`docs/graphify-guide.md`:**
   - §2 Quick start: step 1 becomes adding
     `graphify:\n  enabled: true` to `nfr-review.yaml`; step 2 `nfr-review run .`
     (nfr-review runs graphify itself, out of tree); keep step 3. Remove
     "it auto-detects graphify-out/graph.json".
   - §3 How it works: the diagram and step 2 say the collector runs graphify
     into a temporary directory (or reads `graphify.graph_path`) — not
     `graphify-out/graph.json` in the repo.
   - §4: "Pre-existing graph.json" becomes "Using a graph you built
     yourself": run `graphify update` yourself and set
     `graphify.enabled: true` and `graphify.graph_path` to the file; nfr-review
     reads it and does not check its freshness. State that a `graphify-out/`
     directory inside the scanned repo is never read. Keep the `.gitignore`
     subsection (it applies to manual runs).
   - §5: replace the five-step collector list with the three-row behaviour
     from S04 (disabled → nothing runs; enabled + `graph_path` → read it;
     enabled without `graph_path` → run graphify in a temp dir, read, delete).
     "Graceful degradation": add that with `enabled: false` the structural
     rules report no evidence.
   - §8 Configuration: add `enabled: false` (default) as the first key with
     its comment, and change the `graph_path` comment to
     "read this graph.json instead of running graphify".
   - §9 CI integration: in both workflow snippets, either drop the
     `graphify update` step and rely on `enabled: true`, or keep it and add a
     note that `graphify.graph_path: graphify-out/graph.json` must be set.
     Use the first form (simpler).
   - §12 Troubleshooting "no graphify-analysis evidence available": item 2
     becomes "Is `graphify.enabled: true` set in `nfr-review.yaml`?".
6. **`learn/10-advanced.mdx`**, "Graph analysis (Graphify)": replace
   "Graphify is optional — if the tool is not installed, the collector is
   skipped gracefully." and the `pip install graphify` / "detects it
   automatically" block with: graphify ships with the base install and is
   off by default; enable it with

   ```yaml
   # nfr-review.yaml
   graphify:
     enabled: true
   ```

   and link to the config reference.
7. **Check passes.** Rerun step 1; expected `s04-docs-OK`. Then
   `python scripts/lint_docs.py` exits 0.
8. **Commit.** Run
   `python -m pytest -n auto -m regression --timeout=600 tests/regression`
   and `pre-commit run --all-files`; both pass. Then:

   ```bash
   git add site/src/content/docs README.md docs/graphify-guide.md
   git commit -m "docs: document graphify.enabled and run --strict-collectors" \
     -m "Graphify is opt-in and never reads or writes graphify-out/ in the scanned repo; --strict-collectors fails the run when a collector crashes." \
     -m "Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S11
   Rows: H2
   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```

**Token check:** `format`.

---

## Task 5 — H3: `[Unreleased]` and the version check

**Row:** H3. **Files:** `CHANGELOG.md` (modify). **Consumes:** the commit
history (`git log --oneline main..pr255-fixes`), the ledger rows of S02–S10
and their statuses (Precondition 3). **Produces:** an `[Unreleased]` section
in the file's Keep a Changelog style (bold lead phrase, em dash, sentence),
with a `### Breaking` subsection, and no change outside `[Unreleased]`.

Steps:

1. **Failing check:**

   ```bash
   bash -c 'set -e
   u=$(sed -n "/^## \[Unreleased\]/,/^## \[0\.3\.1\]/p" CHANGELOG.md)
   for s in "### Breaking" "Typst" "Rust language support" "extras" "required_tech" "graphify.enabled" "--strict-collectors" "LlmClient.analyze" "Capabilities.weasyprint" "llm_client"; do
     printf "%s" "$u" | grep -qF -- "$s"
   done' && echo unreleased-OK
   ```

   Expected now: no `unreleased-OK` (`[Unreleased]` is empty).

2. **Confirm API facts before writing them:**
   `grep -n 'def call' src/nfr_review/llm_integration.py` (expect
   `call(self, prompt: str, *, max_tokens: int = 1024)`),
   `git show main:src/nfr_review/llm_client.py | grep -n 'def analyze\|def serialize_evidence_bundle\|class LlmUnavailableError'`,
   `grep -n 'weasyprint' src/nfr_review/capabilities.py` (expect nothing),
   `git show main:src/nfr_review/protocols.py | grep -n 'class LlmClient'`.
   If any differs, write what the code shows.

3. **Insert** after the `## [Unreleased]` line (one blank line before and
   after each subsection, wrapped at about 78 columns like the rest of the
   file). Bullets marked *(S0N)* in the mapping table below are written only
   if that slice is `done` per Precondition 3; omitted ones are listed in the
   evidence file so the later slice adds its own line.

   ```markdown
   ### Breaking

   - **LLM integration moved to ai-tooling** — `nfr_review.llm_client` is
     removed; LLM access goes through `nfr_review.llm_integration`, which
     delegates to the `ai-tooling` library from the `[llm]` extra and falls
     back to an inert client without it. `LlmClient.analyze(prompt,
     evidence_bundle, max_tokens)` is replaced by `LlmClient.call(prompt, *,
     max_tokens)`; `serialize_evidence_bundle` is replaced by
     `serialize_bundle`; `LlmUnavailableError` is replaced by
     `ProviderUnavailableError`; the `AnthropicClient`,
     `OpenAICompatibleClient` and `ClaudeCliClient` classes and the
     `nfr_review.protocols.LlmClient` protocol are removed. Custom rules that
     call the LLM must switch to `call()`.
   - **`Capabilities.weasyprint` removed** — `detect_capabilities()` reports
     only `git`, `mmdc` and `dot`.

   ### Added

   - **Rust language support** — Cargo.toml detection, a tree-sitter AST
     collector, a Cargo.toml dependency collector (deps.dev `cargo`
     ecosystem) and five rules: `rust-unwrap-expect`,
     `rust-mutex-lock-unwrap`, `rust-http-no-timeout`,
     `rust-blocking-in-async` and `rust-unbounded-spawn-in-loop`.
   - **`graphify.enabled`** — new config key (default `false`) that turns
     the graphify collector on.
   - **`run --strict-collectors`** — exits non-zero after writing its outputs
     if any collector failed; missing-grammar warnings do not count. The
     Container E2E job uses it.
   - **Missing grammar warnings** — when a tree-sitter grammar cannot be
     loaded, the run reports a warning naming it instead of silently
     producing no evidence for that language.

   ### Changed

   - **PDF rendering uses Typst** — weasyprint and its Cairo/Pango system
     libraries are replaced by the self-contained `typst` wheel, so `report`
     and `arch` PDFs build on every platform, including Windows. Typst
     markup in report content is escaped and compilation is confined to a
     temporary root. The Docker image no longer installs Cairo/Pango.
   - **Optional extras consolidated** — all language grammars, graphviz,
     graphifyy, networkx, aiohttp and typst are core dependencies. The
     `[pdf]`, `[diagrams]`, `[monitor]`, `[graphify]`, `[llm-anthropic]` and
     `[llm-openai]` extras are removed; use `[llm]` for the Anthropic backend.
     nfr-review no longer installs `openai`: the OpenAI-compatible backend
     needs `pip install openai` alongside `[llm]`. `anthropic` is no longer
     in `[dev]`. Remaining extras: `[llm]`, `[scancode]`, `[otel]`, `[full]`,
     `[dev]`.
   - **Technology detection and `required_tech`** — every Go, Python, Java,
     Node.js and C# rule now declares `required_tech`, so language rules run
     only when their technology is detected. Detection now finds Go, Rust,
     Node.js, Python, Java and Spring Boot modules in subdirectories
     (monorepos), and detects Python from scripts alone, without a packaging
     manifest.
   - **Graphify is opt-in** — the graphify collector no longer runs on every
     scan. With `graphify.enabled: true` it reads `graphify.graph_path` if
     set, otherwise runs graphify with its output in a temporary directory.
     A `graphify-out/` directory in the scanned repository is never read or
     written.
   - **Evidence locators use forward slashes on every platform**, so JSONL,
     CSV and SARIF output on Windows matches other platforms.
   - **LLM configuration** — the LLM client honours `LlmConfig` defaults,
     `NFR_LLM_*` environment overrides and a `.env` file in the source
     checkout.
   - **`click>=8.2`** is now the minimum supported version.
   - **CI** — coverage is measured over all shipped code, and the LLM
     integration tests publish their own coverage report.

   ### Fixed

   - Windows: baselines and issue markers recorded with `\` locators still
     match after the forward-slash change.
   - Windows: collector subprocesses are stopped with `terminate()` instead
     of `SIGTERM`, and `nfr-review monitor` no longer depends on POSIX-only
     signal and `resource` APIs.
   - `--include-tests` is honoured by architecture integration discovery.
   - Rust: io `.read(..)`/`.write(..)` calls with arguments are not reported
     as lock calls; blocking calls inside closures in async functions are not
     reported, and those inside `async {}` blocks in sync functions are;
     test-code suppression matches `#[test]`, `#[cfg(test)]` and a
     `mod tests` exactly; imported paths are resolved;
     `rust-mutex-lock-unwrap` skips test code; unwrap summaries are
     single-line and bounded; rule descriptions are complete sentences.
   - Rust dependencies: workspace-inherited, target-specific and renamed
     Cargo dependencies resolve to the right crate, and `target/` is not
     parsed.
   - `tree-sitter-dockerfile` is installed only where a 0.2 wheel exists
     instead of as an empty placeholder; an `AttributeError` raised outside
     grammar loading is no longer reported as a missing grammar; each
     grammar warning is reported once per run.
   - PDF: the Scoring Methodology appendix, including the LLM usage
     disclosure, is back in the Typst PDF; architecture diagrams render at
     full resolution again.
   - Architecture report: the disclosed LLM model is the one the client
     resolved from config, and an architecture profile over 8 KB still
     reaches the market-comparison call.
   - Configuration-integration discovery honours the configured test-path
     exclusion, and detection no longer walks `node_modules`, `target` or
     other excluded directories.
   - Privacy rule: SCM-username suppression applies only to SSH remotes such
     as `git@github.com:org/repo`; addresses like `github@acme-corp.com` in
     prose are reported.
   - The executive summary sends its full payload to the LLM instead of an
     empty list when it exceeds 8 KB.

   ### Security

   - Docker image: zlib1g is upgraded to the Debian fix for CVE-2026-76844
     and CVE-2026-85091, and the base image is pinned by digest.

   ### Dependencies

   - `requirements.txt` and `requirements-dev.txt` recompiled from
     `pyproject.toml`; `tree-sitter` is held below 0.26 for
     `graphifyy==0.9.97`.
   - `tree-sitter-dockerfile>=0.2`, installed only on macOS arm64 and Linux
     x86_64.
   - Dependabot now updates the Docker base image digest.
   ```

   Bullet → source mapping (drop a bullet only if its slice is not `done`):

   | Bullet | Source |
   |---|---|
   | Breaking, both | commits `16ec3a7`, `4bfe2bd`, `3e6f076` (landed) |
   | Rust language support | commit `642f36f` (landed) |
   | graphify.enabled, `--strict-collectors`, Graphify is opt-in | S04 (GR1) |
   | Missing grammar warnings | commit `0d76f76` (landed) |
   | Typst | commits `3e6f076`, `42e979f`, `003069e` (landed) |
   | Extras consolidated | commits `e3dfab0`, `3a47e88`, `39f912e` (landed) |
   | required_tech / detection | commits `6a34524`, `03ce982`, `3a47e88`, `bb39ff0` (landed) |
   | Forward slashes | commit `e9fdfc6` (landed) |
   | LLM configuration | commit `0a9fdc1` (landed) |
   | click | commit `b0477e4` (landed) |
   | CI coverage | commit `828beaf` (landed) and S10 (H5) for the second clause |
   | Fixed: Windows baselines | S05 (W1) |
   | Fixed: terminate / monitor | commits `b0477e4`, `3a47e88` (landed) |
   | Fixed: `--include-tests` | commit `e9fdfc6` (landed) |
   | Fixed: Rust, Rust dependencies | S02 (R1, R2, R3) |
   | Fixed: tree-sitter-dockerfile / grammar | S03 (G1, G2, G3) |
   | Fixed: PDF | S06 (P1, P2) |
   | Fixed: Architecture report | S06 (P3, L1) |
   | Fixed: integration discovery / detection walk | S07 (C1, C2) |
   | Fixed: Privacy | S08 (PV1); commits `b0477e4`, `cb67480` for the SSH half |
   | Fixed: executive summary | commit `f307a2a` (landed) |
   | Security | S10 (H4) |
   | Dependencies: lockfiles | S10 (H1) |
   | Dependencies: tree-sitter-dockerfile | S03 (G1) |
   | Dependencies: Dependabot | S10 (H4) |

   S09 (T2) changes tests only and has no CHANGELOG line.

4. **Check passes.** Rerun step 1; expected `unreleased-OK`.
5. **History untouched and version consistent:**

   ```bash
   bash -c 'diff <(sed -n "1,/^## \[Unreleased\]/p" CHANGELOG.md) <(git show main:CHANGELOG.md | sed -n "1,/^## \[Unreleased\]/p") &&
   diff <(sed -n "/^## \[0\.3\.1\]/,\$p" CHANGELOG.md) <(git show main:CHANGELOG.md | sed -n "/^## \[0\.3\.1\]/,\$p") &&
   grep -q "^version = \"0.3.1\"" pyproject.toml &&
   grep -q "^__version__ = \"0.3.1\"" src/nfr_review/__init__.py &&
   test "$(grep -m1 -E "^## \[[0-9]" CHANGELOG.md)" = "## [0.3.1] - 2026-06-23"' && echo changelog-history-and-version-OK
   ```

   Expected: `changelog-history-and-version-OK` — `git diff main --
   CHANGELOG.md` touches only `[Unreleased]`, and the newest released
   heading equals the package version.
6. **Commit.** Run
   `python -m pytest -n auto -m regression --timeout=600 tests/regression`
   and `pre-commit run --all-files`; both pass. Then:

   ```bash
   git add CHANGELOG.md
   git commit -m "docs(changelog): record the unreleased PR #255 changes" \
     -m "Typst PDF, Rust support, extras consolidation, detection and required_tech, graphify opt-in and --strict-collectors, the breaking LLM refactor, and the remediation fixes. Version stays 0.3.1." \
     -m "Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S11
   Rows: H3
   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```

**Token check:** `format`.

---

## Task 6 — Slice gate and evidence

**Rows:** H2, H3. **Files:**
`docs/plans/pr255-remediation/evidence/M001-S11.md` (create). **Consumes:**
the outputs of Tasks 1–5. **Produces:** the evidence file named in the ledger
slice.

Steps:

1. **Failing check.**
   `test -f docs/plans/pr255-remediation/evidence/M001-S11.md && echo evidence-present`
   prints nothing now.
2. **Ledger-row greps** (H2 verification, over the row's paths plus the
   pages added in Tasks 3–4). Both must print nothing:

   ```bash
   grep -rniI weasyprint ARCHITECTURE.md docs/dependencies.md docs/install.md scripts/setup-all.sh README.md docs/graphify-guide.md site/src/content/docs
   grep -rniI "openai.*core" ARCHITECTURE.md docs/dependencies.md docs/install.md scripts/setup-all.sh README.md docs/graphify-guide.md site/src/content/docs
   ```

   `CHANGELOG.md` is deliberately outside this grep: its released 0.1.0
   entry names weasyprint as history (restored verbatim in Task 1), and
   `[Unreleased]` names it as removed. `docs/internal/` is not user-facing
   and was reverted to main by S01.
3. Run `discipline` (`jk-standards ledger`), `python scripts/lint_docs.py`
   and `gate` (Validation 3). All pass.
4. Write `docs/plans/pr255-remediation/evidence/M001-S11.md` in the format of
   `evidence/M001-S01.md`: heading `# Evidence — M001/S11`; H2 → the empty output of the
   step 2 greps; H3 → `changelog-history-and-version-OK`, the
   version decision (0.3.1, `[Unreleased]`), the PR-title "v0.5" left for the
   owner per M001-decisions, and any `[Unreleased]` bullets omitted because
   their slice was not `done`; one bullet per token with its result; the date.
5. **Check passes.** Rerun step 1; expected `evidence-present`. Run `format`.
6. **Commit.**

   ```bash
   git add docs/plans/pr255-remediation/evidence/M001-S11.md
   git commit -m "docs(plans): record M001/S11 evidence" \
     -m "Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S11
   Rows: H2, H3
   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```

**Token check:** `gate` (and `discipline`).

---

## Self-review

- **DoD coverage.** DoD 1 → Tasks 2, 3, 4 and the Task 6 step 2 greps
  (weasyprint, removed extras, openai-as-core, plus the Docker "ships LLM
  SDKs" claim). DoD 2 → Task 1 and Task 5 step 5. DoD 3 → Task 5 (each named
  item is a bullet; the failing check greps for each). DoD 4 → the version
  decision above and Task 5 step 5; the PR-title half is the owner's, per
  M001-decisions, and is recorded in evidence.
- **Row coverage.** H2 → Tasks 2, 3, 4 (every path in the row's "Lands in",
  plus `03-the-pipeline.mdx`, `11-ci-cd.mdx` and `docs/graphify-guide.md`
  found while planning). H3 → Tasks 1 and 5 (historical revert, `[Unreleased]`,
  version decision recorded in this plan).
- **Placeholder scan.** No unresolved values. Execution-time facts (the
  `Dockerfile` apt list, S04's exit code, which slices are `done`) each have
  the exact command that reads them.
- **Name consistency.** `graphify.enabled`, `graphify.graph_path`,
  `--strict-collectors`, `llm_integration`, `serialize_bundle`,
  `ProviderUnavailableError`, and the five `rust-*` rule IDs match the code
  and the S04 design.
