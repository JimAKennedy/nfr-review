<!-- Copyright 2026 nfr-review contributors — Licensed under Apache-2.0 -->

# Installing nfr-review

This guide covers every way to add nfr-review to a repository: a minimal
five-line GitHub Action step, a full PR + nightly setup, local CLI usage, and
all the reference tables you need along the way.

---

## Table of contents

1. [Minimal install (one PR workflow)](#1-minimal-install)
2. [Full install (PR + nightly)](#2-full-install)
3. [Action inputs reference](#3-action-inputs-reference)
4. [Action outputs reference](#4-action-outputs-reference)
5. [Permissions reference](#5-permissions-reference)
6. [Versioning policy](#6-versioning-policy)
7. [Configuration](#7-configuration)
8. [Execution modes](#8-execution-modes)
9. [Running locally](#9-running-locally)
10. [Troubleshooting](#10-troubleshooting)
11. [Uninstalling](#11-uninstalling)

---

## 1. Minimal install

Add a single workflow file to your repository. This runs nfr-review on every
pull request, uploads SARIF to the Security tab, and posts a sticky PR comment.

Create **`.github/workflows/nfr-review.yml`**:

```yaml
name: NFR Review
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
  pull-requests: write
  security-events: write
jobs:
  nfr-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: JimAKennedy/nfr-review@v1
        with:
          fail-on: "red"
          sarif-upload: "true"
          comment: "true"
```

That is everything you need to start getting non-functional design feedback on
pull requests. The action installs nfr-review via pip, scans the repository,
and fails the check if any red findings are present.

---

## 2. Full install

A production setup pairs two workflows:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| **PR workflow** | `pull_request` | Diff scan against the nightly baseline, PR comment, SARIF upload |
| **Nightly workflow** | `schedule` (cron) | Full scan, issue sync, publishes baseline artifact for PR diffs |

### PR workflow

Copy [`docs/examples/nfr-review-pr.yml`](examples/nfr-review-pr.yml) to
`.github/workflows/nfr-review.yml` in the target repository.

Key features of the PR workflow:

- Downloads the baseline artifact from the last successful nightly run
  (using `dawidd6/action-download-artifact@v6`).
- Runs nfr-review in **diff mode** so only new or changed findings appear.
- On first adoption (no nightly has run yet), the baseline download is skipped
  and a full scan runs instead. Set `fail-on: "never"` for that first merge,
  then restore `fail-on: "red"` once a nightly baseline exists.

### Nightly workflow

Copy [`docs/examples/nfr-review-nightly.yml`](examples/nfr-review-nightly.yml)
to `.github/workflows/nfr-review-nightly.yml` in the target repository.

Key features of the nightly workflow:

- Runs at 03:00 UTC daily (adjustable via `cron`).
- Sets `fail-on: "never"` because nightly scans are observational.
- Enables `create-issues: "true"` to sync remediation issues.
- Uploads the JSONL output as `nfr-review-baseline` for the PR workflow.
- `first-run-cap: "25"` prevents flooding the issue tracker on first adoption.

### First-run adoption sequence

1. Merge the nightly workflow file into `main`.
2. Trigger it manually via **Actions > NFR Review (nightly) > Run workflow** or
   wait for the first scheduled run.
3. Merge the PR workflow file. Subsequent PRs will diff against the nightly
   baseline.

---

## 3. Action inputs reference

All inputs are optional. The action reference is `JimAKennedy/nfr-review@v1`.

| Input | Default | Description |
|-------|---------|-------------|
| `path` | `"."` | Path to the repository to scan (alias: `target`). |
| `target` | `""` | **Deprecated** -- use `path` instead. |
| `config` | `""` | Path to `nfr-review.yaml` config file. |
| `baseline` | `""` | Path to baseline JSONL for diff mode. |
| `fail-on` | `"red"` | Failure threshold: `"red"`, `"red+amber"`, or `"never"`. |
| `fail-on-red` | `""` | **Deprecated** -- use `fail-on` instead. |
| `sarif` | `""` | Override path for the SARIF output file. |
| `sarif-upload` | `"false"` | Upload SARIF to the GitHub Security tab. |
| `comment` | `"true"` | Post a sticky PR comment with results. |
| `create-issues` | `"false"` | Sync GitHub issues for findings (create, update, close). |
| `file-issues` | `""` | **Deprecated** -- use `create-issues` instead. |
| `issue-severity` | `"high"` | Minimum severity for issue filing (`critical`, `high`, `medium`, `low`, `info`). |
| `rag-min` | `"amber"` | Minimum RAG level for issue filing (`red`, `amber`, `green`). |
| `extra-labels` | `""` | Comma-separated extra labels applied to filed issues. |
| `first-run-cap` | `"25"` | Max issues to create on the first sync (prevents flooding). |
| `python-version` | `"3.12"` | Python version to use (pip mode only, ignored in container mode). |
| `execution` | `"pip"` | Execution mode: `"pip"` or `"container"`. |
| `image` | `"ghcr.io/jimakennedy/nfr-review:latest"` | Docker image for container mode. |

---

## 4. Action outputs reference

All outputs are available via `${{ steps.<id>.outputs.<name> }}`.

| Output | Description |
|--------|-------------|
| `findings-count` | Total number of findings. |
| `red-count` | Number of red findings. |
| `amber-count` | Number of amber findings. |
| `green-count` | Number of green findings. |
| `exit-code` | Exit code of the scan (`0` = pass, `2` = threshold exceeded). |
| `sarif-path` | Path to the generated SARIF file (empty if SARIF was not requested). |
| `jsonl-path` | Path to the generated JSONL findings file. |
| `issues-created` | Number of GitHub issues created during sync. |
| `issues-updated` | Number of GitHub issues updated during sync. |
| `issues-closed` | Number of GitHub issues closed during sync. |

### Using outputs in downstream steps

```yaml
- name: Run NFR Review
  id: nfr
  uses: JimAKennedy/nfr-review@v1
  with:
    fail-on: "red"

- name: Print summary
  if: always()
  run: |
    echo "Findings: ${{ steps.nfr.outputs.findings-count }}"
    echo "Red: ${{ steps.nfr.outputs.red-count }}"
    echo "Exit code: ${{ steps.nfr.outputs.exit-code }}"
```

---

## 5. Permissions reference

Set permissions at the workflow or job level. Only grant the permissions you
actually use.

| Permission | Required when | Why |
|------------|---------------|-----|
| `contents: read` | Always | Read repository files for scanning. |
| `pull-requests: write` | `comment: "true"` | Post and update the sticky PR comment. |
| `security-events: write` | `sarif-upload: "true"` | Upload SARIF to the GitHub Security tab (Code Scanning). |
| `issues: write` | `create-issues: "true"` | Create, update, and close remediation issues. |
| `actions: read` | PR workflow with nightly baseline | Download the baseline artifact from a previous workflow run. |

### Minimal permissions block (PR workflow)

```yaml
permissions:
  contents: read
  pull-requests: write
  security-events: write
  actions: read
```

### Minimal permissions block (nightly workflow)

```yaml
permissions:
  contents: read
  issues: write
  security-events: write
```

---

## 6. Versioning policy

Pin to the **`@v1`** major tag for stability:

```yaml
- uses: JimAKennedy/nfr-review@v1
```

The `v1` tag tracks the latest `v1.x.y` release. It receives backward-compatible
bug fixes and new rules without breaking existing workflows.

If you need absolute reproducibility, pin to a specific version tag:

```yaml
- uses: JimAKennedy/nfr-review@v1.2.3
```

Avoid pinning to `@main` or a commit SHA in production workflows -- these may
include breaking changes without notice.

---

## 7. Configuration

nfr-review can be configured with an optional `nfr-review.yaml` file in your
repository root (or any path specified via the `config` input).

```yaml
# nfr-review.yaml — minimal example
exclude:
  - "vendor/**"
  - "generated/**"
```

The config file controls which paths to exclude, which collectors to enable or
disable, rule-level overrides, and output format preferences.

See the [README](../README.md) for the full configuration reference.

---

## 8. Execution modes

The `execution` input controls how nfr-review runs inside the GitHub Actions
runner.

### pip mode (default)

```yaml
- uses: JimAKennedy/nfr-review@v1
  with:
    execution: "pip"           # this is the default
    python-version: "3.12"     # optional, default 3.12
```

- Sets up Python via `actions/setup-python`.
- Installs nfr-review from the action directory via `pip install`.
- Best for most repositories. No Docker required on the runner.

### container mode

```yaml
- uses: JimAKennedy/nfr-review@v1
  with:
    execution: "container"
    image: "ghcr.io/jimakennedy/nfr-review:latest"
```

- Pulls a pre-built Docker image and runs the scan inside a container.
- Useful when you want a fully isolated, reproducible environment.
- The `python-version` input is ignored in container mode.
- Mount points: the workspace is mounted at `/repo` and the runner temp
  directory at `/output`.

Pin the image tag to a specific version for reproducibility:

```yaml
image: "ghcr.io/jimakennedy/nfr-review:1.2.3"
```

---

## 9. Running locally

### Install from source

```bash
# Requires Python 3.11+
git clone https://github.com/JimAKennedy/nfr-review.git
cd nfr-review
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### Install with extras

```bash
pip install -e ".[scancode]"   # adds scancode-toolkit for license scanning
pip install -e ".[dev]"        # adds pytest, ruff, pytest-cov
```

### CLI usage

```bash
# Scan a repository
nfr-review run /path/to/repo

# Scan with a config file
nfr-review run /path/to/repo --config nfr-review.yaml

# Output JSONL and SARIF
nfr-review run /path/to/repo --jsonl findings.jsonl --sarif findings.sarif

# Diff mode against a baseline
nfr-review run /path/to/repo --baseline baseline.jsonl

# Full report with PDF, score, test results, and dependency analysis
nfr-review report /path/to/repo

# Architecture documentation (multi-repo supported)
nfr-review arch /path/to/repo1 /path/to/repo2

# Hygiene audit
nfr-review hygiene /path/to/repo

# Dependency analysis
nfr-review deps /path/to/repo

# Auto-detect technologies and generate config
nfr-review init /path/to/repo

# Sync issues to GitHub (requires GITHUB_TOKEN)
export GITHUB_TOKEN="ghp_..."
nfr-review issues sync findings.jsonl --repo owner/repo

# Run architecture + NFR reports across multiple repos
nfr-review all /path/to/repo1 /path/to/repo2
```

### Docker

```bash
docker run --rm \
  -v "$(pwd):/repo" \
  ghcr.io/jimakennedy/nfr-review:latest \
  run /repo
```

---

## 10. Troubleshooting

### "Resource not accessible by integration" error

The workflow is missing a required permission. Add the appropriate `permissions`
block (see [Permissions reference](#5-permissions-reference)). If your
repository or organization uses restrictive default permissions, you must
explicitly grant each permission the action needs.

### SARIF upload fails

- Ensure `security-events: write` is in the permissions block.
- GitHub Code Scanning must be enabled for the repository (it is enabled by
  default on public repos; private repos may need Advanced Security or the
  free Code Scanning tier).

### No PR comment appears

- Ensure `pull-requests: write` is in the permissions block.
- The `comment` input must be `"true"` (the default).
- Comments are only posted on `pull_request` events. Nightly (schedule) and
  `workflow_dispatch` runs do not post comments.

### Diff mode shows all findings (not just new ones)

- The baseline artifact may not exist yet. Run the nightly workflow at least
  once before opening a PR.
- Verify the `dawidd6/action-download-artifact` step completed successfully
  (check the step output for "Artifact downloaded" vs "No artifact found").
- Ensure the `baseline` input path matches the downloaded artifact location.

### Too many issues created at once

- Set `first-run-cap` to limit the number of issues created on the first sync.
  The default is 25. Subsequent runs create issues only for new findings.
- Raise or lower `rag-min` and `issue-severity` to control which findings
  produce issues.

### Container mode fails to pull the image

- Ensure the runner has network access to `ghcr.io`.
- If using a private image, configure Docker authentication on the runner
  before the nfr-review step.

### Python version errors in pip mode

- The default Python version is 3.12. If your runner does not have it
  available, set `python-version` to a version present on the runner.
- nfr-review requires Python 3.11 or later.

### Action fails but no findings are shown

- Check the "Run nfr-review scan" step logs for errors (import failures,
  missing dependencies, config parse errors).
- Run the scan locally to reproduce the issue (see
  [Running locally](#9-running-locally)).

---

## 11. Uninstalling

### Remove the GitHub Action

1. Delete `.github/workflows/nfr-review.yml` (the PR workflow).
2. Delete `.github/workflows/nfr-review-nightly.yml` (the nightly workflow), if
   present.
3. Optionally delete `nfr-review.yaml` from the repository root if you added a
   configuration file.
4. Close any open GitHub issues labelled `nfr-review` if you used
   `create-issues`.

### Remove a local installation

```bash
pip uninstall nfr-review
# Or remove the entire virtualenv:
rm -rf .venv
```

### Remove Docker images

```bash
docker rmi ghcr.io/jimakennedy/nfr-review:latest
```
