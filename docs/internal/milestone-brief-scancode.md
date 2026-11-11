# Milestone Brief: ScanCode License & Copyright Compliance Integration

**Gathered:** 2026-05-12
**Status:** Ready for planning

## Project Description

Integrate scancode-toolkit (Apache-2.0) as an optional dependency to provide deep
license detection, copyright scanning, and open-source compliance auditing within
nfr-review's hygiene subsystem. This gives nfr-review the ability to answer: "Is
this repository safe to release as open source?"

## Why This Milestone

nfr-review's hygiene rules currently check for *presence* of license metadata
(HYG-DOC-001, HYG-COM-004) but cannot detect:
- Copyleft licenses in the dependency tree (GPL/AGPL contamination)
- Missing or stale NOTICE file entries
- Source files without license headers
- Invalid SPDX expressions in project metadata
- Copyright attribution gaps

These are the checks that legal/compliance teams require before approving an
open-source release. Without them, nfr-review can say "your repo has good hygiene"
but not "your repo is safe to open-source."

scancode-toolkit is the most comprehensive license scanner available (Apache-2.0
licensed, Python-native, 32.5.0 supports Python 3.10+). It uses NLP-based license
detection on file content — not just metadata — catching licenses that pip-licenses
and similar tools miss entirely.

## User-Visible Outcome

### When this milestone is complete, the user can:

- Run `nfr-review hygiene --category license <target>` to get license compliance findings
- Run `nfr-review report <target>` and see license/copyright findings in the combined report
- Install with `pip install nfr-review[scancode]` for full scanning, or skip scancode for a lighter install
- See clear red/amber/green findings for copyleft contamination, missing attributions, and NOTICE staleness

### Entry point / environment

- Entry point: `nfr-review hygiene` and `nfr-review report` CLI commands
- Environment: local dev, CI pipelines
- Live dependencies involved: none (scancode runs fully offline against local files)

## Completion Class

- Contract complete means: unit tests pass with mocked scancode output; rules produce correct findings for known-good and known-bad fixture repos
- Integration complete means: real scancode scans run against fixture repos and produce expected findings; collector gracefully skips when scancode is not installed
- Operational complete means: `nfr-review report` on a real repo (e.g., nfr-review itself) produces accurate license findings in the combined Markdown/CSV/JSONL output

## Final Integrated Acceptance

To call this milestone complete, we must prove:

- `nfr-review hygiene --category license` on a repo with a GPL dependency produces a red finding
- `nfr-review hygiene --category license` on nfr-review itself produces all-green (all deps are permissive)
- `nfr-review report` includes license findings alongside NFR and other hygiene findings
- When scancode-toolkit is not installed, the collector skips gracefully with an informative message

## Architectural Decisions

### Use scancode Python API, not subprocess

**Decision:** Import `scancode.api.get_licenses()` and `scancode.api.get_copyrights()` directly rather than shelling out to the `scancode` CLI.

**Rationale:** The Python API avoids subprocess overhead, gives us direct control over parallelism (we already use `concurrent.futures` in the engine), and produces structured Python objects instead of requiring JSON parsing. The API functions are the same ones the CLI wraps internally.

**Alternatives Considered:**
- `subprocess.run(["scancode", "--license", "--json", ...])` — adds process overhead, requires JSON deserialization, harder to control timeouts per-file. The helm collector uses subprocess because helm is a Go binary; scancode is Python-native so direct import is cleaner.

### scancode as optional dependency with graceful skip

**Decision:** Add `scancode-toolkit>=32.0` as an optional extra (`pip install nfr-review[scancode]`). The collector uses a try/except ImportError guard and skips gracefully when absent.

**Rationale:** scancode-toolkit pulls ~47 transitive dependencies (lxml, pdfminer, beautifulsoup4, etc.). Making it required would bloat the default install for users who don't need license scanning. The graceful-skip pattern matches our existing helm binary check convention.

