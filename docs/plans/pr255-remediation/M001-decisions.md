# M001 decisions

Append-only record of every question asked and every choice made on the
user's behalf while running M001 of the PR #255 remediation ledger.

## 2026-11-10 — assessing the programme

- **Q:** Where should the milestones land? — **A:** One milestone on `pr255-fixes`.
- **Q:** Does the 12-slice decomposition work? — **A:** Agree as proposed.
- **Q:** Are the validation tokens, definitions of done and S01 backfill right? — **A:** Agree, write the ledger.

## 2026-11-10 — planning M001/S02–S11 (front-loaded by /jk:auto)

- **Q:** S04: once graphify is opt-in, should `graphifyy` stay a core dependency? — **A:** Keep core; opt-in by config.
- **Q:** S04: how should Container E2E detect a collector crash? — **A:** A new `--strict-collectors` CLI flag.
- **Q:** S10: pin `python:3.14-slim` by digest? — **A:** Pin, and add a `docker` ecosystem to dependabot.
- **Q:** S11: what should the version be? — **A:** Leave 0.3.1; changes go under `[Unreleased]`.
- **Q:** Approve the S04 design and the bounded designs for S02, S03, S05–S11? — **A:** Approve all; run unattended.
- **Decision:** S04 is classified architectural (new config key and CLI flag); design in `M001-S04-design.md`. The others are bounded. — **Why:** interface changes take the heavier path.
- **Decision:** G1 marker is `(sys_platform=='darwin' and platform_machine=='arm64') or (sys_platform=='linux' and platform_machine=='x86_64')`. — **Why:** PyPI lists only those two wheels for tree-sitter-dockerfile 0.2.0, and no sdist.
- **Decision:** L1 calls `client.call()` directly rather than raising the bundle cap. — **Why:** same fix as the summary payload (`f307a2a`), and the profile is already a bounded summary.
- **Decision:** H5 uploads test-llm coverage as its own artifact rather than combining it with test-core's. — **Why:** the jobs run on separate runners; a combine step would need a new job, which widens the slice.
- **Decision:** H1 does not compile the `[llm]` extra. — **Why:** it points at a local `file://` path and is deferred under D1.
- **Decision:** The PR title's "v0.5" is not edited by this run. — **Why:** it is an outward-facing change on the fork's PR; it is recommended in the milestone report instead.

## 2026-11-10 — reviewing the S02–S11 plans

- **Decision:** `unit` and `gate` tokens exclude regression from the unit pytest run (`-m "not regression"`), matching CI's test-core. — **Why:** the committed `unit` text ran the regression suite despite its comment, and `gate` ran it twice; the S04 planner caught it.
- **Decision:** S06/P3 is fixed by threading the config's `llm` block through the `all` command into `run_arch_review`; `arch` keeps its interface. — **Why:** the orchestrator has no config object; adding `--config` to `arch` would be a CLI change outside the row.
- **Decision:** S06/P2 also restores main's `height=1600`. — **Why:** main rendered arch diagrams at scale 4, 2400×1600.
- **Decision:** S07/C1 wires `exclude_test_paths` only through `nfr-review all` (`--include-tests`). — **Why:** `arch` has no such flag; adding one widens the slice.
- **Decision:** S07/C2's pruned walk also skips dot-directories, as approved. — **Why:** matches the AST collectors; no snapshot changes, but a repo whose only Python lives under `.github/` is no longer detected as Python.
- **Decision:** S04 adds a result check for `container-e2e` to `ci-complete`. — **Why:** without it a failing E2E job would not fail CI, so GR1's "E2E fails" outcome would be false.
- **Decision:** S02's closure boundary hides blocking calls inside executor-run closures (e.g. `.map(|x| std::fs::read(x))`), and an `async {}` block in a sync fn is reported with that fn's name. — **Why:** the input asked for exactly this boundary; rule wording is outside R1.
- **Decision:** S10/H5 DoD reworded to "measured and uploaded as its own report"; S11 DoD 4 reworded so the PR-title correction is an owner action. — **Why:** both DoD lines contradicted decisions already recorded above.
- **Decision:** S09 adds an autouse offline-LLM fixture and blocks `.env` loading in tests. — **Why:** with a dummy key, 65 tests made 91 real LLM calls; the main checkout's `.env` could supply a real key.
- **Q:** Regression is red before any slice (gin +2, httpx +1 dep-freshness drift). How to handle it? — **A:** New slice S13; refresh first.
- **Decision:** S13 is placed before S02 and every other open slice depends on it. — **Why:** each owes `regression` or `gate`, both red until the drift is refreshed.

