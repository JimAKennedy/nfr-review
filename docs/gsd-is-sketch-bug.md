# GSD Bug: `gsd_plan_slice` never clears `is_sketch` flag

**Discovered:** 2026-05-08 during M006 auto-mode execution
**Status:** Pending investigation — need to verify against upstream before filing

## Summary

`gsd_plan_slice` writes plan files and task plans to disk but never clears the
`is_sketch` database flag. This causes `deriveStateFromDb()` to perpetually
return `phase: 'refining'`, trapping auto-mode in an infinite dispatch loop
where it repeatedly attempts to plan an already-planned slice.

## Reproduction

1. Start a milestone with progressive planning (creates slices with `is_sketch = 1`)
2. Run `/gsd auto` — auto-mode dispatches a "refine-slice" unit
3. `gsd_plan_slice` writes all plan files successfully
4. `is_sketch` remains `1` in the DB
5. `deriveStateFromDb()` returns `phase: 'refining'`
6. Auto-dispatch matches "refining -> refine-slice" again
7. Loop repeats indefinitely, burning context windows

## Root Cause Analysis

### Primary: `upsertSlicePlanning()` has no `is_sketch` UPDATE

`gsd-db.ts` around lines 2307-2326 — the `upsertSlicePlanning()` function
writes slice and task planning data but its SQL has no clause to set
`is_sketch = 0` after successful planning.

### Dead code: `autoHealSketchFlags()` never called

`gsd-db.ts` around lines 2295-2305 — a function exists that would clear
`is_sketch` for slices that have plan files, but it is never called from any
production code path. It is only referenced in tests.

### State derivation trusts `is_sketch` blindly

`state.ts` around line 734 — `deriveStateFromDb()` checks `is_sketch` in the
DB and returns `phase: 'refining'` whenever it is `1`, regardless of whether
plan files exist on disk. The DB is authoritative; the filesystem is not
consulted.

### Contributing: stale CONTINUE.md files

`register-hooks.ts` around line 256 — context compaction creates
`*-CONTINUE.md` files that can tell auto-mode to "resume refining" a phase
that already completed. These are never cleaned up after a session ends.
With worktree isolation, they can exist in both `.gsd/milestones/` and
`.gsd/worktrees/<MID>/.gsd/milestones/`.

## Proposed Fix (one line)

In `plan-slice.ts`, after the `upsertSlicePlanning()` call (around line 181):

```typescript
setSliceSketchFlag(params.milestoneId, params.sliceId, false);
```

`setSliceSketchFlag` is already imported and available in that file. The
function exists, its test exists — it just never gets called from production
code.

## Current Workaround

Manual sqlite3 command after each `gsd_plan_slice` on a sketch slice:

```sql
UPDATE slices SET is_sketch = 0
WHERE milestone_id = '<MID>' AND id = '<SID>';
```

A defensive pre-flight script is documented in `.gsd/KNOWLEDGE.md` (K001)
that checks and auto-fixes this before `/gsd auto` restarts.

## Before Filing Upstream

- [ ] Verify this isn't a local installation issue (custom patches, outdated version, etc.)
- [ ] Check if the issue exists in the latest upstream GSD release
- [ ] Confirm `autoHealSketchFlags()` is still dead code in upstream
- [ ] Confirm `upsertSlicePlanning()` still lacks `is_sketch` update in upstream
- [ ] Check if there's an existing issue or PR for this
- [ ] Test the one-line fix locally to confirm it resolves the loop
