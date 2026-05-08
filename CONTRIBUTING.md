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

## Installing Agent Skills

This project uses third-party agent skills (for Claude Code / GSD) that are
**not tracked in git** due to their licensing terms. After cloning, install them
from `skills-lock.json`:

```bash
python scripts/install_skills.py
```

This downloads skill directories from their source GitHub repositories into
`.agents/skills/`. The three project-authored skills (`nfr-review-domain`,
`pydantic-v2`, `python-conventions`) are tracked in git and require no extra
setup.

Other useful commands:

```bash
python scripts/install_skills.py --check        # verify installed skills
python scripts/install_skills.py --force        # reinstall all skills
python scripts/install_skills.py --update-lock  # update lock hashes after upstream changes
```

> **Important:** Never commit third-party skill files to git. They are excluded
> via `.gitignore`. Only project-authored skills under `.agents/skills/` should
> be tracked. See `skills-lock.json` for the canonical list of vendored skills
> and their sources.

## Git Identity

Before committing, configure your Git email to a public address (not a local
hostname). GitHub provides a private noreply address you can use:

```bash
git config user.email "YOUR_USERNAME@users.noreply.github.com"
```

Find your noreply address at
<https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-email-preferences/setting-your-commit-email-address>.

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
