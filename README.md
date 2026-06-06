# nfr-review

[![CI](https://github.com/JimAKennedy/nfr-review/actions/workflows/ci.yml/badge.svg)](https://github.com/JimAKennedy/nfr-review/actions/workflows/ci.yml)
[![coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/JimAKennedy/af34283def743414fcf7c3ade1155881/raw/nfr-review-coverage.json)](https://github.com/JimAKennedy/nfr-review/actions/workflows/ci.yml)
[![mypy](https://img.shields.io/badge/mypy-strict-blue)](https://github.com/JimAKennedy/nfr-review/blob/main/pyproject.toml)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Automated non-functional design reviews for software projects.

`nfr-review` scans a repository for architectural evidence (Spring configs, K8s manifests, CI pipelines, Dockerfiles, Helm charts, Terraform modules, Istio configs, ADRs, Java/Go/Python/C#/C++ source, gRPC proto files, APIM policies, and more) and evaluates 134 rules covering resilience, observability, security, operational readiness, deployment patching, and repository hygiene. Hygiene audits cover documentation, CI automation, community standards, build readiness, privacy, and license compliance. Findings are emitted as CSV, JSONL, SARIF, Markdown, and PDF for integration into review workflows.

## Quick start

### GitHub Action (CI integration)

Add a single workflow file to start getting NFR feedback on pull requests:

```yaml
# .github/workflows/nfr-review.yml
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

This scans the repo, uploads SARIF to the Security tab, posts a sticky PR
comment, and fails the check on red findings. Add a [nightly workflow](docs/examples/nfr-review-nightly.yml) for baseline tracking and issue sync.

See [docs/install.md](docs/install.md) for the full install guide (inputs, outputs, permissions, execution modes, troubleshooting) and [docs/continuous-compliance.md](docs/continuous-compliance.md) for compliance framework mappings.

### Local CLI

```bash
# Install from PyPI (requires Python 3.11+)
pip install nfr-review

# Run against a target repository
nfr-review run /path/to/your/repo
```

Optional extras:

```bash
pip install "nfr-review[llm-anthropic]"  # LLM via Anthropic API
pip install "nfr-review[llm-openai]"     # LLM via OpenAI-compatible APIs (Ollama, Azure, OpenRouter)
pip install "nfr-review[pdf]"            # PDF report generation
pip install "nfr-review[scancode]"       # license compliance scanning
pip install "nfr-review[diagrams]"       # Graphviz diagram rendering
```

## Requirements

- **Python 3.11+** (`python3.11`, `python3.12`, etc. — macOS ships 3.9 as `python3` which is too old)
- Python dependencies are installed automatically via `pip install -e .`

### Optional external tools

These are **not** Python packages — they are standalone binaries that some collectors call at runtime. The tool degrades gracefully when they are absent (skips the relevant analysis with an informative message), but for full coverage they should be installed:

| Tool | Used by | Install |
|------|---------|---------|
| [Helm](https://helm.sh/) | `helm` collector — renders Go-templated Helm charts via `helm template` before analysis | `brew install helm` (macOS) or [helm.sh/docs/intro/install](https://helm.sh/docs/intro/install/) |

Without Helm, the Helm collector still analyses `Chart.yaml` and `values.yaml` statically, but rendered manifest analysis (template expansion, secret leakage in rendered output) is skipped.

### Optional: LLM features

Three LLM backends are supported: Anthropic API (`[llm-anthropic]` extra), OpenAI-compatible APIs like Ollama (`[llm-openai]` extra), and Claude CLI (no extra needed). Configure via `nfr-review.yaml` or env vars. Without a backend, LLM features are skipped gracefully. See [docs/install.md — LLM features](docs/install.md#7-llm-features) for setup details.

## Installation

### From PyPI

```bash
pip install nfr-review
```

### Optional extras

| Extra | What it adds |
|-------|-------------|
| `[llm-anthropic]` | [anthropic](https://pypi.org/project/anthropic/) SDK for LLM-powered analysis (executive summary, ADR drift, PII detection). |
| `[llm-openai]` | [openai](https://pypi.org/project/openai/) SDK for OpenAI-compatible backends (Ollama, Azure OpenAI, OpenRouter). |
| `[scancode]` | [scancode-toolkit](https://github.com/aboutcode-org/scancode-toolkit) for license compliance scanning. Without it, license hygiene rules skip gracefully with an informative warning. |
| `[diagrams]` | [graphviz](https://pypi.org/project/graphviz/) Python bindings for `--render-diagrams` output. |
| `[pdf]` | [weasyprint](https://weasyprint.org/) for PDF report generation with rendered diagrams and executive summary. |
| `[dev]` | pytest, ruff, and pytest-cov for development and CI. |

Install extras individually or combine them:

```bash
pip install "nfr-review[llm-anthropic,pdf]"
```

### Development install (from source)

```bash
git clone https://github.com/JimAKennedy/nfr-review.git
cd nfr-review
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

## LLM backend (optional)

LLM-assisted rules (PII detection, ADR drift analysis) require an LLM backend. Three backends are supported:

**Anthropic API** (default):
```bash
pip install "nfr-review[llm-anthropic]"
export ANTHROPIC_API_KEY="sk-ant-..."
nfr-review run /path/to/repo
```

**OpenAI-compatible** (Ollama, Azure OpenAI, OpenRouter):
```bash
pip install "nfr-review[llm-openai]"
export NFR_LLM_PROVIDER=openai
export NFR_LLM_MODEL=llama3
export NFR_LLM_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama   # Ollama ignores this but the SDK requires it
nfr-review run /path/to/repo
```

**Claude CLI** (Claude Code subscription, no API key needed):
```bash
export NFR_LLM_PROVIDER=claude-cli
nfr-review run /path/to/repo
```

Configure via `nfr-review.yaml` for persistent settings:
```yaml
llm:
  provider: openai              # anthropic | openai | claude-cli
  model: llama3
  base_url: http://localhost:11434/v1
  api_key_env_var: OPENAI_API_KEY
```

Env vars (`NFR_LLM_PROVIDER`, `NFR_LLM_MODEL`, `NFR_LLM_BASE_URL`) override the config file. Without a backend configured, LLM features are skipped gracefully and all other rules still run normally.

## Usage

### Scan a repository

```bash
nfr-review run /path/to/target/repo
```

This will:
1. Collect evidence from the target repo (Spring configs, K8s manifests, CI workflows, Dockerfiles, Helm charts, Terraform, Istio, source code, ADRs, APIM policies, and more)
2. Evaluate all applicable rules against the collected evidence
3. Write findings to `{repo}-nfr-review.csv` and `{repo}-nfr-review.jsonl` in the current directory
4. Print a summary to stderr

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--config PATH` | `./nfr-review.yaml` (if present) | Path to configuration file |
| `--csv PATH` | `{repo}-nfr-review.csv` | Output path for CSV findings |
| `--jsonl PATH` | `{repo}-nfr-review.jsonl` | Output path for JSONL run record |
| `--sarif PATH` | — | Output path for SARIF 2.1.0 findings file |
| `--exclude-tests` / `--include-tests` | exclude | Exclude test and fixture directories from analysis |
| `--baseline PATH` | — | Path to a prior JSONL file; suppress known findings, exit on regressions |
| `--score` | off | Compute and display design maturity score |
| `--workers N` | `1` | Number of parallel collector threads (`1` = sequential) |
| `-v` / `--verbose` | off | Increase verbosity (`-v` for INFO, `-vv` for DEBUG) |
| `-q` / `--quiet` | off | Suppress warnings (ERROR level only) |
| `--log-file PATH` | stderr | Write diagnostics to FILE instead of stderr |

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | Success — scan completed |
| 1 | Error — bad target path, config error, or engine failure |
| 2 | Threshold breach — at least one finding meets or exceeds `severity_threshold` |

### List available rules

```bash
nfr-review list-rules

# JSON output (includes compliance refs, tags, severity, category)
nfr-review list-rules --format json
```

### Get details on a specific rule

```bash
nfr-review explain ci-test-stage-missing
```

### Run a hygiene audit

```bash
# Full hygiene audit (documentation, CI, community, build readiness, privacy)
nfr-review hygiene /path/to/target/repo

# License compliance only (requires scancode extra)
nfr-review hygiene --category license /path/to/target/repo

# List all registered hygiene checks
nfr-review hygiene --list-checks
```

Without the `[scancode]` extra installed, license rules are skipped with an informative warning — all other hygiene categories still run normally.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--list-checks` | off | List registered hygiene checks and exit |
| `--output-dir PATH` | `.` | Directory where CSV and JSONL files are written |
| `--format FORMAT` | `both` | Output format: `csv`, `jsonl`, or `both` |
| `--severity-threshold LEVEL` | — | Exit 2 if any finding meets or exceeds this severity |
| `--category NAMES` | — | Comma-separated category names to filter rules |
| `--config PATH` | `./nfr-review.yaml` (if present) | Path to configuration file |
| `--exclude-tests` / `--include-tests` | exclude | Exclude test and fixture directories from analysis |
| `-v` / `-q` / `--log-file` | — | Same as `run` command |

### Generate a full report

```bash
# Run NFR + hygiene + pytest + deps and produce timestamped files in reports/
nfr-review report /path/to/target/repo

# Skip PDF generation
nfr-review report --no-pdf /path/to/target/repo

# Skip LLM summary (PDF still generated, without summary section)
nfr-review report --no-summary /path/to/target/repo

# Skip design maturity score computation
nfr-review report --no-score /path/to/target/repo
```

This produces timestamped files under `reports/`:
- `{repo}-nfr-review-{timestamp}.md` — Markdown report with NFR findings, hygiene findings, test results, and dependency summary
- `{repo}-nfr-review-{timestamp}.csv` — combined CSV findings
- `{repo}-nfr-review-{timestamp}.jsonl` — combined JSONL run record
- `{repo}-nfr-review-{timestamp}.pdf` — PDF report (enabled by default; use `--no-pdf` to skip)

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--config PATH` | `./nfr-review.yaml` (if present) | Path to configuration file |
| `--output-dir PATH` | `reports/` | Directory where report files are written |
| `--no-pdf` | — | Skip PDF report generation (PDF is generated by default) |
| `--no-summary` | off | Skip LLM executive summary (PDF will omit summary section) |
| `--no-score` | off | Skip design maturity score computation |
| `--no-tests` | off | Skip pytest execution |
| `--no-deps` | off | Skip dependency tree analysis |
| `--no-diagrams` | off | Suppress Mermaid diagram sections in the report |
| `--exclude-tests` / `--include-tests` | exclude | Exclude test and fixture directories from analysis |
| `--sarif PATH` | — | Output path for SARIF 2.1.0 findings file |
| `--test-timeout SECS` | `900` | Maximum seconds to wait for pytest to complete |
| `--max-resolve-rounds N` | `2000` | Maximum resolver iterations for dependency analysis |
| `--workers N` | `1` | Number of parallel collector threads (`1` = sequential) |
| `-v` / `-q` / `--log-file` | — | Same as `run` command |

### Analyze dependencies

```bash
# Show upgrade summary table and transitive dependency tree
nfr-review deps /path/to/target/repo

# Skip transitive resolution (faster)
nfr-review deps --no-tree /path/to/target/repo

# Write Markdown report to a file
nfr-review deps --output deps-report.md /path/to/target/repo

# Write Graphviz DOT dependency graph (optionally render to SVG)
nfr-review deps --dot deps.dot /path/to/target/repo
nfr-review deps --dot deps.dot --render-diagrams /path/to/target/repo
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--no-tree` | off | Skip transitive resolution and dependency tree (faster) |
| `--output PATH` | — | Write Markdown dependency report to FILE |
| `--dot PATH` | — | Write Graphviz DOT dependency graph to FILE |
| `--render-diagrams` | off | Render DOT graph to SVG (requires `[diagrams]` extra) |
| `--max-resolve-rounds N` | `2000` | Maximum resolver iterations for dependency analysis |
| `-v` / `-q` / `--log-file` | — | Same as `run` command |

### Generate architecture documentation \[experimental\]

```bash
# Generate architecture docs for a single repo (JSON + Markdown + PDF)
nfr-review arch /path/to/target/repo

# Generate for multiple repos as a unified report
nfr-review arch /path/to/repo1 /path/to/repo2

# Skip LLM-based analysis (domain model enhancement, market comparison)
nfr-review arch --no-llm /path/to/target/repo

# Output only JSON and Markdown (no PDF)
nfr-review arch --format json --format md /path/to/target/repo
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir PATH` | `reports` | Directory where report files are written |
| `--format FORMAT` | `json` + `md` + `pdf` | Output format(s): `json`, `md`, `pdf` (repeat for multiple) |
| `--no-llm` | off | Skip LLM-based analysis (domain model enhancement, market comparison) |
| `--diagram-mode MODE` | `hierarchical` | Component diagram layout: `hierarchical` (overview + detail) or `flat` |
| `-v` / `-q` / `--log-file` | — | Same as `run` command |

### Initialize a configuration file

```bash
# Auto-detect technologies and generate nfr-review.yaml
nfr-review init /path/to/target/repo

# Preview without writing a file
nfr-review init --dry-run /path/to/target/repo
```

### File or sync GitHub issues

```bash
# Scan and file issues for high-severity findings
nfr-review issues scan /path/to/target/repo

# Preview without filing
nfr-review issues scan --dry-run /path/to/target/repo

# Sync issues from a prior JSONL scan file
nfr-review issues sync findings.jsonl --repo owner/repo

# Preview sync decisions without calling GitHub
nfr-review issues sync findings.jsonl --dry-run
```

**`issues scan` options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Preview issues without filing to GitHub |
| `--repo OWNER/REPO` | auto-detect | GitHub owner/repo (auto-detected from git remote) |
| `--severity-threshold` | `high` | Minimum severity for filing issues |
| `--config PATH` | `./nfr-review.yaml` | Path to configuration file |
| `-v` / `-q` / `--log-file` | — | Same as `run` command |

**`issues sync` options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--repo OWNER/REPO` | — | GitHub owner/repo (required unless `--dry-run`) |
| `--extra-labels LABELS` | — | Comma-separated extra labels to apply |
| `--rag-min LEVEL` | `amber` | Minimum RAG level for filing: `red`, `amber`, `green` |
| `--severity-threshold` | `high` | Minimum severity for filing issues |
| `--first-run-cap N` | `25` | Max issues to create on first sync |
| `--close-resolved` / `--no-close-resolved` | close | Close issues whose findings are no longer present |
| `--dry-run` | off | Preview decisions without calling GitHub |

### Run everything at once

`nfr-review all` runs an architecture review across all targets and an NFR report per target in a single invocation.

```bash
# Architecture + NFR reports for two repos
nfr-review all /path/to/repo1 /path/to/repo2

# Skip architecture, just batch NFR reports
nfr-review all /path/to/repo1 /path/to/repo2 --no-arch

# Custom output directory, skip PDF and tests
nfr-review all /path/to/repo1 --output-dir my-reports --no-pdf --no-tests
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output-dir` | `reports` | Directory for all output files |
| `--no-arch` | off | Skip the cross-repo architecture report |
| `--no-tests` | off | Skip pytest execution per repo |
| `--no-deps` | off | Skip dependency analysis |
| `--no-diagrams` | off | Suppress Mermaid diagrams in NFR reports |
| `--no-pdf` | off | Skip PDF generation |
| `--no-summary` | off | Skip LLM executive summary |
| `--no-score` | off | Skip maturity score |
| `--no-llm` | off | Skip LLM analysis in architecture report |
| `--diagram-mode` | `hierarchical` | Architecture diagram layout |
| `--test-timeout` | `900` | Pytest timeout per repo (seconds) |
| `--workers` | `1` | Parallel collector threads per repo |
| `--exclude-tests` | exclude | Exclude test directories from NFR analysis |

### Check version

```bash
nfr-review version
```

## Configuration

Create an `nfr-review.yaml` in your working directory (or pass `--config`). All fields are optional — an empty file or no file at all uses safe defaults.

```yaml
version: 1

# Declare which technology stacks the target repo uses.
# Rules requiring a tech that isn't declared true will be skipped.
# 18 tech keys are auto-detected; these override detection results.
tech:
  spring_boot: true
  apim: false
  terraform: false
  cmake: true   # enables C++ rules

# Control which rules run.
rules:
  skip:
    - sample-readme-exists      # skip specific rules by ID
  # include_only:               # or run only these (mutually exclusive with skip)
  #   - ci-test-stage-missing
  #   - probes-missing

# Control which collectors run.
collectors:
  skip: []

# If any finding has severity >= this threshold, exit code is 2.
# Valid values: info, low, medium, high, critical
severity_threshold: high

# Glob patterns for paths to exclude from all collectors.
# Built-in exclusions (.venv, node_modules, .regression-repos, etc.) always apply.
exclude_paths:
  - "vendor/**"
  - "third_party/**"

# Set to false to include test directories in analysis (default: excluded).
exclude_test_paths: true
```

## Rules

nfr-review ships with 134 rules (106 NFR + 28 hygiene) across several domains. A selection:

| Rule ID | Domain | Description |
|---------|--------|-------------|
| `sample-readme-exists` | General | Verify a README exists at the repo root |
| `ci-test-stage-missing` | CI/CD | Flag CI pipelines with no test step |
| `ci-security-scan-missing` | CI/CD | Flag CI pipelines with no security scanning |
| `adr-lifecycle-gap` | Architecture | Check ADR status lifecycle consistency |
| `architectural-drift-from-adr` | Architecture | Detect code diverging from ADR decisions (LLM-assisted) |
| `probes-missing` | Kubernetes | Flag deployments without liveness/readiness probes |
| `resource-limits-missing` | Kubernetes | Flag containers without CPU/memory limits |
| `network-policy-missing` | Kubernetes | Flag namespaces without network policies |
| `non-root-container-violation` | Kubernetes | Flag containers running as root |
| `health-endpoint-missing` | Java | Flag services without a health endpoint |
| `resilience-annotation-missing` | Java | Flag missing circuit breaker / retry patterns |
| `exception-handling-antipattern` | Java | Detect bare catch blocks and swallowed exceptions |
| `thread-pool-misconfiguration` | Java | Detect unbounded thread pools and queue configurations |
| `actuator-exposure-risk` | Spring | Flag insecure actuator endpoint exposure |
| `logging-config-missing` | Spring | Flag missing structured logging configuration |
| `spring-profile-misconfiguration` | Spring | Detect profile configuration issues |
| `apim-auth-policy-missing` | APIM | Flag API endpoints without authentication policies |
| `apim-hardcoded-backend-url` | APIM | Detect hardcoded backend URLs in APIM policies |
| `apim-rate-limit-missing` | APIM | Flag APIs without rate limiting |
| `pii-in-log-statements` | Security | Detect potential PII in log statements (LLM-assisted) |
| `cmake-build-config` | C++ | Flag CMake builds missing Release/RelWithDebInfo configuration |
| `cmake-fetchcontent-pinning` | C++ | Flag FetchContent dependencies without a pinned tag or hash |
| `cmake-minimum-version` | C++ | Flag cmake_minimum_required set below a supported floor |
| `cpp-clang-format` | C++ | Check for a `.clang-format` configuration in the repo |
| `cpp-clang-tidy` | C++ | Check for a `.clang-tidy` configuration in the repo |
| `cpp-exception-safety` | C++ | Flag unsafe exception handling patterns in C++ source |
| `cpp-include-guards` | C++ | Flag header files missing include guards or `#pragma once` |
| `cpp-raw-memory` | C++ | Flag raw `new`/`delete` usage that should use smart pointers |
| `cpp-sanitizer-ci` | C++ | Flag CI pipelines missing AddressSanitizer / UBSan steps |
| `dep-freshness` | Dependencies | Flag packages with updates available beyond their declared constraints |
| `dep-upgrade-path` | Dependencies | Identify packages that require multi-step version upgrades |
| `PATCH-*` (22 rules) | Patching | Deployment and infrastructure patching readiness analysis |

Rules marked "LLM-assisted" use an optional LLM call for deeper analysis and fall back gracefully when no API key is configured.

Use `nfr-review list-rules` to see the full list of registered rules, or `nfr-review explain <rule-id>` for details on any rule.

## Output

The `run` command produces two files (named after the target repository):

- **CSV** (`{repo}-nfr-review.csv`) — one row per finding, suitable for spreadsheet review
- **JSONL** (`{repo}-nfr-review.jsonl`) — first line is run metadata, subsequent lines are findings

The `report` command produces timestamped files under `reports/`:

- **Markdown** (`{repo}-nfr-review-{timestamp}.md`) — full report with NFR findings, hygiene findings, test results, and dependency summary
- **CSV** (`{repo}-nfr-review-{timestamp}.csv`) — combined findings from all scans
- **JSONL** (`{repo}-nfr-review-{timestamp}.jsonl`) — combined run record
- **PDF** (`{repo}-nfr-review-{timestamp}.pdf`) — rendered PDF with executive summary and diagrams (enabled by default; use `--no-pdf` to skip)

### Finding fields

| Field | Description |
|-------|-------------|
| `rule_id` | Which rule produced this finding |
| `rag` | Red / Amber / Green / Skipped |
| `severity` | critical / high / medium / low / info |
| `summary` | Human-readable description |
| `recommendation` | Suggested remediation |
| `evidence_locator` | File path or resource that triggered the finding |
| `collector_name` | Which collector gathered the evidence |
| `collector_version` | Collector version |
| `confidence` | 0.0 to 1.0 |
| `pattern_tag` | Classification tag for the pattern detected |
| `content_hash` | Line-number-independent hash for stable baseline diffing |

## Example: scanning the test fixtures

The repo includes sample fixtures you can scan immediately:

```bash
# Scan the Java sample repo (has Spring configs, K8s manifests, and Java source)
nfr-review run tests/fixtures/java-sample-repo

# Scan with a config that enables Spring tech
nfr-review run tests/fixtures/java-sample-repo \
  --config tests/fixtures/configs/tech-spring-only.yaml

# View findings
cat java-sample-repo-nfr-review.csv
```

## Development

```bash
# Run tests (parallel via pytest-xdist)
pytest -n auto

# Run tests with coverage
pytest -n auto --cov

# Lint
ruff check src/ tests/
ruff format --check src/ tests/
```

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) before submitting a pull request.

- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security Policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

## Development Transparency

This project was developed with AI assistance using Claude by Anthropic. AI tools were used for code generation, test writing, documentation, and code review during development. All AI-generated output was reviewed, tested, and validated by human maintainers before inclusion.

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
