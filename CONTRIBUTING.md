# Contributing to nfr-review

Thank you for considering a contribution to nfr-review. This document explains
how to set up a development environment, run checks locally, and submit changes.

## Prerequisites

- Python 3.11 or later
- Git

## Development Setup

```bash
git clone https://github.com/JimAKennedy/nfr-review.git
cd nfr-review
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
# Full suite
pytest

# With coverage report
pytest --cov --cov-report=term-missing
```

## Linting

The project uses [Ruff](https://docs.astral.sh/ruff/) for linting and
formatting. These are the same checks CI runs:

```bash
# Lint
ruff check src/ tests/

# Format check (no changes)
ruff format src/ tests/ --check --diff

# Auto-fix lint issues
ruff check src/ tests/ --fix

# Auto-format
ruff format src/ tests/
```

## Type Checking

```bash
mypy src/
```

## Dependency Lockfiles

Pinned dependency lockfiles ensure reproducible installs in CI and development.
Regenerate them after changing `[project.dependencies]` or
`[project.optional-dependencies]` in `pyproject.toml`:

```bash
pip-compile --strip-extras --annotation-style=line --output-file=requirements.txt pyproject.toml
pip-compile --strip-extras --extra=dev --annotation-style=line --output-file=requirements-dev.txt pyproject.toml
```

To install from lockfiles instead of the loose specifiers:

```bash
pip install -r requirements-dev.txt
pip install -e . --no-deps
```

## Pre-commit Hooks

The repository includes a `.pre-commit-config.yaml` that runs Ruff, mypy,
Bandit, and Gitleaks on each commit. Install hooks with:

```bash
pip install pre-commit
pre-commit install
```

## Pull Request Expectations

- One logical change per PR.
- New rules or collectors should include tests.
- All CI checks must pass: ruff check, ruff format, mypy, pytest, bandit.
- Keep commits focused and write clear commit messages.

## Adding a New Rule

1. Create a module in `src/nfr_review/rules/`.
2. Implement the rule following the existing registry pattern (see any rule in
   that directory for reference).
3. Add tests in `tests/` with appropriate fixtures.
4. The rule auto-registers on import via the `_register()` convention.

## Adding a New Collector

1. Create a module in `src/nfr_review/collectors/`.
2. Implement the `Collector` protocol from `src/nfr_review/protocols.py`.
3. Register in `src/nfr_review/collectors/__init__.py`.
4. Add test fixtures and tests.

## License

Contributions are accepted under the [Apache License 2.0](LICENSE). By
submitting a pull request you agree to license your contribution under the same
terms.

Please sign off your commits with the
[Developer Certificate of Origin (DCO)](https://developercertificate.org/) by
adding `Signed-off-by: Your Name <email>` to your commit messages, or use
`git commit -s`.
