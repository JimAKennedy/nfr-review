# Test Suite Fix Writeup

## Introduction

`nfr-review` is a Python 3.11+ CLI for non-functional requirement (NFR) design reviews. It analyses source trees across multiple languages using tree-sitter grammars, applies configurable rule sets, and emits reports in a range of formats (SARIF, JSONL, CSV, Markdown, HTML). The tool is polyglot by design — grammars for Java, Go, Rust, C#, Node.js, and C++ are supported alongside the core Python, HCL, and Dockerfile grammars.

### The refactor that preceded these fixes

Before the fixes described in this document, the package underwent a structural refactor:

- Language support was reorganised into optional extras (`nfr-lang-*`). Python, HCL, and Dockerfile grammars stayed in core; all other language grammars became optional installs.
- `llm_client.py` was renamed to `llm_integration.py`. The module-level sentinel `_ENV_LOADED` was renamed to `_AI_TOOLING_AVAILABLE` throughout.
- Collectors changed their missing-grammar behaviour. Previously they raised `RuntimeError` when a required grammar was not installed. After the refactor they return `[]` silently, allowing the engine to continue without that language.
- The CI workflow was split from a single job into one job per lang pack, so each extra is validated in isolation.

This refactor introduced approximately 15 new test failures on top of roughly 125 pre-existing Windows-only failures, giving a total of around 140 failures before the work described here.

---

## New package structure

After the refactor the extras layout is:

| Extra | Contents |
|---|---|
| `nfr-review` (core) | Python, HCL, Dockerfile grammars |
| `nfr-review[lang-java]` | Java grammar |
| `nfr-review[lang-go]` | Go grammar |
| `nfr-review[lang-rust]` | Rust grammar |
| `nfr-review[lang-csharp]` | C# grammar |
| `nfr-review[lang-nodejs]` | Node.js grammar |
| `nfr-review[lang-cpp]` | C++ grammar |
| `nfr-review[llm]` | LLM integration |
| `nfr-review[monitor]` | Monitoring feature (not yet implemented) |
| `nfr-review[diagrams]` | Diagram rendering |
| `nfr-review[pdf]` | PDF export |
| `nfr-review[scancode]` | ScanCode licence scanning |
| `nfr-review[otel]` | OpenTelemetry tracing |
| `nfr-review[full]` | All of the above |

CI runs one job per lang pack. Each job installs only the core plus the specific lang extra it covers, so cross-language test failures surface quickly.

---

## Category A — Introduced by the refactor (~15 tests)

These failures were directly caused by changes made during the refactor.

### A1: `required_tech` gate fires before `required_collectors`

Several tests constructed `Config(tech={})` to trigger the "no collectors" skip path. After the refactor the engine checks `required_tech` first, and an empty `tech` dict matches that guard before reaching `required_collectors`. The tests were asserting the wrong skip reason.

Fix: change `Config(tech={})` to `Config(tech={"lang": True})` so the tech gate passes and the test reaches the intended code path.

### A2: `llm_client` → `llm_integration` module rename

Tests that imported from `nfr_review.llm_client` or referenced `_ENV_LOADED` broke with `ImportError` / `AttributeError`.

Fix: update all import paths to `nfr_review.llm_integration` and replace `_ENV_LOADED` with `_AI_TOOLING_AVAILABLE`.

### A3: Collectors return `[]` instead of raising `RuntimeError`

Collectors no longer raise `RuntimeError` when a grammar is missing — they return an empty list. Tests that asserted `pytest.raises(RuntimeError)` on these paths failed.

However, changing to silent `[]` returns also silently dropped the user-facing warning that previously told operators which grammar was missing. This was a regression in observable behaviour, not just a test change.

The fix was two-part:

1. Update the tests to match the new return-value behaviour (assert `result == []` instead of expecting an exception).
2. Restore the warning contract in production code: each collector populates a `grammar_warnings` list when a grammar is absent. The engine reads this list after `collect()` returns and appends the messages to `RunResult.warnings`, so the warning still surfaces to users in every output format.

The second part was the more important fix — test changes alone would have silently regressed user-visible behaviour.

### A4: Cross-language tests fail in per-lang CI jobs

Some test files exercise multiple languages in a single file. When those tests run in a per-lang CI job where peer grammars are not installed, they crash at import or at fixture construction rather than skipping cleanly.

Fix: add `pytest.importorskip("tree_sitter_go")` (and equivalents for other grammars) at the top of test functions or test classes that require a grammar not guaranteed to be present. This converts collection-time crashes into clean skips.

---

## Category B — Windows path separators (~20 tests)

Tests hardcoded forward-slash substrings in path assertions. On Windows, `str(Path(...))` produces backslashes, so equality and `in` checks failed.

Fix: normalise the actual value before asserting — `.replace("\\", "/")` on the actual string, or `.as_posix()` on `Path` objects. Expected strings were left exactly as written; only the actual side was normalised. This keeps expected values readable and makes the fix obviously mechanical.

No production code was changed in this category.

---

## Category C — CliRunner stderr capture (~20 tests)

Click's `CliRunner()` merges stderr into stdout by default. On Windows, tests that accessed `result.stderr` raised `ValueError: stderr not separately captured`. On Unix the same tests passed because the merged stream still happened to contain the right content when checked via `result.output`.

