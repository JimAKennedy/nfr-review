# CLAUDE.md

## Project

- Python 3.11+ CLI tool for non-functional design reviews
- Uses: Pydantic v2, ruff, pytest, src-layout
- Run tests: `python -m pytest -n auto tests/`
- Lint: `ruff check src/ tests/`
- Format: `ruff format src/ tests/`

## Auto-Mode Code Quality

After writing or modifying any `.py` file, run `ruff format <file>` before finishing the
task. This prevents pre-commit hook reformatting from creating dirty working-tree state
after git commits. This applies to all agents and subagents — format is not a git command
and is safe to run during task execution.
