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
7. [LLM features](#7-llm-features)
8. [Configuration](#8-configuration)
9. [Execution modes](#9-execution-modes)
10. [Running locally](#10-running-locally)
11. [Dynamic analysis](#11-dynamic-analysis)
12. [Troubleshooting](#12-troubleshooting)
13. [Rule catalogue](#13-rule-catalogue)
14. [External dependencies](#14-external-dependencies)
15. [Uninstalling](#15-uninstalling)

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
      - uses: actions/checkout@v6
      - uses: JimAKennedy/nfr-review@v1
        with:
          fail-on: "red"
          sarif-upload: "true"
          comment: "true"
```

That is everything you need to start getting non-functional design feedback on
pull requests. The action installs nfr-review via pip, scans the repository,
and fails the check if any red findings are present.

> **Code Scanning (recommended):** To see SARIF results in the GitHub Security tab,
> enable Code Scanning in **Settings > Code security > Code scanning**. If Code
> Scanning is not enabled, the SARIF upload step is skipped gracefully — all other
> features (PR comment, artifacts, fail-on threshold) still work.

> **Optional:** To enable LLM-powered features (executive summary, ADR drift
> analysis), add `anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}` to the
> `with:` block. See [LLM features](#7-llm-features) for details.

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
  (using the `gh` CLI — no third-party action required).
- Runs nfr-review in **diff mode** so only new or changed findings appear.
- On first adoption (no nightly has run yet), the baseline download is skipped
  automatically and a full scan runs instead. No manual setup needed.

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
| `workers` | `"4"` | Number of parallel collector threads (`1` = sequential). |
| `otel-traces` | `""` | Path to an OTLP JSON/NDJSON trace file for Band 3 dynamic analysis. |
| `anthropic-api-key` | `""` | Anthropic API key for LLM features. Omit to skip LLM features gracefully. |

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

## 7. LLM features

nfr-review includes optional LLM-powered analysis with three backend options:

| Backend | Extra to install | Auth | Best for |
|---------|-----------------|------|----------|
| **Anthropic API** (default) | `[llm-anthropic]` | `ANTHROPIC_API_KEY` | CI, production use |
| **OpenAI-compatible** | `[llm-openai]` | Varies by provider | Ollama (local), Azure OpenAI, OpenRouter |
| **Claude CLI** | None | Claude Code subscription | Local dev, no API key needed |

When no backend is configured, LLM features are **skipped gracefully** — the
scan runs normally and all static-analysis findings are still produced.

### What LLM features provide

| Feature | Command | What it does |
|---------|---------|--------------|
| Executive summary | `report` | Generates a natural-language summary for the PDF report |
| ADR drift analysis | `run` | Detects when code has drifted from Architecture Decision Records |
| PII detection confirmation | `run` | Uses LLM to confirm potential PII logging patterns |
| Domain model inference | `arch` | Infers bounded contexts and domain models from code |
| Market comparison | `arch` | Compares architecture patterns against industry norms |

### Configuration

LLM settings live in `nfr-review.yaml` under the `llm:` key. Environment
variables override the config file.

```yaml
# nfr-review.yaml
llm:
  provider: anthropic           # anthropic | openai | claude-cli
  model: claude-sonnet-4-6
  base_url: null                # override for custom endpoints
  api_key_env_var: ANTHROPIC_API_KEY  # which env var holds the API key
```

| Env var | Overrides | Example |
|---------|-----------|---------|
| `NFR_LLM_PROVIDER` | `llm.provider` | `openai` |
| `NFR_LLM_MODEL` | `llm.model` | `gpt-4o` |
| `NFR_LLM_BASE_URL` | `llm.base_url` | `http://localhost:11434/v1` |

### Setting up in GitHub Actions

GitHub Actions should use the Anthropic API backend (Claude CLI is not
available in CI).

1. Add `ANTHROPIC_API_KEY` as a **repository secret** in Settings > Secrets and
   variables > Actions.

2. Pass it to the action via the `anthropic-api-key` input:

```yaml
- name: Run NFR Review
  id: nfr
  uses: JimAKennedy/nfr-review@v1
  with:
    path: .
    fail-on: "red"
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

The action forwards the key as an environment variable to the scan process. In
container mode, it is injected into the Docker container automatically.

### Setting up locally

The setup scripts (`scripts/setup.sh` or `scripts/setup-all.sh`) prompt you to
choose a backend interactively. You can also configure it manually:

**Option A — Anthropic API:**

```bash
pip install "nfr-review[llm-anthropic]"
export ANTHROPIC_API_KEY="sk-ant-..."
nfr-review report /path/to/repo
```

**Option B — OpenAI-compatible (Ollama):**

```bash
pip install "nfr-review[llm-openai]"
export NFR_LLM_PROVIDER=openai
export NFR_LLM_MODEL=llama3
export NFR_LLM_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama   # Ollama ignores this but the SDK requires it
nfr-review report /path/to/repo
```

Or configure persistently in `nfr-review.yaml`:

```yaml
llm:
  provider: openai
  model: llama3
  base_url: http://localhost:11434/v1
  api_key_env_var: OPENAI_API_KEY
```

This also works with Azure OpenAI (set `base_url` to your Azure endpoint) and
OpenRouter (set `base_url: https://openrouter.ai/api/v1`).

**Option C — Claude CLI (Claude Max):**

```bash
export NFR_LLM_PROVIDER=claude-cli
nfr-review report /path/to/repo
```

Requires the `claude` binary on your `$PATH` (installed with Claude Code).
No API key or Python SDK needed.

### Opting out

If a backend is configured but you want to skip LLM features for a specific run:

```bash
nfr-review report /path/to/repo --no-summary   # skip executive summary
nfr-review arch /path/to/repo --no-llm         # skip all LLM analysis
```

### Cost and data scope

LLM features send code snippets and structural metadata to the configured
backend. See [SECURITY.md](../SECURITY.md) for the full data scope disclosure.
With the Anthropic API, typical cost is under $0.10 per scan. With Claude CLI,
calls are covered by your Claude Max subscription. With Ollama, calls are free
and stay on your local machine.

---

## 8. Configuration

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

## 9. Execution modes

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
- Installs nfr-review via `pip install`.
- Best for most repositories. No Docker required on the runner.

### container mode

```yaml
- uses: JimAKennedy/nfr-review@v1
  with:
    execution: "container"
    image: "ghcr.io/jimakennedy/nfr-review:latest"
```

- Pulls a pre-built Docker image and runs the scan inside a container.
- Image available for `linux/amd64` (runs on Apple Silicon via Rosetta).
- Useful when you want a fully isolated, reproducible environment.
- The `python-version` input is ignored in container mode.
- Mount points: the workspace is mounted at `/repo` and the runner temp
  directory at `/output`.

Pin the image tag to a specific version for reproducibility:

```yaml
image: "ghcr.io/jimakennedy/nfr-review:1.2.3"
```

---

## 10. Running locally

### Install from PyPI

```bash
# Requires Python 3.11+
pip install nfr-review
```

### Optional extras

| Extra | What it adds |
|-------|-------------|
| `[llm-anthropic]` | [anthropic](https://pypi.org/project/anthropic/) SDK for LLM-powered analysis (executive summary, ADR drift, PII detection). |
| `[llm-openai]` | [openai](https://pypi.org/project/openai/) SDK for OpenAI-compatible backends (Ollama, Azure OpenAI, OpenRouter). |
| `[scancode]` | [scancode-toolkit](https://github.com/aboutcode-org/scancode-toolkit) for license compliance scanning. |
| `[diagrams]` | [graphviz](https://pypi.org/project/graphviz/) Python bindings for diagram rendering. |
| `[pdf]` | [weasyprint](https://weasyprint.org/) for PDF report generation. |
| `[monitor]` | [aiohttp](https://pypi.org/project/aiohttp/) for the production interaction monitor. |
| `[otel]` | [opentelemetry-api](https://pypi.org/project/opentelemetry-api/) + SDK for OTel trace generation in tests. |
| `[graphify]` | [graphifyy](https://pypi.org/project/graphifyy/) knowledge-graph extraction + [networkx](https://pypi.org/project/networkx/) for structural analysis rules (god nodes, weak boundaries, coupling clusters). |
| `[full]` | All of the above (except `scancode`): `pdf` + `diagrams` + `llm-anthropic` + `llm-openai` + `otel` + `monitor` + `graphify`. |
| `[dev]` | pytest, ruff, pytest-cov, and test dependencies for development and CI. |

Install extras individually or combine them:

```bash
pip install "nfr-review[llm-anthropic,pdf,scancode]"

# Or install everything at once:
pip install "nfr-review[full]"
```

For a complete list of all external dependencies — including GitHub Actions,
LLM providers, CI services, and runtime binaries — see the
[External Dependencies](dependencies.md) catalog.

### Install from source (development)

```bash
git clone https://github.com/JimAKennedy/nfr-review.git
cd nfr-review
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
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

# Dynamic analysis with pre-collected OTel traces
nfr-review run /path/to/repo --otel-traces traces.ndjson

# Dynamic analysis with managed OTel Collector
nfr-review run /path/to/repo --collector

# Architecture documentation (multi-repo supported)
nfr-review arch /path/to/repo1 /path/to/repo2

# Hygiene audit
nfr-review hygiene /path/to/repo

# Dependency analysis
nfr-review deps /path/to/repo

# Auto-detect technologies and generate config
nfr-review init /path/to/repo

# Preview config without writing (dry-run)
nfr-review init /path/to/repo --dry-run

# Sync issues to GitHub (requires GITHUB_TOKEN)
export GITHUB_TOKEN="ghp_..."
nfr-review issues sync findings.jsonl --repo owner/repo

# Run architecture + NFR reports across multiple repos
nfr-review all /path/to/repo1 /path/to/repo2
```

> **Dynamic analysis:** The `--otel-traces` and `--collector` flags enable
> Band 3 rules that analyse runtime behaviour from OpenTelemetry traces.
> See the [Dynamic Analysis guide](dynamic-analysis.md) for full details.

### Docker

A pre-built `linux/amd64` image is published to GHCR. It includes PDF
generation (via WeasyPrint), LLM SDKs (Anthropic and OpenAI), and `git`.
The container runs as non-root user `nfr` (UID 1000).

> **Note:** The container does not include Node.js, Chromium, or
> mermaid-cli (`mmdc`). Diagrams in HTML reports use bundled client-side
> Mermaid.js instead. PDF diagrams use pure-Python SVG fallbacks. This
> keeps the image size under 200MB.

```bash
# Pull the image (--platform required on Apple Silicon Macs)
docker pull --platform linux/amd64 ghcr.io/jimakennedy/nfr-review:latest

# Scan a local project (mount it at /repo)
docker run --rm --platform linux/amd64 \
  -v "$(pwd)":/repo \
  ghcr.io/jimakennedy/nfr-review:latest run /repo

# HTML report (recommended for container usage)
docker run --rm --platform linux/amd64 \
  -v "$(pwd)":/repo \
  ghcr.io/jimakennedy/nfr-review:latest report /repo --html

# Full report with PDF (WeasyPrint included in image)
docker run --rm --platform linux/amd64 \
  -v "$(pwd)":/repo \
  ghcr.io/jimakennedy/nfr-review:latest report /repo
```

The entrypoint is `nfr-review`, so all CLI subcommands and flags
(`run`, `report`, `hygiene`, `deps`, `arch`, `all`, etc.) work directly as
arguments.

**Using LLM features in Docker:** Pass your API key via `-e`. The image
ships with both Anthropic and OpenAI SDKs pre-installed. Without an API key,
LLM-powered features (executive summary, ADR drift, PII detection) are
skipped gracefully — all static-analysis rules still run.

```bash
# Anthropic API (default provider)
docker run --rm --platform linux/amd64 \
  -v "$(pwd)":/repo \
  -e ANTHROPIC_API_KEY \
  ghcr.io/jimakennedy/nfr-review:latest report /repo

# OpenAI-compatible (e.g. Ollama running on the host)
docker run --rm --platform linux/amd64 \
  -v "$(pwd)":/repo \
  -e NFR_LLM_PROVIDER=openai \
  -e NFR_LLM_MODEL=llama3 \
  -e NFR_LLM_BASE_URL=http://host.docker.internal:11434/v1 \
  -e OPENAI_API_KEY=ollama \
  ghcr.io/jimakennedy/nfr-review:latest report /repo

# Override provider and model via env vars
docker run --rm --platform linux/amd64 \
  -v "$(pwd)":/repo \
  -e NFR_LLM_PROVIDER=anthropic \
  -e NFR_LLM_MODEL=claude-sonnet-4-6 \
  -e ANTHROPIC_API_KEY \
  ghcr.io/jimakennedy/nfr-review:latest all /repo -v
```

Note: `-e ANTHROPIC_API_KEY` (no `=`) forwards the variable from your
host shell. You can also use `-e ANTHROPIC_API_KEY=sk-ant-...` to set
it explicitly.

**macOS (Apple Silicon):** The image is `linux/amd64` only. Docker Desktop
on M-series Macs runs it via Rosetta emulation — the `--platform linux/amd64`
flag is required on both `pull` and `run`. Without it, Docker will report
`no matching manifest for linux/arm64/v8`. For faster emulation, enable
**Settings > General > "Use Rosetta for x86_64/amd64 emulation on Apple
Silicon"** in Docker Desktop.

---

## 11. Dynamic analysis

nfr-review can analyse runtime behaviour captured in OpenTelemetry traces,
producing topology graphs, sequence diagrams, and findings about latency
hotspots, N+1 queries, and trace correlation gaps.

**Two modes are available:**

| Mode | Flag | When to use |
|------|------|-------------|
| Pre-collected traces | `--otel-traces FILE` | You already have an OTLP trace file from a test run or production export |
| Managed collector | `--collector` | You want nfr-review to start/stop an OTel Collector during the scan |

```bash
# Pre-collected traces
nfr-review report /path/to/repo --otel-traces traces.ndjson

# Managed collector (requires otelcol-contrib on PATH)
nfr-review run /path/to/repo --collector
```

The managed collector requires `otelcol-contrib` or `otelcol` on your
`$PATH`. Run `scripts/setup-all.sh` to install automatically, or download
from [GitHub releases](https://github.com/open-telemetry/opentelemetry-collector-releases/releases).

For the full guide — including trace file format, custom collector configs,
and CI integration — see [Dynamic Analysis](dynamic-analysis.md).

### Production interaction monitor (EXPERIMENTAL)

nfr-review also includes an experimental production interaction monitor that
continuously compares live traces against a UAT-derived baseline to detect
novel service interactions. Install the monitor extra to use it:

```bash
pip install "nfr-review[monitor]"
```

See the [Production Monitor deployment guide](monitor-deployment.md) for
setup and configuration.

---

## 12. Troubleshooting

### "Resource not accessible by integration" error

The workflow is missing a required permission. Add the appropriate `permissions`
block (see [Permissions reference](#5-permissions-reference)). If your
repository or organization uses restrictive default permissions, you must
explicitly grant each permission the action needs.

### SARIF upload warning

If the workflow shows a warning like "SARIF upload failed — Code Scanning may
not be enabled", the scan still completed successfully — only the upload to the
Security tab was skipped. To fix:

- Enable Code Scanning in **Settings > Code security > Code scanning** (enabled
  by default on public repos; private repos may need Advanced Security or the
  free Code Scanning tier).
- Ensure `security-events: write` is in the workflow permissions block.

### No PR comment appears

- Ensure `pull-requests: write` is in the permissions block.
- The `comment` input must be `"true"` (the default).
- Comments are only posted on `pull_request` events. Nightly (schedule) and
  `workflow_dispatch` runs do not post comments.

### Diff mode shows all findings (not just new ones)

- The baseline artifact may not exist yet. Run the nightly workflow at least
  once before opening a PR (or trigger it manually via Actions > Run workflow).
- Verify the "Download nightly baseline" step completed successfully
  (check the step output — it will log a notice if no baseline was found).
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

### LLM summary or ADR drift analysis is missing

No LLM backend is configured, or the configured backend is unavailable. LLM
features are silently skipped when no provider is ready. Check your `llm:`
config in `nfr-review.yaml` or env vars (`NFR_LLM_PROVIDER`, API key). See
[LLM features](#7-llm-features) for setup. Use `-v` to see which features
were skipped and why.

### Code Scanning check shows "skipping" on a PR

This is expected behavior, not an error. When SARIF results are uploaded, GitHub's
Code Scanning integration compares the PR results against the base branch (main).
If all findings in the PR already exist in the nightly baseline on main, GitHub
reports zero *new* alerts and the code scanning check shows a **neutral / "skipping"**
status. The NFR Review workflow itself still ran successfully — check the "NFR Review"
workflow run in the Actions tab to confirm.

You will only see the code scanning check report findings when the PR introduces
a genuinely new alert that was not present on main.

### Action fails but no findings are shown

- Check the "Run nfr-review scan" step logs for errors (import failures,
  missing dependencies, config parse errors).
- Run the scan locally to reproduce the issue (see
  [Running locally](#10-running-locally)).

---

## 13. Rule catalogue

A browsable HTML catalogue of all rules is published to GitHub Pages on each
release. Visit
[jimakennedy.github.io/nfr-review](https://jimakennedy.github.io/nfr-review/)
to search and filter rules by category, severity, and tags.

To generate the catalogue locally:

```bash
nfr-review list-rules --format json | python scripts/generate_catalogue.py --output catalogue.html
```

The catalogue is self-contained (no external dependencies) and can be opened
directly in a browser.

To create your own custom rules or distribute rule packs as pip-installable
plugins, see the [Custom Rules Guide](custom-rules.md).

---

## 14. External dependencies

For a comprehensive catalog of every external dependency — Python libraries,
LLM providers, GitHub Actions, external APIs, CI services, runtime binaries,
and environment variables — see **[External Dependencies](dependencies.md)**.

The catalog includes adaptation notes for adopters who are forking or deploying
nfr-review internally (what to change, what to remove, what breaks without
each dependency).

---

## 15. Uninstalling

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