## 2026-11-11 — executing M001/S13

- **Decision:** the S13 refresh kept only the 3 `dep-freshness` lines and dropped 2 duplicate `structure-coupling-cluster` lines the refresh also added. — **Why:** DoD 2 allows only freshness lines; structure rules are graphify reclustering noise the snapshot test ignores, and S04 removes them all. The plan's grep keyed on `dep-freshness` in the line, which `dead-library` findings carry only as `rule_id`; matched by `rule_id` instead.

## 2026-11-11 — executing M001/S02

- **Decision:** Task 2 sets the `RustMutexLockUnwrapRule` class docstring to "Flag .lock()/.read()/.write().unwrap() on std::sync Mutex/RwLock outside test code." rather than the all-clear sentence the plan's wording literally applied to both. — **Why:** the docstring is what `list-rules`/`explain-rule` print as the rule's description, so it must say what the rule flags; the all-clear sentence was meant for `all_clear_summary`.
- **Decision:** Task 2's `test_multiline_receiver_summary_is_single_line` splits its expected-summary literal across two adjacent strings. — **Why:** the plan's single literal is 97 columns and fails `ruff` E501 (limit 95); the asserted value is unchanged.
- **Decision:** Task 2's snapshot refresh kept only the `rust-ast` lines (8 changed: 6 `rust-unwrap-expect` summaries, 2 `rust-mutex-lock-unwrap` all-clear summaries) and dropped the 24 graphify `structure-*` lines the refresh also rewrote. — **Why:** same as the S13 precedent — structure lines are reclustering noise the snapshot test ignores, and the plan's check requires every changed line to come from `rust-ast`.

## 2026-11-11 — executing M001/S03

- **Decision:** the G1 dry-run resolution is recorded in the evidence file at Task 1, not copied in at Task 4. — **Why:** the ledger standard appends evidence per task as it lands; Task 4 then appends only the gate results and the row-to-test map.
- **Decision:** T1 stays `open` after Task 2 and is set `done` at Task 3. — **Why:** both tasks list T1; Task 3 adds the remaining `*records_warning` cases.

## 2026-11-11 — executing M001/S04

- **Decision:** targeted test runs use `-n0` instead of the plan's `-p no:xdist`. — **Why:** `pyproject.toml` `addopts` passes `-n`/`--dist`, so disabling the xdist plugin makes pytest reject those options; `-n0` runs serially with the same effect.
- **Decision:** Task 1 also rewords `docs/graphify-guide.md` §3 item 2 ("reads that `graph.json`") and replaces the nightly-regression lead sentence with the plan's new one, keeping the GitHub Actions "Add Graphify to your nfr-review workflow:" line after the new sentence. — **Why:** the plan's goal for the guide is that it no longer describes reuse of `graphify-out/graph.json`; §3 item 2 still did, and the old nightly sentence would have duplicated the new one.

## 2026-11-11 — executing M001/S05

- **Decision:** W1 stays `open` after Tasks 1 and 2 and is set `done` at Task 3. — **Why:** Tasks 1–3 all list W1; Task 3 adds the structural-baseline half.

## 2026-11-11 — executing M001/S06

