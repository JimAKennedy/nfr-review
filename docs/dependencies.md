<!-- Copyright 2026 nfr-review contributors — Licensed under Apache-2.0 -->

# External Dependencies

This page catalogs every external dependency nfr-review relies on — Python
libraries, LLM providers, GitHub Actions, external APIs, CI services, and
runtime binaries. Use it to understand what an adopter needs to install, pay
for, or adapt when forking or deploying nfr-review internally.

**Core analysis has zero external API dependencies.** All static-analysis
rules run locally using bundled tree-sitter grammars and Python libraries.
Optional features (LLM analysis, dependency freshness, container scanning,
issue sync) add external dependencies that degrade gracefully when
unavailable.

---

## Table of contents

1. [Python core dependencies](#1-python-core-dependencies)
2. [Python optional extras](#2-python-optional-extras)
3. [LLM providers](#3-llm-providers)
4. [External APIs](#4-external-apis)
5. [GitHub Actions](#5-github-actions)
6. [CI services and infrastructure](#6-ci-services-and-infrastructure)
7. [Runtime binaries](#7-runtime-binaries)
8. [Environment variables](#8-environment-variables)
9. [Container image](#9-container-image)
10. [Plugin system](#10-plugin-system)

---

## 1. Python core dependencies

These are installed automatically with `pip install nfr-review`. All are
required for the tool to start.

| Package | Constraint | Purpose | Adaptation notes |
|---------|-----------|---------|------------------|
| click | `>=8.1` | CLI framework — powers the `nfr-review` command | Standard CLI library |
| pydantic | `>=2` | Data validation and serialization for findings, evidence, config | Must be v2 (not v1) |
| ruamel.yaml | `>=0.18` | YAML parsing for config files, Helm values, K8s manifests | Uses ruamel.yaml (not PyYAML) for round-trip fidelity |
| tree-sitter | `>=0.23` | Core parsing engine for static analysis of source files | None |
| tree-sitter-java | `>=0.23` | Java language grammar | Remove if Java analysis unneeded |
| tree-sitter-python | `>=0.23` | Python language grammar | Remove if Python analysis unneeded |
| tree-sitter-go | `>=0.23` | Go language grammar | Remove if Go analysis unneeded |
| tree-sitter-hcl | `>=1.1` | HCL/Terraform grammar for IaC analysis | Remove if Terraform analysis unneeded |
| tree-sitter-dockerfile | `>=0.2` | Dockerfile grammar for container rules | Excluded on `aarch64` (no wheel). Build amd64-only for full coverage |
| tree-sitter-c-sharp | `>=0.23` | C# grammar for .NET project analysis | Remove if C# analysis unneeded |
| tree-sitter-typescript | `>=0.23` | TypeScript/JavaScript grammar | Remove if TS/JS analysis unneeded |
| tree-sitter-cpp | `>=0.23` | C++ grammar for native code analysis | Remove if C++ analysis unneeded |
| packaging | `>=24.0` | PEP 440 version parsing for dependency version rules | Standard Python packaging library |
| resolvelib | `>=1.0` | Dependency resolution algorithm for transitive dep analysis | None |

---

## 2. Python optional extras

Install extras individually or combine them:

```bash
pip install "nfr-review[llm-anthropic,pdf,scancode]"
pip install "nfr-review[full]"        # everything except scancode and otel
```

### `[llm-anthropic]` — Anthropic Claude API

| Package | Constraint | Purpose |
|---------|-----------|---------|
| anthropic | `>=0.40` | Anthropic Python SDK for Band 2 LLM-augmented rules |

Requires `ANTHROPIC_API_KEY`. Without the key, LLM rules are skipped
gracefully. Default model: `claude-sonnet-4-6`.

### `[llm-openai]` — OpenAI-compatible API

| Package | Constraint | Purpose |
|---------|-----------|---------|
| openai | `>=1.0` | OpenAI SDK for Ollama, Azure OpenAI, OpenRouter |

Set `NFR_LLM_PROVIDER=openai` and optionally `NFR_LLM_BASE_URL` for custom
endpoints.

### `[pdf]` — PDF report generation

| Package | Constraint | Purpose |
|---------|-----------|---------|
| weasyprint | `>=60` | HTML-to-PDF rendering engine |

Requires system libraries: libpango, libcairo, libharfbuzz, libgdk-pixbuf,
fonts-liberation. The Docker image includes these. Without them, use `--no-pdf`
or `--html`.

### `[diagrams]` — Architecture diagrams

| Package | Constraint | Purpose |
|---------|-----------|---------|
| graphviz | `>=0.20` | Python bindings for Graphviz DOT rendering |

Requires the system-level `graphviz` binary. Without it, diagram output is
skipped gracefully.

### `[otel]` — OpenTelemetry instrumentation

| Package | Constraint | Purpose |
|---------|-----------|---------|
| opentelemetry-api | `>=1.20` | OTel API surface |
| opentelemetry-sdk | `>=1.20` | OTel SDK implementation |
| opentelemetry-exporter-otlp-proto-common | `>=1.20` | OTLP exporter for trace data |

Used for dynamic analysis with `--otel-traces`. Without it, only static
analysis is available.

### `[scancode]` — License compliance scanning

| Package | Constraint | Purpose |
|---------|-----------|---------|
| scancode-toolkit | `>=32.0,<34` | License and copyright detection engine |
| typecode-libmagic | `>=5.39` | File type detection (libmagic bindings) |
| extractcode-libarchive | `>=3.5` | Archive extraction (libarchive bindings) |

Heavy dependency (~500 MB). The built-in `pip-licenses` check in CI is a
lighter alternative. Requires native libraries.

### `[monitor]` — Production interaction monitor

| Package | Constraint | Purpose |
|---------|-----------|---------|
| aiohttp | `>=3.9` | Async HTTP server for live analysis dashboards |

Only needed for the experimental production monitor feature.

### `[graphify]` — Structural knowledge-graph analysis

| Package | Constraint | Purpose |
|---------|-----------|---------|
| graphifyy | `>=0.8` | Tree-sitter-based codebase knowledge graph extraction and querying |
| networkx | `>=3.0` | In-process graph analysis (shortest path, degree metrics, community queries) |

Requires the `graphify` CLI binary (installed automatically with `graphifyy`).
When the binary is not available, the GraphifyCollector skips gracefully and
structural rules produce no findings. See the
[Graphify usage guide](graphify-guide.md) for a complete walkthrough.

### `[full]` — Convenience aggregate

Installs: `pdf` + `diagrams` + `llm-anthropic` + `llm-openai` + `otel` +
`monitor` + `graphify`. Does **not** include `scancode` (too heavy) or `dev`
(test dependencies).

### `[dev]` — Development and testing

| Package | Constraint | Purpose |
|---------|-----------|---------|
| pytest | `>=8.0` | Test runner |
| pytest-cov | `>=5.0` | Coverage reporting |
| pytest-timeout | `>=2.2` | Test timeout enforcement |
| pytest-xdist | `>=3.5` | Parallel test execution (`-n auto`) |
| pytest-asyncio | `>=0.23` | Async test support |
| pytest-aiohttp | `>=1.0` | aiohttp test client fixtures |
| filelock | `>=3.12` | File locking for parallel test isolation |
| ruff | `>=0.6` | Linter and formatter (CI pins exact version) |
| anthropic | `>=0.40` | Anthropic SDK for LLM-augmented rule tests |
| build | `>=1.0` | PEP 517 build frontend for sdist/wheel |

---

## 3. LLM providers

All LLM features are **optional**. When no provider is configured, LLM rules
are skipped gracefully and all static-analysis findings are still produced.

| Provider | SDK / binary | Auth | Default model | What it powers |
|----------|-------------|------|---------------|----------------|
| **Anthropic API** (default) | `anthropic>=0.40` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` | Executive summary, ADR drift, PII detection, domain inference |
| **OpenAI-compatible** | `openai>=1.0` | `OPENAI_API_KEY` | Varies | Same features via Ollama, Azure OpenAI, or OpenRouter |
| **Claude CLI** | `claude` binary on PATH | Claude Code subscription | N/A | Same features via Claude Code CLI — no API key needed |

**Adopter adaptation:** Provide your own API key or switch providers via
`NFR_LLM_PROVIDER` and `NFR_LLM_BASE_URL`. For air-gapped environments, use
Ollama with a local model.

---

## 4. External APIs

| API | Base URL | Auth | Purpose | If unavailable |
|-----|----------|------|---------|----------------|
| **deps.dev** (v3alpha) | `https://api.deps.dev/v3alpha` | None (public) | Dependency freshness, transitive dep analysis, version metadata | Freshness rules return no findings; core analysis unaffected |
| **GitHub API** | Via `gh` CLI | `GITHUB_TOKEN` | Issue sync, PR comments, baseline download | Issue sync and PR comments fail; core analysis unaffected |

**deps.dev endpoints used:**
- `GET /systems/{ecosystem}/packages/{package}` — version listing
- `GET /systems/{ecosystem}/packages/{package}/versions/{version}` — version detail
- `GET /systems/{ecosystem}/packages/{package}/versions/{version}:dependencies` — dependency graph

Ecosystems: pypi, npm, maven, nuget, go. Public API with rate limits. Client
uses in-memory cache and concurrent prefetch (8 workers, 10 s timeout).
Adopters behind corporate firewalls may need to allowlist `api.deps.dev`.

---

## 5. GitHub Actions

All actions are SHA-pinned for supply-chain security. Version comments show the
corresponding tag at time of pinning.

### Core workflow actions

| Action | Version | Used in | Purpose | Adaptation notes |
|--------|---------|---------|---------|------------------|
| `actions/checkout` | v6.0.3 | All workflows | Repository checkout | Standard |
| `actions/setup-python` | v6.2.0 | ci, release, nightly, pages, action | Python runtime setup | Versions tested: 3.11, 3.12 |
| `actions/cache` | v5.0.5 | ci, nightly | Cache pip packages and regression repos | Keys use pyproject.toml hash |
| `actions/upload-artifact` | v7.0.1 | ci, pr, nightly | Upload findings, coverage, SARIF | Standard |

### CI-specific actions

| Action | Version | Used in | Purpose | Adaptation notes |
|--------|---------|---------|---------|------------------|
| `azure/setup-helm` | v5.0.0 | ci, nightly | Install Helm binary for chart analysis | Required for Helm collector tests |
| `dorny/paths-filter` | v4.0.1 | ci | Skip Docker jobs when no Docker files changed | Optimization only — safe to remove |
| `gitleaks/gitleaks-action` | v3.0.0 | ci | Secret scanning in git history | Requires `GITLEAKS_LICENSE` for commercial use. Advisory only |
| `schneegans/dynamic-badges-action` | v1.8.0 | ci | Coverage badge via GitHub Gist | Requires `GIST_TOKEN`. Cosmetic only |
| `aquasecurity/trivy-action` | v0.36.0 | ci, release | Container CVE scanning (CRITICAL/HIGH gate) | Downloads Trivy DB at runtime. May need proxy behind firewalls |

### Docker and release actions

| Action | Version | Used in | Purpose | Adaptation notes |
|--------|---------|---------|---------|------------------|
| `docker/setup-buildx-action` | v4.1.0 | ci, release | Docker Buildx for multi-platform builds | Standard Docker CI setup |
| `docker/login-action` | v4.2.0 | release | GHCR authentication for image push | Change registry and creds if not using GHCR |
| `docker/metadata-action` | v6.1.0 | release | Semver tags and OCI labels | Change image name if forking |
| `docker/build-push-action` | v7.2.0 | ci, release | Build and push Docker images | Currently linux/amd64 only |
| `sigstore/cosign-installer` | v4.1.2 | release | Container image signing (keyless via Fulcio) | Requires `id-token:write` for OIDC |
| `anchore/sbom-action` | v0.24.0 | release | SPDX SBOM for container images | Output attested with cosign |
| `pypa/gh-action-pypi-publish` | v1.14.0 | release | Publish to PyPI via OIDC trusted publishing | Set up your own PyPI project if forking |
| `softprops/action-gh-release` | v3.0.0 | release | Create GitHub Release with changelog | Standard |

### Composite action (action.yml) actions

| Action | Version | Purpose | Adaptation notes |
|--------|---------|---------|------------------|
| `github/codeql-action/upload-sarif` | v4 | Upload SARIF to Security tab | Requires Code Scanning enabled |
| `peter-evans/find-comment` | v4.0.0 | Find existing PR comment for update | Requires `pull-requests:write` |
| `peter-evans/create-or-update-comment` | v5 | Post/update sticky PR comment | Requires `pull-requests:write` |
| `actions/upload-pages-artifact` | v5.0.0 | Upload rule catalogue for Pages | Only if publishing catalogue |
| `actions/deploy-pages` | v5.0.0 | Deploy catalogue to GitHub Pages | Requires Pages enabled |

---

## 6. CI services and infrastructure

These external services are used by CI workflows but are not required for
local CLI usage.

| Service | Purpose | If unavailable | Adaptation notes |
|---------|---------|----------------|------------------|
| **GitHub Container Registry (GHCR)** | Hosts pre-built Docker image | Container mode fails; pip mode works | Change image name in action.yml if forking |
| **Trivy Vulnerability Database** | CVE data for container scanning | CVE scan job fails (not a CI gate) | May need proxy/mirror behind firewalls |
| **Gitleaks** | Secret scanning | Scan skips (advisory only) | Requires `GITLEAKS_LICENSE` for commercial use |
| **Sigstore / Fulcio / Rekor** | Container image signing (keyless) | Release images are unsigned | Requires `id-token:write` |
| **Anchore Syft** | SPDX SBOM generation | No SBOM on releases | Used via `anchore/sbom-action` |
| **PyPI** | Package distribution | Must install from source | Set up your own PyPI project if forking |
| **GitHub Pages** | Rule catalogue website | No hosted catalogue | Requires Pages enabled on repo |
| **GitHub Gist** | Coverage badge storage | Badge shows stale data | Requires `GIST_TOKEN` + `COVERAGE_GIST_ID` |

---

## 7. Runtime binaries

External binaries detected at runtime via `shutil.which()`. None are strictly
required — features degrade gracefully when missing.

| Binary | Purpose | If missing | Where installed |
|--------|---------|------------|-----------------|
| **git** | Repo metadata, commit history, remote URL detection | Metadata collectors produce no output | Docker image; all CI runners |
| **helm** | `helm template` rendering for Kubernetes chart analysis | Helm collector uses values.yaml only (no rendered manifests) | `azure/setup-helm` in CI |
| **gh** | Issue sync and baseline download in Actions | Issue sync and PR baseline features fail | Pre-installed on GitHub-hosted runners |
| **claude** | Claude CLI LLM backend (`NFR_LLM_PROVIDER=claude-cli`) | Claude CLI backend unavailable; other providers work | Claude Code installation |
| **docker** | Container execution mode and CI Docker jobs | Container mode fails; pip mode works | Pre-installed on GitHub-hosted runners |
| **otelcol-contrib** | Managed OTel Collector for dynamic analysis | Must use `--otel-traces` with pre-collected traces instead | `scripts/setup-all.sh` or manual download |
| **graphviz** (dot) | DOT diagram rendering for architecture reports | Diagram output skipped | System package (`apt install graphviz`) |
| **graphify** | Codebase knowledge-graph extraction for structural analysis rules | GraphifyCollector skips; structural rules produce no findings | `pip install "nfr-review[graphify]"` (installed with the Python package) |

---

## 8. Environment variables

No environment variables are required for core static analysis.

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | For LLM features (Anthropic) | Anthropic Claude API authentication |
| `OPENAI_API_KEY` | For LLM features (OpenAI) | OpenAI-compatible API authentication |
| `NFR_LLM_PROVIDER` | No | Override LLM provider: `anthropic` (default), `openai`, `claude-cli` |
| `NFR_LLM_MODEL` | No | Override LLM model name |
| `NFR_LLM_BASE_URL` | No | Override LLM API base URL (proxies, Ollama, Azure) |
| `GITHUB_TOKEN` | For issue sync / SARIF upload | Auto-provided in GitHub Actions |
| `GIST_TOKEN` | For coverage badge | Personal access token for Gist updates |
| `GITLEAKS_LICENSE` | For secret scanning | Commercial license key |
| `COVERAGE_GIST_ID` | For coverage badge | Gist ID (repository variable, not secret) |

---

## 9. Container image

The pre-built Docker image is published to GHCR on each tagged release.

| Property | Value |
|----------|-------|
| **Registry** | `ghcr.io/jimakennedy/nfr-review` |
| **Base image** | `python:3.14-slim` |
| **Architecture** | `linux/amd64` only |
| **User** | Non-root `nfr` (UID 1000) |
| **Python extras** | `pdf`, `diagrams`, `llm-anthropic`, `llm-openai` (excludes `graphify` — add manually if needed) |

**System packages in the image:** libpango, libpangocairo, libpangoft2,
libharfbuzz, libcairo2, libgdk-pixbuf, libffi, shared-mime-info,
fonts-liberation, git.

**Not included:** Node.js, Chromium, mermaid-cli. Diagrams use bundled
client-side Mermaid.js in HTML reports and pure-Python SVG fallbacks in PDF.

**Adopter adaptation:** Update the `LABEL` metadata, GHCR image name, and
Dockerfile base image if forking.

---

## 10. Plugin system

nfr-review supports external rule packs via Python entry points:

| Entry point group | Purpose |
|-------------------|---------|
| `nfr_review.rules` | Register additional NFR rules |
| `nfr_review.hygiene_rules` | Register additional hygiene rules |

Third-party plugins install themselves as Python packages with entry points.
Discovery is automatic via `importlib.metadata.entry_points()` — no central
registry.

See the [Custom Rules Guide](custom-rules.md) for details on writing rule
plugins.
