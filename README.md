# nfr-review

[![CI](https://github.com/JimAKennedy/nfr-review/actions/workflows/ci.yml/badge.svg)](https://github.com/JimAKennedy/nfr-review/actions/workflows/ci.yml)
[![coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/JimAKennedy/af34283def743414fcf7c3ade1155881/raw/nfr-review-coverage.json)](https://github.com/JimAKennedy/nfr-review/actions/workflows/ci.yml)
[![mypy](https://img.shields.io/badge/mypy-strict-blue)](https://github.com/JimAKennedy/nfr-review/blob/main/pyproject.toml)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Automated non-functional design reviews for software projects.

`nfr-review` scans a repository for architectural evidence (Spring configs, K8s manifests, CI pipelines, ADRs, Java source, APIM policies) and evaluates 20 rules covering resilience, observability, security, and operational readiness. Findings are emitted as CSV and JSONL for integration into review workflows.

## Quick start

```bash
# Clone and install (requires Python 3.11+)
git clone https://github.com/JimAKennedy/nfr-review.git
cd nfr-review
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

# Run against a target repository
nfr-review run /path/to/your/repo
```

## Requirements

- Python 3.11+ (`python3.11`, `python3.12`, etc. — macOS ships 3.9 as `python3` which is too old)
- Dependencies are installed automatically via `pip install -e .`

## Installation

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .           # core CLI only
pip install -e ".[llm]"    # adds Anthropic SDK for LLM-assisted rules
pip install -e ".[dev]"    # includes llm + pytest, ruff, pytest-cov
```

The `[llm]` extra adds the Anthropic SDK for LLM-assisted rules (PII detection, ADR drift). Without it, those rules fall back gracefully. The `[dev]` extra includes `[llm]` plus test/lint tooling.

## API key (optional)

LLM-assisted rules (PII detection, ADR drift analysis) require an Anthropic API key. Set it as an environment variable:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
nfr-review run /path/to/repo
```

Without the key, these rules are skipped gracefully and all other rules still run normally.

## Usage

### Scan a repository

```bash
nfr-review run /path/to/target/repo
```

This will:
1. Collect evidence from the target repo (Spring configs, K8s manifests, CI workflows, Java source, ADRs, APIM policies)
2. Evaluate all applicable rules against the collected evidence
3. Write findings to `nfr-review.csv` and `nfr-review.jsonl` in the current directory
4. Print a summary to stderr

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--config PATH` | `./nfr-review.yaml` (if present) | Path to configuration file |
| `--csv PATH` | `nfr-review.csv` | Output path for CSV findings |
| `--jsonl PATH` | `nfr-review.jsonl` | Output path for JSONL run record |

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | Success — scan completed |
| 1 | Error — bad target path, config error, or engine failure |
| 2 | Threshold breach — at least one finding meets or exceeds `severity_threshold` |

### List available rules

```bash
nfr-review list-rules
```

### Get details on a specific rule

```bash
nfr-review explain ci-test-stage-missing
```

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
tech:
  spring_boot: true
  apim: false
  kafka: false

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
```

## Rules

nfr-review ships with 20 rules across several domains:

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

Rules marked "LLM-assisted" use an optional LLM call for deeper analysis and fall back gracefully when no API key is configured.

## Output

Each scan produces two files:

- **CSV** (`nfr-review.csv`) — one row per finding, suitable for spreadsheet review
- **JSONL** (`nfr-review.jsonl`) — first line is run metadata, subsequent lines are findings

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

## Example: scanning the test fixtures

The repo includes sample fixtures you can scan immediately:

```bash
# Scan the Java sample repo (has Spring configs, K8s manifests, and Java source)
nfr-review run tests/fixtures/java-sample-repo

# Scan with a config that enables Spring tech
nfr-review run tests/fixtures/java-sample-repo \
  --config tests/fixtures/configs/tech-spring-only.yaml

# View findings
cat nfr-review.csv
```

## Development

```bash
# Run tests
pytest

# Run tests with coverage
pytest --cov

# Lint
ruff check src/ tests/
ruff format --check src/ tests/
```

## Development Transparency

This project was developed with AI assistance using Claude by Anthropic. AI tools were used for code generation, test writing, documentation, and code review during development. All AI-generated output was reviewed, tested, and validated by human maintainers before inclusion.

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
