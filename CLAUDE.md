# CLAUDE.md

## GSD Tool Loading

Claude Code defers loading MCP tool schemas to save context. GSD-workflow tools are
operational (not optional), so they must be loaded before use. **At the start of every
session where you need to perform GSD operations**, run ToolSearch to load the schemas
for these tool groups:

```
ToolSearch query: "select:mcp__gsd-workflow__gsd_task_complete,mcp__gsd-workflow__gsd_slice_complete,mcp__gsd-workflow__gsd_complete_task,mcp__gsd-workflow__gsd_complete_slice"
ToolSearch query: "select:mcp__gsd-workflow__gsd_task_reopen,mcp__gsd-workflow__gsd_reopen_task,mcp__gsd-workflow__gsd_slice_reopen,mcp__gsd-workflow__gsd_reopen_slice"
ToolSearch query: "select:mcp__gsd-workflow__gsd_milestone_complete,mcp__gsd-workflow__gsd_complete_milestone,mcp__gsd-workflow__gsd_milestone_reopen,mcp__gsd-workflow__gsd_reopen_milestone"
ToolSearch query: "select:mcp__gsd-workflow__gsd_replan_slice,mcp__gsd-workflow__gsd_slice_replan,mcp__gsd-workflow__gsd_reassess_roadmap,mcp__gsd-workflow__gsd_roadmap_reassess"
ToolSearch query: "select:mcp__gsd-workflow__gsd_plan_milestone,mcp__gsd-workflow__gsd_plan_slice,mcp__gsd-workflow__gsd_plan_task,mcp__gsd-workflow__gsd_skip_slice"
ToolSearch query: "select:mcp__gsd-workflow__gsd_validate_milestone,mcp__gsd-workflow__gsd_milestone_validate,mcp__gsd-workflow__gsd_save_gate_result"
ToolSearch query: "select:mcp__gsd-workflow__gsd_milestone_generate_id,mcp__gsd-workflow__gsd_generate_milestone_id,mcp__gsd-workflow__gsd_milestone_status"
```

When a user asks you to perform any GSD workflow action (complete a task, reopen a slice,
replan, validate, etc.) and you encounter a tool that isn't loaded yet, **always use
ToolSearch to fetch its schema first** rather than telling the user the tool doesn't exist.

## Project

- Python 3.11+ CLI tool for non-functional design reviews
- Uses: Pydantic v2, ruff, pytest, src-layout
- Run tests: `python -m pytest tests/`
- Lint: `ruff check src/ tests/`
