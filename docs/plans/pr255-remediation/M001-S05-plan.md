# M001/S05 implementation plan — Windows locator stability

**Slice:** M001/S05 — Windows locator stability
**Ledger:** docs/plans/pr255-remediation/ledger.md
**Branch:** pr255-fixes
**Rows:** W1, W2


> **Evidence rule (ledger standard):** evidence is appended per task as it lands and never names a commit SHA; the commits are found with `git log --grep="Slice: M001/S05"`. Earlier wording in this plan that asked for SHAs was removed on 2026-11-11 before execution.

## Task status

- [x] Task 1 — W1: normalise baseline locators on load
- [x] Task 2 — W1: issue keys survive the separator change
- [x] Task 3 — W1: structural design baseline file items
- [ ] Task 4 — W2: assert raw locators and add the Windows-path case
- [ ] Task 5 — Slice gate and evidence

## Definition of Done

Copied verbatim from the ledger slice:

- [ ] A baseline and legacy issue markers recorded with `\` locators match the same findings after the forward-slash change
- [ ] No test normalises the locator it is asserting on
- [ ] A test feeds a Windows-style relative path and asserts the raw `/` locator

## Validation

Tokens from `.jk/validations.yml`, expanded. Run every command from the
worktree root with the project venv active (`source .venv/bin/activate`), so
`python` is `.venv/bin/python`.

1. `format` → `pre-commit run --all-files`
2. `unit` → `python -m pytest -n auto -m "not regression" tests/`
3. `regression` → `python -m pytest -n auto -m regression --timeout=600 tests/regression`
4. `gate` →
   `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`

After writing or modifying any `.py` file, run `.venv/bin/ruff format <file>`
on it before committing (CLAUDE.md "Auto-Mode Code Quality").

## Code facts this plan relies on

Verified against `pr255-fixes` at `2a3300b`. Every code block below was
applied to a scratch copy of the tree and run: each new test failed on the
unmodified tree with the failure quoted in its task, and passed with the
change; ruff check and ruff format were clean.

- Commit `e9fdfc6` adds no locator helper. It replaces `str(rel)` with
  `rel.as_posix()` inline at about 60 sites in 36 modules. The one shared
  builder is `BaseASTCollector.collect` in
  `src/nfr_review/collectors/ast_common.py`, which computes
  `rel = src_file.relative_to(repo_path)` and then `rel_posix = rel.as_posix()`
  for the locator. All AST collectors (C#, Java, Python, Go, …) go through it.
  The W2 Windows-path test drives this path through `CSharpAstCollector`,
  whose grammar is installed in `.venv`.
- `src/nfr_review/baseline.py` `load_baseline` reads `record["evidence_locator"]`
  once and derives all three key sets from it: `legacy_keys`, `stable_keys`
  (via `_strip_line_from_locator`) and `hashless_summaries`. Normalising that
  one variable covers every key built from a record locator.
- `src/nfr_review/issues.py`: an issue marker (`<!-- nfr-review:key=… -->`
  or the legacy `<!-- nfr-review:issue:… -->`) stores only
  `sha256(":".join(parts))[:12]` of `_finding_key`'s parts. The locator is
  hashed, not stored, so it **cannot be normalised when the marker is
  parsed**. The approved design said to normalise "wherever legacy issue
  markers are parsed". That is not possible. Instead, each current finding
  also computes the key a Windows run would have written: the same parts with
  `/` turned back into `\`. Issues found under that key are re-keyed before
  the sync decides update/create/close. `_handle_update` then rewrites the
  body with the new key, which migrates the marker. `_finding_key` also
  normalises `\` → `/` before hashing, so old Windows JSONL fed to the sync
  hashes like a current run.
- `scripts/action_issues.py` does not parse markers. It re-exports
  `nfr_review.issues` helpers and calls `sync_issues`, so it picks up the fix
  without any change. `tests/test_action_issues.py` passes against the
  changed `issues.py`.
- Other baseline consumers:
  - `monitor/baseline.py` keys on OTel interaction fingerprints, so it has
    nothing to change.
  - The arch baseline (`structurizr_diff.load_arch_baseline`) keys on DSL
    identifiers from `arch_utils.make_id`, which hashes the component's
    relative path. Like issue markers, these cannot be normalised on load.
    No Windows alias exists for them either: `make_id` hashes the whole name,
    and matching would need every candidate separator spelling of every
    component. **Out of scope.** A Windows arch baseline shows a one-time
    drift for nested `src-`, `ml-` and `nested-` components; report this in
    the evidence.
  - The structural design baseline (`design_change/snapshot.py`) stores
    `schema_migrations` items as `file:<payload.file_path>`. Those are path
    strings and can be normalised on load (Task 3).
  - `adr_titles` items fall back to `file_path` only when an ADR has no
    title. They are left alone: a title could legitimately contain `\`.
- `tests/regression` snapshots contain no baseline or issue-sync output, so
  this slice cannot change them. **Pre-existing drift:** on the unmodified
  tree, `test_regression_snapshot[gin]` (+2 `dep-freshness` findings) and
  `test_regression_snapshot[httpx]` (+1 `dep-freshness` finding) already
  fail. The cause is time-based dependency freshness, not this slice.

---

## Task 1 — W1: normalise baseline locators on load

**Rows:** W1
**Files:**
- Modify `src/nfr_review/models.py`
- Modify `src/nfr_review/baseline.py`
- Modify `tests/test_baseline.py`

**Consumes:** `load_baseline`, `classify_findings`, `_make_finding`, `_write_jsonl`.
**Produces:** `nfr_review.models.normalise_locator(locator: str) -> str`
(public, in `__all__`). `load_baseline` uses it, so every key it builds
carries `/` separators.

### Steps

1. Append to `tests/test_baseline.py`:

   ```python
   # ---- Windows baselines: locators recorded with backslashes ------------------


   class TestWindowsBaselineLocators:
       """Baselines written on Windows before locators used ``/`` still match."""

       def test_backslash_locators_are_normalised_on_load(self, tmp_path: Path) -> None:
           path = tmp_path / "baseline.jsonl"
           _write_jsonl(
               path,
               [
                   _make_finding(evidence_locator="src\\pkg\\a.py:3"),
                   _make_finding(
                       rule_id="R002",
                       evidence_locator="src\\pkg\\b.py:7",
                       content_hash="abc123def456",
                   ),
               ],
           )

           baseline = load_baseline(path)

           assert baseline.legacy_keys == {
               ("R001", "src/pkg/a.py:3", "missing-readme"),
               ("R002", "src/pkg/b.py:7", "missing-readme"),
           }
           assert baseline.stable_keys == {
               ("R002", "src/pkg/b.py", "missing-readme", "abc123def456")
           }
           assert set(baseline.hashless_summaries) == {
               ("R001", "src/pkg/a.py:3", "missing-readme")
           }

       def test_backslash_legacy_key_matches_same_finding(self, tmp_path: Path) -> None:
           path = tmp_path / "baseline.jsonl"
           _write_jsonl(path, [_make_finding(evidence_locator="src\\foo.py:12")])
           current = _make_finding(evidence_locator="src/foo.py:12")

           result = classify_findings([current], load_baseline(path))

           assert result.new == []
           assert result.shifted == []
           assert result.resolved == []

       def test_backslash_stable_key_matches_shifted_finding(self, tmp_path: Path) -> None:
           path = tmp_path / "baseline.jsonl"
           _write_jsonl(
               path,
               [_make_finding(evidence_locator="src\\foo.py:12", content_hash="abc123def456")],
           )
           current = _make_finding(evidence_locator="src/foo.py:15", content_hash="abc123def456")

           result = classify_findings([current], load_baseline(path))

           assert result.new == []
           assert [s.baseline_locator for s in result.shifted] == ["src/foo.py:12"]

       def test_backslash_hashless_entry_matches_moved_finding(self, tmp_path: Path) -> None:
           path = tmp_path / "baseline.jsonl"
           _write_jsonl(path, [_make_finding(evidence_locator="src\\foo.py:12")])
           moved = _make_finding(evidence_locator="src/foo.py:20")

           result = classify_findings([moved], load_baseline(path))

           assert result.new == []
           assert [s.baseline_locator for s in result.shifted] == ["src/foo.py:12"]
           assert result.resolved == []
   ```

   (`test_backslash_stable_key_matches_shifted_finding` deliberately does not
   assert `resolved`. `classify_findings` lists the unmatched legacy key of a
   stable-shifted finding as resolved, as `TestClassifyFindings` already
   shows.)

2. Run and see it fail:
   `.venv/bin/python -m pytest tests/test_baseline.py -k TestWindowsBaselineLocators -q`
   → 4 failed. The load test fails with
   `Extra items in the left set: ('R001', 'src\\pkg\\a.py:3', 'missing-readme')`.
   The three classify tests fail with `assert [Finding(...)] == []` on
   `result.new`.

3. In `src/nfr_review/models.py`, directly after `_strip_line_from_locator`, add:

   ```python
   def normalise_locator(locator: str) -> str:
       """Return *locator* with Windows path separators replaced by ``/``.

       Locators use ``/`` on every platform; records written by earlier Windows
       runs carry ``\\`` and must be normalised before they are compared with
       current findings.
       """
       return locator.replace("\\", "/")
   ```

   and add `"normalise_locator",` after `"compute_content_hash",` in `__all__`.

4. In `src/nfr_review/baseline.py`, change the import to
   `from nfr_review.models import Finding, _strip_line_from_locator, normalise_locator`
   and, in `load_baseline`, directly after
   `locator = record.get("evidence_locator")`, insert:

   ```python
                   if locator is not None:
                       locator = normalise_locator(locator)
   ```

   Every later use (`legacy_keys.add`, `_strip_line_from_locator(locator)` for
   `stable_keys`, `hashless_summaries[...]`) now sees the normalised value.
   Update the `BaselineData` docstring's first bullet to read
   ``- ``legacy_keys``: 3-tuple ``(rule_id, evidence_locator, pattern_tag)``,
   locator normalised to ``/``.``

5. Run and see it pass:
   `.venv/bin/python -m pytest tests/test_baseline.py tests/test_baseline_cli.py tests/test_baseline_diff_cli.py tests/test_baseline_shift_e2e.py -q`
   → all passed.

6. `.venv/bin/ruff format src/nfr_review/models.py src/nfr_review/baseline.py tests/test_baseline.py`, then commit:

   ```
   git add src/nfr_review/models.py src/nfr_review/baseline.py tests/test_baseline.py
   git commit -F - <<'EOF'
   fix(baseline): match Windows baselines recorded with backslash locators

   Locators now use forward slashes on every platform, so a baseline
   written on Windows before that change keyed its findings on
   `src\foo.py:12` and every one of them read as new. load_baseline now
   normalises the record locator before deriving the legacy, stable and
   hashless keys.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S05
   Rows: W1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