**Alternatives Considered:**
- Hard requirement — too heavy for users who only want NFR rules
- Separate package (`nfr-review-scancode`) — over-engineering for a single collector; optional extras are the Python convention

### Separate hygiene category "license"

**Decision:** Add a new hygiene category `license` alongside the existing `community`, `ci-automation`, `documentation`, `build-readiness`, and `privacy` categories.

**Rationale:** License compliance is a distinct concern from the existing categories. Users should be able to run just license checks (`--category license`) without the full hygiene suite, and vice versa.

**Alternatives Considered:**
- Merge into existing `documentation` category — conceptually wrong; license compliance is about legal risk, not documentation quality
- Merge into `privacy` — privacy is about PII/tracking, not licensing

---

## Error Handling Strategy

- **scancode not installed:** Collector returns empty evidence list with a logged warning. Rules that depend on the collector are skipped via the engine's collector gate (same as helm binary missing).
- **scancode scan timeout:** Use per-file timeout (configurable, default 120s). Files that timeout are logged as warnings and excluded from results — never block the full scan.
- **Unparseable files:** scancode handles binary/corrupt files internally. The collector logs any files scancode couldn't process and continues.
- **No license detected in a file:** This is not an error — many files (configs, data) legitimately have no license. Rules distinguish between "no license needed" and "license expected but missing" based on file type.

## Risks and Unknowns

- **Scan performance on large repos** — scancode is NLP-heavy; a 5000-file repo could take 3-5 minutes. Mitigation: make the collector opt-in (only runs when scancode is installed), add `--max-depth` and `--timeout` controls, consider caching scan results.
- **intbitset LGPL dependency** — scancode depends on `intbitset` (LGPL-3.0). This is fine for normal use (dynamic import) but would be an issue if we bundled/redistributed scancode. We don't, so this is a documentation-only concern.
- **scancode API stability** — the `scancode.api` module is public API but could change between major versions. Pin to `>=32.0,<34` to limit exposure.
- **False positives on license detection** — scancode's NLP can misidentify code patterns as license text. Mitigation: use `min_score` threshold (default 50) and let users tune via config.

## Existing Codebase / Prior Art

- `src/nfr_review/hygiene/collectors/` — 5 existing hygiene collectors showing the registration pattern
- `src/nfr_review/hygiene/rules/` — 20 existing HYG-* rules showing the evaluation pattern
- `src/nfr_review/hygiene/__init__.py` — `hygiene_collector_registry` and `hygiene_rule_registry`
- `docs/compliance/dependency-licenses.md` — manual point-in-time license inventory (pip-licenses based)
- `NOTICE` — current third-party attribution file
- `ARCHITECTURE.md` — collector/rule contracts and registration pattern

## Scope

### In Scope

- `LicenseScanCollector` using scancode Python API for license + copyright detection
- `HYG-LIC-001`: Copyleft license detection — one rule, two evidence paths: source-file copyleft (always red) and dependency copyleft (red for GPL/AGPL, amber for LGPL)
- `HYG-LIC-002`: NOTICE file completeness — cross-reference scancode findings against NOTICE entries
- `HYG-LIC-003`: License header presence in source files (configurable file extensions)
- `HYG-LIC-004`: SPDX expression validity in pyproject.toml / package.json / pom.xml
- Optional dependency configuration in pyproject.toml (`[scancode]` extra)
- Graceful skip when scancode not installed
- Unit tests with mocked scancode output + integration tests with real scans on fixture repos
- Fixture repos: one with copyleft deps (dirty), one all-permissive (clean)
- Regression snapshot updates for any corpus repos where new rules fire
- Documentation updates (ARCHITECTURE.md, README usage section)

### Out of Scope / Non-Goals

