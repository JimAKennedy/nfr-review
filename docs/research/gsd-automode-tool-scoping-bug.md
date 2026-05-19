# GSD Auto-Mode Tool Scoping Bug

**Date observed:** 2026-05-18
**Status:** Open / workaround: restart GSD and resume auto-mode

## Symptom

Auto-mode stops with:

```
Auto-mode stopped — Provider "claude-code" cannot run auto-mode for complete-slice:
this unit requires gsd_slice_complete, gsd_task_reopen, gsd_replan_slice, but the
active runtime toolset currently exposes only Skill, ask_user_questions, bash, bg_shell,
capture_thought, edit, gsd_checkpoint_db, gsd_decision_save, gsd_exec, gsd_exec_search,
gsd_milestone_status, gsd_resume, gsd_task_complete, memory_query, read, write.
```

## Root Cause Analysis

GSD auto-mode scopes the active toolset **per unit type** before dispatch. When it runs
an `execute-task` unit, it narrows the toolset to only `gsd_task_complete` +
`gsd_decision_save` + the base tools. When the next unit is `complete-slice` (which
needs `gsd_slice_complete`, `gsd_task_reopen`, `gsd_replan_slice`), the **pre-flight
check runs against the still-narrowed toolset** from the previous unit — and those
tools aren't in it.

The restore function (`restoreGsdWorkflowTools`) is supposed to widen the toolset back
before the next unit's pre-flight check, but it's not firing in time.

## Why ~/.claude/CLAUDE.md ToolSearch instructions don't help

The ToolSearch instructions in `~/.claude/CLAUDE.md` are for Claude Code's interactive
LLM sessions — they load deferred MCP tool schemas so the LLM can call them. But this
error happens **before** Claude Code is even invoked — it's GSD's own pre-flight
capability gate in `phases.js`, checking `pi.getActiveTools()` at the GSD runtime layer.

## Key files in GSD engine

- **`register-hooks.js:97-161`** — `buildMinimalAutoGsdToolSet()` and
  `applyMinimalGsdToolSurface()`
- **`register-hooks.js:225-233`** — `restoreGsdWorkflowTools()` (the restore that
  should widen the toolset back)
- **`phases.js:1473-1484`** — the pre-flight check that reads the stale narrowed toolset

## Possible fixes (in GSD itself)

1. Ensure `restoreGsdWorkflowTools()` fires before the next unit's pre-flight check
2. Have the pre-flight check validate against the full `MCP_WORKFLOW_TOOL_SURFACE`
   rather than the currently-scoped `pi.getActiveTools()`

## Current workaround

Restart GSD and resume auto-mode (`/gsd auto`). The fresh session starts with the full
toolset, so the complete-slice unit succeeds on retry.