- **Decision:** the evidence file is created at Task 1 and appended per task; Task 5 appends the slice-gate results and the row-to-test map instead of writing the file. — **Why:** the ledger standard (and the plan's own evidence rule) appends evidence per task as it lands; same precedent as S03.

## 2026-11-11 — executing M001/S07

- **Decision:** Task 1 adds `exclude_test_paths` to `run_arch_review` after S06's `llm_config` (and its docstring entry after `llm_config:`), not directly after `progress:` as the plan says. — **Why:** the plan predates S06; both are keyword-only, so the order only keeps S06's parameter and docstring pair intact.

## 2026-11-11 — executing M001/S09

- **Decision:** the `CREATE_LLM_CLIENT_SITES` list is the plan's, unchanged. — **Why:** re-derived from the tree after S06/S07: module-level importers are still `collectors.adr_derive`, `output.summarize`, `rules.adr_drift`, `rules.pii_logging`; S06 added no new site (`arch_orchestrator._init_llm_client` imports `create_llm_client` at call time from `nfr_review.llm_integration`, already covered); `test_sites_cover_every_module_level_import` passes.
- **Decision:** S06's `TestArchLlmModelDisclosure` (`tests/test_arch_orchestrator.py`) is left unchanged, with no opt-out marker. — **Why:** its `created_with` fixture monkeypatches `nfr_review.llm_integration.create_llm_client` after the autouse `offline_llm` fixture has run (autouse fixtures are set up first), so its recording fake wins and its assertions keep their intent; `tests/test_arch_orchestrator.py` passes with `ANTHROPIC_API_KEY=dummy`.
- **Decision:** the throwaway tripwire plugin and its logs live in the session scratchpad rather than `/tmp/llm_tripwire/`. — **Why:** the executor environment requires temporary files in its scratchpad; the plugin's content is the plan's verbatim and nothing is committed.

## 2026-11-11 — executing M001/S10

- **Decision:** the lockfiles were compiled with pip-tools 7.5.3 under Python 3.11 from a throwaway venv in the session scratchpad (with `pip<26.2` and `click<8.3`), not with `/opt/homebrew/bin/pip-compile`. — **Why:** the Homebrew binary crashes on import (`cannot import name 'stdlib_pkgs' from 'pip._internal.utils.compat'`, pip 26.2.1), and with `click` 8.5 pip-tools 7.5.3 writes a spurious `--no-index` into the header; the pinned venv runs the same pip-tools version and Python as the plan and the lockfile headers, and the headers come out byte-identical to the originals.
- **Decision:** the evidence file is created at Task 1 and appended per task; Task 4 appends the slice-gate results instead of creating the file, so its `test -f` failing check is moot. — **Why:** the ledger standard (and the plan's own evidence rule) appends evidence per task as it lands; same precedent as S03 and S06.

## 2026-11-11 — executing M001/S11

- **Decision:** the evidence file is created at Task 1 and appended per task; Task 6 appends the slice-gate results instead of creating the file, so its `test -f` failing check is moot. — **Why:** the ledger standard (and the plan's own evidence rule) appends evidence per task as it lands; same precedent as S03, S06 and S10.
- **Decision:** `gate` (format + unit + regression) is run at every task, not only Task 6. — **Why:** the executor brief requires every declared validation token per task; it also covers the repo constraint of regression + pre-commit before each commit.
- **Decision:** the docs say the Claude CLI backend needs the `[llm]` extra, not "no extra" as the plan's README wording had it; install.md's backend table and Option C, and the README "LLM backend" snippets, now include the `pip install` line each backend needs. — **Why:** `llm_integration.py` returns the inert client for every provider when ai-tooling is absent, and ai-tooling (the `ClaudeCliProvider`) comes only from `[llm]`; the docs must not promise behaviour the code lacks.
- **Decision:** ARCHITECTURE.md's `protocols.py` row keeps `LlmClient` as a re-export from ai-tooling (or the stub) instead of dropping it, and lists `Band` as a type alias. — **Why:** `protocols.py` still imports and exports `LlmClient` in `__all__`; `Band` is `Literal[1, 2, 3]`, not a protocol.
- **Decision:** Task 2 also fixes three adjacent stale lines in the same files: dependencies.md `click` `>=8.1` → `>=8.2`, the base image noted as "pinned by digest", and ARCHITECTURE.md's "Tests must mock `nfr_review.llm_client.anthropic`" guidance. — **Why:** each contradicts `pyproject.toml`, the `Dockerfile` or the removed module, and the slice's aim is docs that match the tree.
