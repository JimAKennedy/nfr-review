---
name: python-conventions
description: Python coding conventions for nfr-review — type hints, ruff config, Google-style docstrings, naming, function length, import order, pytest layout. Use when writing or editing any Python source file (.py), configuring ruff/pyproject.toml, adding tests, or reviewing Python code for style compliance.
---

# Python Conventions

Project-wide Python rules for nfr-review. Adapted from MorphForge's `CODING-STANDARDS.md`. Apply on every Python edit.

## Targets

- **Python version:** 3.11+
- **Lint/format:** `ruff check` and `ruff format` must pass with zero errors
- **Type hints:** Required on every function signature (parameters and return)
- **Docstrings:** Required on every public function/class (Google style)
- **Function length:** ≤ 50 lines. If longer, extract.
- **Test coverage:** ≥ 70% for new code

## Naming

| Element | Convention | Example |
|---------|-----------|---------|
| Functions | `snake_case` | `parse_evidence`, `score_finding` |
| Variables | `snake_case` | `severity_level`, `report_path` |
| Constants | `UPPER_SNAKE` | `MAX_FINDINGS`, `DEFAULT_TIMEOUT` |
| Classes | `PascalCase` | `NfrReport`, `EvidenceCollector` |
| Files | `snake_case.py` | `evidence_collector.py` |
| Tests | `test_*.py` | `test_evidence_collector.py` |
| Private | leading `_` | `_internal_helper` |

## Import order

Three groups, separated by a blank line. Ruff's isort (`I`) enforces this.

```python
# Standard library
import json
from pathlib import Path
from typing import Any

# Third-party
import pydantic
from rich.console import Console

# Local
from nfr_review.evidence import Evidence
```

## Type hints

- Use modern syntax: `list[str]`, `dict[str, int]`, `X | None` (not `List`, `Dict`, `Optional[X]`)
- Annotate every parameter and return type, including `None`
- For complex types, alias them once: `type FindingMap = dict[str, list[Finding]]`
- Use `Literal[...]` for enum-like string parameters when an Enum is overkill

```python
def load_findings(path: Path) -> list[Finding]:
    ...

def render(report: NfrReport, *, format: Literal["md", "json"] = "md") -> str:
    ...
```

## Docstrings (Google style)

Required on every public function and class. Skip docstrings on trivial private helpers.

```python
def score_finding(finding: Finding, weights: dict[str, float]) -> float:
    """Compute weighted severity score for a single finding.

    Args:
        finding: The finding to score.
        weights: Per-category multipliers (1.0 = default).

    Returns:
        Score in [0.0, 10.0]. Higher means more severe.

    Raises:
        ValueError: If finding has no severity assigned.
    """
```

## Function length and structure

- ≤ 50 lines per function. If you hit it, extract a helper.
- Prefer pure functions when possible — easier to test.
- Side effects (I/O, mutation) belong in clearly-named functions, not inside computation.
- Keep cyclomatic complexity low: early returns, guard clauses, no deep nesting.

## ruff configuration

Pin in `pyproject.toml`. The selected rules below are the project default; do not silently relax.

```toml
[tool.ruff]
target-version = "py311"
line-length = 95

[tool.ruff.lint]
select = [
    "E", "W",   # pycodestyle
    "F",        # pyflakes
    "I",        # isort
    "N",        # pep8-naming
    "UP",       # pyupgrade (modern syntax)
    "B",        # bugbear (likely bugs)
    "SIM",      # simplify
    "TCH",      # type-checking imports
    "RUF",      # ruff-specific
]
ignore = ["E501"]  # line length handled by formatter

[tool.ruff.lint.isort]
known-first-party = ["nfr_review"]
```

When adding rules, prefer enabling project-wide over scattering `# noqa`.

## Bandit (security linter)

Bandit runs in CI via `bandit -r src/ -c pyproject.toml`. Configuration lives in `[tool.bandit]` in pyproject.toml.

**Critical:** Ruff's `# noqa: S603` does NOT suppress Bandit — it only suppresses ruff's S-rules. To suppress Bandit findings, use `# nosec BXXX`. When both tools flag the same line, you need both annotations:

```python
import subprocess  # nosec B404
result = subprocess.run(cmd, ...)  # noqa: S603  # nosec B603 B607
```

Common Bandit codes in this project:
- **B404** — `import subprocess` (suppress at the import)
- **B603** — `subprocess.run()` without `shell=True` (suppress at the call site)
- **B607** — partial executable path in subprocess call (suppress at the call site)
- **B101** — `assert` statements (globally skipped in pyproject.toml)

Only add `# nosec` when the usage is genuinely safe and you understand why Bandit flags it.

## pytest layout

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
```

- Test names describe behavior: `test_score_finding_returns_zero_for_info_severity`
- One assertion focus per test; use `pytest.mark.parametrize` for variants
- Fixtures in `conftest.py` at the appropriate scope level
- Use `tmp_path` for filesystem tests, never `/tmp` directly

```python
@pytest.mark.parametrize("severity,expected", [
    ("info", 0.0),
    ("low", 2.5),
    ("high", 7.5),
    ("critical", 10.0),
])
def test_score_finding_maps_severity_to_score(severity, expected):
    finding = Finding(title="x", severity=severity, category="perf")
    assert score_finding(finding, weights={}) == expected
```

## Project layout (src layout)

```
nfr-review/
  pyproject.toml
  src/
    nfr_review/
      __init__.py
      cli.py
      evidence/
      reports/
  tests/
    test_cli.py
    test_evidence/
```

- Always `src/`-layout — prevents importing the working tree by accident
- Package name uses underscores; distribution name (in pyproject) uses hyphens
- Every package has `__init__.py`; explicit `__all__` for public surface

## Errors and logging

- Raise typed exceptions with actionable messages: `raise ValueError(f"unsupported format: {fmt}; expected one of {SUPPORTED}")`
- Don't catch `Exception` broadly. Catch the specific class you can actually handle.
- Use `logging` (not `print`) for diagnostics. Configure once at CLI entry, not in libraries.
- For user-facing CLI output, use `rich` (see `rich-output` patterns) — keep it separate from logs.

## Common anti-patterns to reject in review

- Mutable default arguments: `def f(x=[]):` → use `None` sentinel
- `from x import *` outside `__init__.py` re-exports
- Catching `Exception:` to suppress unknown failures
- `print()` in library code
- Untyped `**kwargs` swallowing the public API
- Tests that share state via module-level globals
- `os.path` when `pathlib.Path` works
- String paths instead of `Path` objects across function boundaries

## Pre-commit verification

Before claiming Python work is done:

```bash
ruff check .
ruff format --check .
bandit -r src/ -c pyproject.toml
pytest
```

All four must pass. If any fails, fix root cause — do not add `# noqa` or skip tests. Bandit is also in pre-commit hooks, so `pre-commit run --all-files` covers everything except pytest.