- License compliance for nfr-review's own dependencies (already handled manually in docs/compliance/)
- REUSE/SPDX header enforcement tooling (could be a follow-up)
- License compatibility matrix (GPL+Apache, etc.) — just flag copyleft presence, don't compute compatibility
- Automated NOTICE file generation/repair
- scancode's other capabilities (package detection, URL scanning, etc.)

## Technical Constraints

- scancode-toolkit >=32.0,<34 (Python 3.10+ required; we need 3.11+)
- Must remain an optional dependency — core nfr-review install must not require scancode
- Collector must follow the existing hygiene collector protocol exactly
- Rules must follow the existing hygiene rule pattern (HYG-LIC-### naming)
- Per-file scan timeout to prevent hanging on large binaries

## Integration Points

- `hygiene_collector_registry` — new `license-scan` collector registration
- `hygiene_rule_registry` — 4 new HYG-LIC rules registration
- `cli.py` — `--category license` filter support (already generic, should work automatically)
- `pyproject.toml` — `[project.optional-dependencies]` scancode extra
- `output/markdown.py` — license findings render in the combined report (already generic)

## Testing Requirements

- **Unit tests:** Mock `scancode.api` responses; test each rule with known-good and known-bad evidence payloads
- **Integration tests:** Real scancode scans on fixture repos (skip if scancode not installed via `pytest.importorskip`)
- **Graceful skip test:** Verify collector returns empty evidence when scancode import fails
- **Regression snapshots:** Update any corpus repo snapshots where new rules fire
- **Fixture repos:** Create `tests/fixtures/license-dirty-repo/` (GPL file, missing headers) and `tests/fixtures/license-clean-repo/` (all permissive, headers present)

## Acceptance Criteria

- [ ] `pip install nfr-review[scancode]` installs scancode-toolkit
- [ ] `pip install nfr-review` works without scancode (no import errors)
- [ ] `nfr-review hygiene --category license <dirty-fixture>` produces red/amber findings
- [ ] `nfr-review hygiene --category license <clean-fixture>` produces all-green findings
- [ ] `nfr-review hygiene <target>` without scancode installed skips license collector gracefully
- [ ] `nfr-review report <target>` includes license findings in combined output
- [ ] All existing tests continue to pass (no regressions)
- [ ] ARCHITECTURE.md updated with license-scan collector and HYG-LIC rules

## Suggested Slice Decomposition

1. **S01: Collector + graceful skip** — `LicenseScanCollector` with scancode API, optional import guard, fixture repos, unit tests. Proves the data pipeline works.
2. **S02: Copyleft detection rule (HYG-LIC-001)** — flag GPL/AGPL/LGPL in scan results. Red for strong copyleft, amber for weak (LGPL). This is the highest-value rule.
3. **S03: NOTICE completeness + SPDX validation (HYG-LIC-002, HYG-LIC-004)** — cross-reference scan results against NOTICE file; validate SPDX expressions in project metadata.
4. **S04: License header presence (HYG-LIC-003)** — check source files for license headers. Configurable file extensions.
5. **S05: Integration + docs** — regression snapshot updates, ARCHITECTURE.md, README, combined report verification.

## Resolved Questions

1. **Scan caching between runs:** No caching for the initial milestone. Adds real complexity (file hashing, invalidation, storage) and the collector is already opt-in. Leverage scancode's built-in parallelism via `--processes` / API equivalent instead. Caching can be a follow-up optimization if repeat-run performance becomes a pain point.

2. **Source copyleft vs. dependency copyleft:** HYG-LIC-001 is one rule with two evidence paths. Source-file copyleft is always red (can't release as Apache-2.0). Dependency copyleft is red for GPL/AGPL, amber for LGPL (dynamic linking is typically fine). Separate findings emitted from a single rule — no sub-rule IDs needed.

3. **`min_score` threshold:** Configurable with a default of 50 (scancode's own recommended threshold for "likely a real license match"). Exposed via nfr-review YAML config (`scancode.min_score: 50`) and CLI argument (`--min-score 50`).