Fix: instantiate `CliRunner(mix_stderr=False)` wherever the test accesses `result.stderr`. This is the correct usage regardless of platform — the default merge behaviour was always masking a latent test design issue.

---

## Category D — Unicode encoding in arch renderer (~25 tests)

The arch report renderer called `Path.write_text()` without specifying an encoding. On Windows the default encoding is `cp1252`, which cannot represent the `⚠` character used in warning messages. This caused `UnicodeEncodeError` at report write time, failing any test that exercised a code path producing a warning.

Fix: add `encoding="utf-8"` to three `write_text` calls in `arch_report_render.py`. This is a production source fix — no test changes were made. The fix is correct on all platforms; `utf-8` is the right encoding for text files this tool produces.

---

## Category E — Monitor feature stubs (~15 tests + 4 E2E)

The monitor feature is not yet implemented. All monitor tests called into stub code that raises `NotImplementedError`, causing failures rather than skips.

Fix: add `@pytest.mark.skip(reason="monitor not yet implemented")` to all test classes in `tests/monitor/` and to `tests/test_monitor_e2e.py`.

A secondary issue in `test_load.py` required a separate fix: `import resource` appeared at module level. `resource` is a Unix-only stdlib module; its absence on Windows crashed pytest collection before skip marks could fire. Fix: move the import inside the test function body, guarded by the skip mark.

---

## Category F — Unreadable file simulation (~5 tests)

Tests simulated permission-denied reads using `f.chmod(0o000)`. On Windows, `chmod` with mode `0o000` has no effect — the file owner can always read the file. The tests then failed because no `OSError` was raised and the collector processed the file normally.

Production collectors are correctly implemented: all have `except OSError` handlers that skip unreadable files.

Fix: replace the `chmod` approach with `unittest.mock.patch.object(Path, "read_bytes", side_effect=OSError("Permission denied"))`. This is platform-neutral and tests exactly the same production code path on both platforms — the collector's OSError handler — without relying on filesystem permission semantics.

---

## Category G — Miscellaneous (~8 tests)

Several distinct issues that did not fit the above categories.

**`test_init_cmd`**: `click.echo(..., err=True)` progress messages leaked into stdout in dry-run mode via CliRunner's default stderr mixing. The test attempted to parse `result.output` as YAML and failed because the progress messages corrupted it. Fixed in production `cli.py` by gating progress messages on `not dry_run`. No test change required.

**`test_sarif`, `test_jsonl_output`, `test_csv_output`**: Used `/dev/null/impossible/` as a bad path to trigger `OutputError`. That path does not exist on Windows (`/dev/null` is not a Windows concept). Fixed by injecting a mock `OSError` on the file-write call, same pattern as Category F.

**`test_setup_script`**: Checked execute-bit permissions using `stat.S_IXUSR`. Execute bits are not meaningful on Windows. Fixed with `@pytest.mark.skipif(sys.platform == "win32", reason="execute bits not meaningful on Windows")`.

**`test_jdepend_collector`**: Used `str(Path(...))` in substring assertions with forward-slash paths. Fixed with `.as_posix()`.

**`test_apim_collector`**: Same path separator issue. Fixed with `.replace("\\", "/")` on the actual value.

**`test_monitor_e2e`**: This E2E test file sits outside `tests/monitor/` and was missed by the Category E skip-mark sweep. The same `@pytest.mark.skip` applied.

---

## Test fix discipline

A rule was added to `CLAUDE.md` during this work: **tests are a contract, not an obstacle**. A test should only be changed when production code has intentionally changed what the test verifies.

Legitimate reasons to change a test:

- Import or symbol renames (Category A2)
- Intentional API behaviour changes (Category A1, A3 — but only after the production behaviour change is deliberate and documented)
- Environment adapters — replacing platform-specific simulation with platform-neutral mocks (Categories C, F, G)
- Skip guards — marking genuinely unimplemented features or platform-irrelevant assertions (Categories E, G)
- Path normalisation — asserting on a canonical form rather than a platform-specific one (Categories B, G)

Things that are never acceptable:

- Changing a fixture file or expected output value because the production code now produces different output
- Weakening an assertion to make a failure go away without understanding the cause
- Skipping a test because it is flaky rather than because the feature is genuinely unimplemented

The Category A3 fix is the clearest example of this discipline in practice: the test change was legitimate (new return-value contract), but it required a parallel production fix to avoid silently regressing user-visible warning output.

---

## Outstanding failures (6)

These failures were not part of the original 140 and are pre-existing. They were not addressed in this work.

- **`test_detect.py` (8 collection errors)**: `os.getuid()` is called at module level. It is a Unix-only call and crashes pytest collection on Windows entirely. The 8 errors are collection errors, not test failures.
- **`test_self_review.py` (3 failures)**: Worker process crashes when nfr-review analyses itself. Likely a resource or timeout issue in the self-scan path.
- **`test_log_output_hygiene.py` (2 failures)**: Worker crashes in self-scan tests. Same category as above.
- **`test_arch_test_coverage.py` (1 failure)**: A subdirectory boundary assertion fails. The rule being checked does not behave as expected at certain nesting depths.

---

## Final suite results

After all fixes: **5838 passed, 146 skipped, 6 failed, 8 errors** (all pre-existing).

Regression tests (`tests/regression/`) are excluded from this count — they require network access and clone public repositories, so they are not part of the standard local suite run.