7. Check (`unit`, scoped): `.venv/bin/python -m pytest -n auto tests/ -k baseline -q` → 0 failed.

---

## Task 2 — W1: issue keys survive the separator change

**Rows:** W1
**Files:**
- Modify `src/nfr_review/issues.py`
- Modify `tests/test_issues.py`

**Consumes:** `normalise_locator` (Task 1), `_finding_key`, `sync_issues`,
`file_issues`, `_partition_issues`.
**Produces:** in `issues.py`:
- `_key_for_locator(finding, locator) -> str`, the old `_finding_key` body
  parameterised on the locator;
- `_finding_key`, which now normalises before hashing;
- `_windows_finding_key(finding) -> str | None`;
- `_adopt_windows_keys(finding_by_key, *issue_maps) -> None`.

`_finding_fingerprint` stays an alias of `_finding_key`.

### Steps

1. In `tests/test_issues.py`:
   - add `import hashlib` above `from typing import Any`;
   - add `file_issues,` after `_finding_key,` in the `from nfr_review.issues import (...)` list;
   - append:

   ```python
   # ---------------------------------------------------------------------------
   # Windows locators recorded before the forward-slash change
   # ---------------------------------------------------------------------------

   _WINDOWS_LOCATOR = "src\\main\\java\\App.java:42"


   def _windows_key(finding: dict[str, Any]) -> str:
       """The marker key a pre-forward-slash Windows run wrote for *finding*."""
       win = dict(finding, evidence_locator=_WINDOWS_LOCATOR)
       if win.get("content_hash"):
           file_path = "src\\main\\java\\App.java"
           parts = [win["rule_id"], file_path, win["pattern_tag"], win["content_hash"]]
       else:
           parts = [win["rule_id"], _WINDOWS_LOCATOR, win["pattern_tag"]]
       return hashlib.sha256(":".join(parts).encode()).hexdigest()[:12]


   class TestWindowsLocatorKeys:
       def test_finding_key_ignores_separator_style(self) -> None:
           windows = dict(_RED_CRITICAL, evidence_locator=_WINDOWS_LOCATOR)
           assert _finding_key(windows) == _finding_key(_RED_CRITICAL)

       def test_finding_key_ignores_separator_style_with_content_hash(self) -> None:
           posix = dict(_RED_CRITICAL, content_hash="abc123def456")
           windows = dict(posix, evidence_locator=_WINDOWS_LOCATOR)
           assert _finding_key(windows) == _finding_key(posix)

       def test_open_issue_with_windows_marker_is_updated_not_duplicated(self) -> None:
           issues = [_issue_json(42, _make_body_with_key(_windows_key(_RED_CRITICAL)))]

           with (
               patch("nfr_review.issues._fetch_nfr_issues", return_value=issues),
               patch("nfr_review.issues._gh_run") as gh,
           ):
               gh.return_value = _gh_result()
               results = sync_issues([_RED_CRITICAL], "owner/repo", rag_min="red")

           assert [r["action"] for r in results] == ["update"]
           edit_args = gh.call_args[0][0]
           assert edit_args[:3] == ["issue", "edit", "--repo"]
           new_body = edit_args[edit_args.index("--body") + 1]
           assert f"{_KEY_MARKER_PREFIX}{_finding_key(_RED_CRITICAL)}{_MARKER_SUFFIX}" in new_body

       def test_hashed_finding_with_windows_marker_is_updated(self) -> None:
           finding = dict(_RED_CRITICAL, content_hash="abc123def456")
           issues = [_issue_json(42, _make_body_with_key(_windows_key(finding)))]

           with (
               patch("nfr_review.issues._fetch_nfr_issues", return_value=issues),
               patch("nfr_review.issues._gh_run") as gh,
           ):
               gh.return_value = _gh_result()
               results = sync_issues([finding], "owner/repo", rag_min="red")

           assert [r["action"] for r in results] == ["update"]

       def test_manually_closed_issue_with_windows_marker_is_not_refiled(self) -> None:
           issues = [
               _issue_json(42, _make_body_with_key(_windows_key(_RED_CRITICAL)), state="CLOSED")
           ]

           with (
               patch("nfr_review.issues._fetch_nfr_issues", return_value=issues),
               patch("nfr_review.issues._issue_has_tool_close_comment", return_value=False),
               patch("nfr_review.issues._gh_run") as gh,
           ):
               gh.return_value = _gh_result()
               results = sync_issues([_RED_CRITICAL], "owner/repo", rag_min="red")

           assert [(r["action"], r["reason"]) for r in results] == [("skip", "manually closed")]

       def test_file_issues_skips_finding_with_windows_marker(self) -> None:
           with (
               patch("nfr_review.issues._ensure_labels"),
               patch(
                   "nfr_review.issues.find_existing_issues",
                   return_value={_windows_key(_RED_CRITICAL)},
               ),
               patch("nfr_review.issues._gh_run") as gh,
           ):
               results = file_issues([_RED_CRITICAL], "owner/repo")

           assert [r["status"] for r in results] == ["skipped"]
           gh.assert_not_called()
   ```

   `_windows_key` spells out the hash recipe on purpose, so the test pins the
   exact key an old Windows run wrote, independent of the code under test.

