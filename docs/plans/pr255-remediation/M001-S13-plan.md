# M001/S13 plan — Regression baseline current

**Slice:** M001/S13 in `docs/plans/pr255-remediation/ledger.md` (row X1)

**Task status**

- [ ] Task 1 — Refresh the drifted `gin` and `httpx` snapshots

**Definition of Done**

- [ ] The regression suite passes on the branch before any other slice's change lands
- [ ] The only snapshot lines that change are time-based `dep-freshness` findings for `gin` and `httpx`

**Validation** (`python` is `.venv/bin/python`)

1. `regression` → `python -m pytest -n auto -m regression --timeout=600 tests/regression`
2. `format` → `pre-commit run --all-files`

## Task 1 — Refresh the drifted `gin` and `httpx` snapshots

Files: `tests/regression/snapshots/` (only the `gin` and `httpx` snapshot files).
Consumes: nothing. Produces: a green regression baseline for every later slice.

1. Failing check: `.venv/bin/python -m pytest -n auto -m regression --timeout=600 tests/regression -k "gin or httpx" -q`
   → 2 failed (`test_regression_snapshot[gin]`, `test_regression_snapshot[httpx]`).
2. Refresh only those two:
   `.venv/bin/python -m pytest -n auto -m regression --timeout=600 tests/regression -k "gin or httpx" --update-snapshots -q`
3. Inspect: `git diff --stat tests/regression/snapshots/` names only the gin and
   httpx snapshot files, and `git diff -U0 tests/regression/snapshots/ | grep '^[+-][^+-]' | grep -vc dep-freshness`
   prints `0`. Any other changed line is a halt: it is not drift, and it is not this slice's to absorb.
4. Passing check: `.venv/bin/python -m pytest -n auto -m regression --timeout=600 tests/regression -q` → 0 failed.
5. `pre-commit run --all-files` → exit 0.
6. Append evidence to `evidence/M001-S13.md`, tick this task, tick the DoD in the
   ledger, set row X1 and the slice `done`, run `jk-standards ledger`, and commit
   with trailers `Plan: docs/plans/pr255-remediation/ledger.md`, `Slice: M001/S13`, `Rows: X1`.

## Self-review

- DoD 1 → step 4. DoD 2 → step 3. Row X1 → steps 3–4 produce its Verification.
- No placeholders; no functions referenced.