2. Run and see it fail:
   `.venv/bin/python -m pytest tests/test_issues.py -k TestWindowsLocatorKeys -q`
   → 6 failed:
   - the two key tests fail with `AssertionError: assert '<hash>' == '<hash>'`;
   - the open-issue test fails with `assert ['create', 'close'] == ['update']`
     (today the sync files a duplicate and closes the original);
   - the hashed-finding test fails the same way;
   - the closed-issue test fails with
     `[('create', 'new finding')] == [('skip', 'manually closed')]`;
   - the `file_issues` test fails with `['error'] == ['skipped']`.

3. In `src/nfr_review/issues.py`, replace the whole `def _finding_key(...)`
   function (keep the `_finding_fingerprint = _finding_key` alias line after
   it) with:

   ```python
   def _key_for_locator(finding: dict[str, Any], locator: str) -> str:
       """Hash *finding*'s identity using *locator* as its evidence locator."""
       from nfr_review.models import _strip_line_from_locator

       content_hash = finding.get("content_hash", "")
       if content_hash:
           parts = [
               finding.get("rule_id", ""),
               _strip_line_from_locator(locator),
               finding.get("pattern_tag", ""),
               content_hash,
           ]
       else:
           parts = [
               finding.get("rule_id", ""),
               locator,
               finding.get("pattern_tag", ""),
           ]
       return hashlib.sha256(":".join(parts).encode()).hexdigest()[:12]


   def _finding_key(finding: dict[str, Any]) -> str:
       from nfr_review.models import normalise_locator

       return _key_for_locator(finding, normalise_locator(finding.get("evidence_locator", "")))


   def _windows_finding_key(finding: dict[str, Any]) -> str | None:
       """Return the key a pre-forward-slash Windows run wrote for *finding*.

       Windows runs recorded ``\\``-separated locators before locators were
       normalised to ``/``, and an issue marker stores only the hash, so the old
       key is recomputed rather than parsed.  Returns None when the locator has
       no separator, because then both keys are identical.
       """
       from nfr_review.models import normalise_locator

       locator = normalise_locator(finding.get("evidence_locator", ""))
       if "/" not in locator:
           return None
       return _key_for_locator(finding, locator.replace("/", "\\"))
   ```

   (The imports stay function-local, as the original `_finding_key`'s was.)

4. Directly after `_dedup_marker`, before the `# Filtering` banner, add:

   ```python
   def _adopt_windows_keys(
       finding_by_key: dict[str, dict[str, Any]],
       *issue_maps: dict[str, dict[str, Any]],
   ) -> None:
       """Re-key issues whose marker was written by a pre-forward-slash Windows run.

       Each issue found under a finding's Windows key is moved to its current key,
       so the sync updates it (rewriting the marker) instead of filing a duplicate
       and closing the original.
       """
       for key, finding in finding_by_key.items():
           legacy = _windows_finding_key(finding)
           if legacy is None:
               continue
           for by_key in issue_maps:
               if key not in by_key and legacy in by_key:
                   by_key[key] = by_key.pop(legacy)
   ```

5. In `sync_issues`, directly after
   `open_by_key, closed_by_key, all_issues = _partition_issues(repo)`, add
   `_adopt_windows_keys(finding_by_key, open_by_key, closed_by_key)`.
   In `file_issues`, change `if fp in existing_fps:` to
   `if fp in existing_fps or _windows_finding_key(finding) in existing_fps:`.

6. Run and see it pass:
   `.venv/bin/python -m pytest tests/test_issues.py tests/test_action_issues.py -q` → all passed.

7. `.venv/bin/ruff format src/nfr_review/issues.py tests/test_issues.py`, then commit:

   ```
   git add src/nfr_review/issues.py tests/test_issues.py
   git commit -F - <<'EOF'
   fix(issues): keep Windows-filed issues matched after the locator change

   An issue marker stores only a hash of the locator, so markers written
   by Windows runs before locators used forward slashes cannot be
   normalised when parsed. The sync now also computes each finding's
   pre-change Windows key and re-keys a matching open or closed issue,
   which is then updated (migrating its marker) instead of being closed
   and filed again. _finding_key normalises separators before hashing,
   and the legacy file_issues path accepts the Windows key as well.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S05
   Rows: W1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

8. Check (`unit`, scoped): `.venv/bin/python -m pytest -n auto tests/ -k "issue" -q` → 0 failed.

---

## Task 3 — W1: structural design baseline file items

**Rows:** W1
**Files:**
- Modify `src/nfr_review/design_change/snapshot.py`
- Modify `tests/test_design_change.py`

**Consumes:** `normalise_locator` (Task 1), `load_baseline`/`save_baseline`
(structural), and the test helpers `_make_baseline` and `_make_category`.
**Produces:** `_FILE_ITEM_PREFIX = "file:"` and
`_normalise_file_items(data: dict[str, Any]) -> None` in `snapshot.py`.
They are called by `load_baseline` before validation.

### Steps

1. Append to `tests/test_design_change.py`:

   ```python
   class TestStructuralBaselineWindowsPaths:
       """Structural baselines saved by Windows runs before paths used ``/``."""

       def test_backslash_file_items_are_normalised_on_load(self, tmp_path: Path) -> None:
           cat = _make_category(
               "schema_migration",
               sets={
                   "schema_migrations": [
                       "file:db\\migrations\\V1__init.sql",
                       "tool:flyway",
                   ]
               },
           )
           path = tmp_path / "baseline.json"
           save_baseline(_make_baseline(metrics={"schema_migration": cat}), path)

           loaded = load_baseline(path)

           items = loaded.metrics["schema_migration"].set_metrics["schema_migrations"].items
           assert items == ["file:db/migrations/V1__init.sql", "tool:flyway"]

       def test_items_without_file_prefix_are_left_alone(self, tmp_path: Path) -> None:
           cat = _make_category("api", sets={"api_endpoints": ["GET /a\\b"]})
           path = tmp_path / "baseline.json"
           save_baseline(_make_baseline(metrics={"api": cat}), path)

           loaded = load_baseline(path)

           assert loaded.metrics["api"].set_metrics["api_endpoints"].items == ["GET /a\\b"]
   ```

2. Run and see it fail:
   `.venv/bin/python -m pytest tests/test_design_change.py -k TestStructuralBaselineWindowsPaths -q`
   → 1 failed, 1 passed. The failure is
   `At index 0 diff: 'file:db\\migrations\\V1__init.sql' != 'file:db/migrations/V1__init.sql'`.
   The second test is a guard and passes before and after.

3. In `src/nfr_review/design_change/snapshot.py`:
   - add `from typing import Any` after `from pathlib import Path`;
   - after the `design_change.models` import block, add:

   ```python
   from nfr_review.models import normalise_locator

   # Set-metric items with this prefix carry a repo-relative file path.
   _FILE_ITEM_PREFIX = "file:"


   def _normalise_file_items(data: dict[str, Any]) -> None:
       """Rewrite ``file:`` set-metric items recorded with ``\\`` to use ``/``.

       Baselines saved by Windows runs before paths were normalised hold
       backslash paths; without this, every such item reads as removed and
       re-added on the next diff.
       """
       for category in (data.get("metrics") or {}).values():
           for metric in (category.get("set_metrics") or {}).values():
               metric["items"] = [
                   normalise_locator(item) if item.startswith(_FILE_ITEM_PREFIX) else item
                   for item in metric.get("items", [])
               ]
   ```

   - in `load_baseline`, add `_normalise_file_items(data)` on the line before
     `return StructuralBaseline.model_validate(data)`.

4. Run and see it pass:
   `.venv/bin/python -m pytest tests/test_design_change.py -q` → all passed.

5. `.venv/bin/ruff format src/nfr_review/design_change/snapshot.py tests/test_design_change.py`, then commit:

   ```
   git add src/nfr_review/design_change/snapshot.py tests/test_design_change.py
   git commit -F - <<'EOF'
   fix(design-change): normalise Windows file paths in structural baselines

   schema_migrations items are stored as file:<path>; a structural
   baseline saved on Windows before paths used forward slashes would
   report every migration as removed and re-added. load_baseline now
   normalises file: items before validation.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S05
   Rows: W1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

6. Check (`unit`, scoped): `.venv/bin/python -m pytest -n auto tests/test_design_change.py -q` → 0 failed.

---

## Task 4 — W2: assert raw locators and add the Windows-path case

**Rows:** W2
**Files (12 modified test modules, one of which also gains the new case):**
- `tests/test_nodejs_deps_collector.py`
- `tests/test_deps_path_filter.py`
- `tests/test_exclude_paths_integration.py`
- `tests/test_python_deps_collector.py`
- `tests/test_rust_deps_collector.py`
- `tests/test_java_deps_collector.py`
- `tests/test_proto_collector.py`
- `tests/test_apim_collector.py`
- `tests/test_csharp_ast_collector.py`
- `tests/test_go_deps_collector.py`
- `tests/test_path_filter.py`
- `tests/test_path_filter_integration.py`

**Consumes:** `BaseASTCollector.collect` via `CSharpAstCollector` and the
`collector` fixture in `tests/test_csharp_ast_collector.py`.
**Produces:** raw-value assertions, and
`TestWindowsRelativePath.test_windows_relative_path_gives_forward_slash_locator`.

### Occurrences and verdicts

`grep -rnF '.replace("\\", "/")' tests` at `2a3300b` returns these 18 hits.
Line numbers were taken from that output.

| # | Location | What is normalised | Verdict → replacement |
|---|---|---|---|
| 1 | `test_nodejs_deps_collector.py:309` | `source_file` (under test) | change → `assert deps[0]["source_file"] == "packages/core/package.json"` |
| 2 | `test_deps_path_filter.py:73` | `manifest_files_found` (under test) | change → delete the `norm_manifest_files = …` line and assert `"requirements.txt" in manifest_files` and `"tests/fixtures/sample/requirements.txt" in manifest_files` |
| 3–7 | `test_exclude_paths_integration.py:102, 141, 210, 227, 269` | `Evidence.locator` (under test) | change each → `locators = [e.locator for e in evidence]` |
| 8 | `test_python_deps_collector.py:259` | `source_file` | change → `assert deps[0]["source_file"] == "requirements/requirements.txt"` |
| 9 | `test_rust_deps_collector.py:175` | `source_file` | change → `assert deps[0]["source_file"] == "crates/core/Cargo.toml"` |
| 10 | `test_java_deps_collector.py:496` | `source_file` | change → `assert deps[0]["source_file"] == "module-a/pom.xml"` |
| 11 | `test_proto_collector.py:55` | `Evidence.locator` | change → `assert results[0].locator == "api/svc.proto"` |
| 12 | `test_apim_collector.py:132` | payload `file_path` | change → `assert evidence[0].payload["file_path"] == "policies/test.xml"` |
| 13 | `test_csharp_ast_collector.py:85` | `Evidence.locator` | change → `assert results[0].locator == "src/main.cs"` |
| 14 | `test_go_deps_collector.py:326` | `source_file` | change → `assert deps[0]["source_file"] == "cmd/server/go.mod"` |
| 15–16 | `test_path_filter.py:293, 308` | the test's own `str(f.relative_to(tmp_path))` of the `Path` objects `iter_repo_files` returns. The value under test is a set of `Path`s, not a locator, so this is not a cancelled fix. | keep the semantics; rewrite each → `rel_paths = {f.relative_to(tmp_path).as_posix() for f in files}` (same result on every OS, no grep hit) |
| 17 | `test_path_filter_integration.py:79` | `Finding.evidence_locator` | change → delete `norm = …`; assert `not f.evidence_locator.startswith("tests/")` and `f.evidence_locator.startswith("src/")` (keep the existing messages) |
| 18 | `test_path_filter_integration.py:102` | `Finding.evidence_locator` | change → `locators = {f.evidence_locator for f in non_green}` |

The `==` forms in rows 1, 8–10 and 14 tighten `in` to equality. Each
fixture has exactly one manifest, at that relative path, and the scratch run
of all 12 modules passed with these edits.

### Steps

1. Append the new case to `tests/test_csharp_ast_collector.py`, and change
   its import to `from pathlib import Path, PureWindowsPath`:

   ```python
   class TestWindowsRelativePath:
       """A Windows-style relative path still yields a ``/``-separated locator."""

       def test_windows_relative_path_gives_forward_slash_locator(
           self, collector: CSharpAstCollector, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           src = tmp_path / "src" / "app"
           src.mkdir(parents=True)
           (src / "main.cs").write_text("class Y {}\n")
           real_relative_to = Path.relative_to

           def windows_relative_to(self: Path, *other: Path) -> PureWindowsPath:
               return PureWindowsPath(*real_relative_to(self, *other).parts)

           monkeypatch.setattr(Path, "relative_to", windows_relative_to)
           assert str((tmp_path / "src" / "app" / "main.cs").relative_to(tmp_path)) == (
               "src\\app\\main.cs"
           )
           results = collector.collect(tmp_path, config=None)
           monkeypatch.undo()

           assert [e.locator for e in results] == ["src/app/main.cs"]
   ```

   While patched, `relative_to` returns a `PureWindowsPath`, exactly what it
   returns on Windows, and the in-test assertion proves the patch took
   effect. The fix is already on the branch (`e9fdfc6`), so this case is a
   lock and passes immediately. Step 2 proves it would catch a regression.

2. Prove the new case bites. Temporarily change `locator=rel_posix,` to
   `locator=str(rel),` in `BaseASTCollector.collect`
   (`src/nfr_review/collectors/ast_common.py`), then run
   `.venv/bin/python -m pytest tests/test_csharp_ast_collector.py -k TestWindowsRelativePath -q`.
   Expect 1 failed, `['src\\app\\main.cs'] == ['src/app/main.cs']`.
   Revert with `git checkout -- src/nfr_review/collectors/ast_common.py`, rerun,
   and expect 1 passed. Do not commit the mutation.

3. Apply the 18 replacements in the table above.

4. Run: `grep -rnF '.replace("\\", "/")' tests` → no output (exit status 1).

5. Run and see it pass:
   `.venv/bin/python -m pytest -n auto tests/test_nodejs_deps_collector.py tests/test_deps_path_filter.py tests/test_exclude_paths_integration.py tests/test_python_deps_collector.py tests/test_rust_deps_collector.py tests/test_java_deps_collector.py tests/test_proto_collector.py tests/test_apim_collector.py tests/test_csharp_ast_collector.py tests/test_go_deps_collector.py tests/test_path_filter.py tests/test_path_filter_integration.py -q`
   → 0 failed.

6. `.venv/bin/ruff format` the 12 files listed above, then commit:

   ```
   git add tests/test_nodejs_deps_collector.py tests/test_deps_path_filter.py \
     tests/test_exclude_paths_integration.py tests/test_python_deps_collector.py \
     tests/test_rust_deps_collector.py tests/test_java_deps_collector.py \
     tests/test_proto_collector.py tests/test_apim_collector.py \
     tests/test_csharp_ast_collector.py tests/test_go_deps_collector.py \
     tests/test_path_filter.py tests/test_path_filter_integration.py
   git commit -F - <<'EOF'
   test: assert raw forward-slash locators

   Sixteen assertions normalised the locator under test with
   .replace("\\", "/"), which cancelled the very property the
   forward-slash change guarantees; they now assert the raw value. Two
   more normalised the test's own str() of returned Paths and now use
   as_posix(). A new case feeds BaseASTCollector a Windows-style relative
   path and asserts the locator is src/app/main.cs.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S05
   Rows: W2

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

7. Check (`unit`, scoped): step 5's command → 0 failed, and step 4's grep → no output.

---

## Task 5 — Slice gate and evidence

**Rows:** W1, W2
**Files:** create `docs/plans/pr255-remediation/evidence/M001-S05.md`
**Consumes:** the Task 1–4 commits.
**Produces:** the slice's evidence record.

### Steps

1. `format`: `pre-commit run --all-files`. Expect every hook to pass. If a
   hook rewrites a file, re-stage it, amend it into the commit that last
   touched that file, and re-run until clean.
2. `unit`: `python -m pytest -n auto -m "not regression" tests/` → 0 failed.
3. `regression`: `python -m pytest -n auto -m regression --timeout=600 tests/regression`.
   This slice changes no collector or rule output, so it must introduce **no**
   snapshot diff. Compare the failures with the pre-existing drift in "Code
   facts". If the only mismatches are the `dep-freshness` additions for `gin`
   and `httpx`, they are not caused by this slice. Do **not** refresh them
   here: record them in the evidence and report them as a blocker to the
   caller. Any other mismatch is a bug in this slice: fix it, don't refresh.
4. `gate`: `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`.
   It is green only once the pre-existing `gin`/`httpx` drift has been
   resolved, which is outside this slice. Record the result either way.
5. Write `docs/plans/pr255-remediation/evidence/M001-S05.md` in the layout of
   `evidence/M001-S01.md`:
   - heading `# Evidence — M001/S05`, section `## M001/S05 — Windows locator stability`;
   - the locking test classes: `TestWindowsBaselineLocators`,
     `TestWindowsLocatorKeys`, `TestStructuralBaselineWindowsPaths` and
     `TestWindowsRelativePath`;
   - the step 4 grep of Task 4 returning nothing;
   - the observed `format` / `unit` / `regression` / `gate` results, with
     counts copied from the output;
   - the out-of-scope note: Windows arch baselines (`--arch-baseline-dir`)
     show a one-time drift for nested components, because `make_id` hashes the
     relative path;
   - the date.

   Record only identifiers that appear in command output.
6. Commit:

   ```
   git add docs/plans/pr255-remediation/evidence/M001-S05.md
   git commit -F - <<'EOF'
   docs(plans): record M001/S05 evidence

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S05
   Rows: W1, W2

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

7. Check (`gate`): the step 4 run on the head commit, with its outcome as recorded.

---

## Self-review

- **DoD coverage:**
  - DoD 1 (a baseline and legacy issue markers with `\` locators match) →
    Task 1 `TestWindowsBaselineLocators` (legacy, stable and hashless keys)
    and Task 2 `TestWindowsLocatorKeys`. The latter covers new-format and
    legacy markers through `_extract_key`, both open and closed issues, and
    the legacy `file_issues` path. Task 3 extends the same guarantee to
    structural baselines.
  - DoD 2 (no test normalises the locator it asserts on) → Task 4 table and
    step 4 grep.
  - DoD 3 (Windows-style relative path → raw `/` locator) → Task 4
    `TestWindowsRelativePath`, with mutation proof in step 2.
- **Row coverage:**
  - W1 "Cases in `tests/test_baseline.py` and `tests/test_issues.py` loading
    `\`-locator records and asserting a match" → Task 1 step 1 and Task 2
    step 1.
  - W2 "`grep` for that pattern over `tests/` returns no assertion-side hits;
    new Windows-path case passes" → Task 4 steps 4 and 5.
  - Evidence for both → Task 5.
- **Placeholder scan:** no TBD/TODO. `<SHA>` appears only in Task 5 as an
  instruction to copy values from `git log` output. `<hash>` in Task 2 step 2
  stands for runtime hash values in pytest output. Nothing is a value this
  plan asserts.
- **Name consistency:**
  - Defined by this plan: `normalise_locator` (Task 1), `_key_for_locator`,
    `_windows_finding_key`, `_adopt_windows_keys` (Task 2),
    `_FILE_ITEM_PREFIX`, `_normalise_file_items` (Task 3), `_windows_key`,
    `_WINDOWS_LOCATOR` and `TestWindowsRelativePath` (tests).
  - Already exist: `_strip_line_from_locator`, `load_baseline` (both
    modules), `classify_findings`, `_make_finding`, `_write_jsonl`,
    `_finding_key`, `sync_issues`, `file_issues`, `find_existing_issues`,
    `_ensure_labels`, `_issue_has_tool_close_comment`, `_partition_issues`,
    `_issue_json`, `_make_body_with_key`, `_gh_result`, `_RED_CRITICAL`,
    `_KEY_MARKER_PREFIX`, `_MARKER_SUFFIX`, `_make_baseline`,
    `_make_category`, `save_baseline`, `CSharpAstCollector`, and the
    `collector` fixture.
