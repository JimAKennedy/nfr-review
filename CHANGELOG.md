# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`--framework` compliance filter** — `nfr-review run` and `report` accept
  `--framework {soc2,iso27001,pci-dss,nist-800-53}` to restrict findings to
  rules mapped to the specified compliance framework. Unmapped rules are
  excluded from all output formats. Report header shows the active filter.
- **External rule plugin API** — third-party packages can register custom rules
  and hygiene rules via `nfr_review.rules` and `nfr_review.hygiene_rules`
  entry-point groups. See `CONTRIBUTING.md` for authoring guide.
- **Compliance mapping module** — `src/nfr_review/compliance_mapping.py`
  provides structured rule-to-framework mapping data extracted from
  `docs/continuous-compliance.md`.

### Changed

- **README restructured** — motivation section added; installation, usage, and
  CLI reference reorganised for clarity.
- **Collector failure surfacing** — when collectors fail or produce warnings,
  a summary line is printed across all output paths (not just verbose mode).
- **`all` command LLM cost warning** — the `all` command now prints a note
  when LLM-based features are active, warning about potential cost and time.

## [0.2.0] - 2026-06-12

### Added

- **Production interaction monitor** (experimental) — `nfr-review monitor`
  accepts live OTLP traces, fingerprints service interactions, and alerts on
  topology drift against a UAT baseline. Includes baseline management
  (`monitor baseline`) and stats reporting.
- **Dynamic analysis** — `--collector` flag on `run` and `report` starts an
  OpenTelemetry Collector sidecar, captures runtime traces, and extracts
  architecture diagrams from live traffic.
- **OTel diagram extraction** — Mermaid sequence and topology diagrams
  generated from OTel trace spans (`output/diagrams.py`).
- **Monitor test framework** — 109 tests covering the full monitor pipeline:
  fingerprinting, baseline comparison, alert classification, backpressure,
  and end-to-end OTLP ingestion.
- **`[monitor]` optional extra** — `pip install nfr-review[monitor]` for the
  production monitor (aiohttp-based OTLP receiver).
- **Lightweight reports** — `--slim` flag for minimal Markdown-only reports
  without PDF, diagrams, or LLM summaries.
- **Coverage at 88%** — formal coverage threshold enforced in CI.

### Changed

- Documentation reorganised: internal UAT scripts moved to `docs/internal/`.
- Dynamic analysis and monitor deployment docs expanded with installation
  instructions, architecture diagrams, and end-to-end workflow guides.
- README updated with supported technologies matrix (18 categories),
  architecture overview, and monitor CLI reference.
- `setup-all.sh` installs otelcol-contrib via direct binary download instead
  of the broken Homebrew tap.
- pyproject.toml classifiers updated for Python 3.13, typed package marker.

### Fixed

- JDepend metrics table in PDF reports: external packages with all-zero
  metrics are now filtered out; numeric columns use `white-space: nowrap`
  to prevent mid-number wrapping.
- LLM client no longer emits a noisy `WARNING` when no API key is
  configured; downgraded to `DEBUG` since LLM features are optional.

## [0.1.3] - 2026-06-08

### Fixed

- Pre-release version specifiers (e.g. `1.0.0-beta.1`) no longer crash
  the dependency solver with a `ValueError`. Versions that don't parse
  as valid PEP 440 are now treated as opaque strings with safe fallback
  comparisons.
- Added `.trivyignore` for 8 Debian base-image CVEs (Perl, xdg-utils,
  gh) that are not exploitable at runtime.

## [0.1.2] - 2026-06-06

### Fixed

- Hardened Docker image — bumped base from `python:3.11-slim` to
  `python:3.14-slim`, replaced Debian chromium with Puppeteer's bundled
  Chrome (reduces CVE surface), added required system libraries for
  headless Chrome rendering.
- Added smoke test gate to release workflow — image must pass
  `nfr-review --version` and a fixture scan before pushing to GHCR.

## [0.1.1] - 2026-06-06

### Added

- Mermaid rendering support and LLM SDKs added to Docker image.
- Docker usage instructions for amd64 image on Apple Silicon.

### Fixed

- amd64-only Docker build with decoupled release jobs.

## [0.1.0] - 2026-06-06

### Added

- **C++ scanning** — `cmake` and `cpp_ast` collectors plus 9 new rules:
  `cmake-build-config`, `cmake-fetchcontent-pinning`, `cmake-minimum-version`,
  `cpp-clang-format`, `cpp-clang-tidy`, `cpp-exception-safety`,
  `cpp-include-guards`, `cpp-raw-memory`, `cpp-sanitizer-ci`.
  C++ build readiness also covered in hygiene audits.
- **PDF report generation** — `report` produces a PDF by default (skip with `--no-pdf`) with rendered
  Mermaid diagrams and an LLM-generated executive summary (`output/pdf.py`,
  `output/render.py`, `output/summarize.py`, `output/summary_models.py`).
  Use `--no-summary` to omit the summary section. Requires `[pdf]` extra
  (weasyprint-based).
- **Dependency analysis** — `deps` command with transitive resolution via
  resolvelib (`deps_analysis.py`, `dep_solver.py`, `deps_dev_client.py`),
  upgrade summary table, Graphviz DOT graph output (`output/dot.py`), and
  Markdown report (`output/deps_report.py`).
- **`report` command** — orchestrates NFR scan + hygiene scan + pytest +
  dependency analysis + diagram rendering + optional executive summary into a
  unified timestamped report (Markdown + CSV + JSONL + optional PDF) under
  `reports/`. New flags: `--no-tests`, `--no-deps`, `--no-diagrams`.
- **22 PATCH-* rules** for deployment and infrastructure patching readiness
  analysis.
- **`dep-freshness`** and **`dep-upgrade-path`** rules for dependency currency
  checks.
- **Path filtering** — `--exclude-tests` flag on `run`, `hygiene`, and `report`
  commands; `exclude_paths` and `exclude_test_paths` config fields; built-in
  auto-exclusion of infrastructure directories (`.venv`, `node_modules`,
  `.regression-repos`, etc.).
- **Repo name in output filenames and report headers** — output files are now
  named `{repo}-nfr-review.{ext}` rather than the generic `nfr-review.{ext}`.
- **`-v`/`--verbose`**, **`-q`/`--quiet`**, and **`--log-file`** flags added
  to `run`, `hygiene`, and `report` commands.
- **Hygiene audit improvements** — 7 auditable categories now include build
  readiness checks for C++ projects (`bld_` prefix rules).
- **`output/diagrams.py`** — Mermaid diagram section helpers shared across
  Markdown and PDF rendering.
- **C#/Node.js AST collectors** — `csharp_ast` and `nodejs_ast` collectors
  registered; initial implementation for structural evidence gathering.
- **NIST 800-53 Rev 5 compliance mapping** — 28 controls mapped across 12
  control families in `docs/continuous-compliance.md`, alongside existing
  SOC 2, ISO 27001, and PCI DSS v4.0 mappings.
- **Typed evidence payloads** — all collectors now emit `BasePayload`
  subclasses instead of plain dicts, enabling IDE completion and schema
  validation on evidence payloads (`collectors/payloads/`).
- **Rule metadata catalogue** — rules carry `RuleMetadata` with severity,
  category, tags, and compliance references; `list-rules --format json`
  exports the full catalogue.
- **Design maturity scoring** — configurable 0–100 maturity score with
  ISO 25010 categories, severity deductions, grade scale (A–F), and trend
  tracking via `--baseline`. Configured under `scoring:` in
  `nfr-review.yaml`.
- **Parallel collector execution** — `--workers N` flag on `run`, `report`,
  and `all` commands for concurrent evidence gathering.
- **Multi-backend LLM support** — three backends: Anthropic API
  (`[llm-anthropic]`), OpenAI-compatible APIs (`[llm-openai]`), and
  Claude CLI. Configured via `llm:` in `nfr-review.yaml` or env vars.
- **`all` command** — runs architecture review (cross-repo) + NFR report
  (per-repo) in a single invocation.
- **`issues` command** — `issues scan` and `issues sync` for filing and
  syncing GitHub issues from findings.
- **SARIF output** — `--sarif` flag on `run` and `report` commands for
  SARIF 2.1.0 findings files and GitHub Security tab integration.
- **Baseline diffing** — `--baseline` flag suppresses known findings using
  content-hash-based stable identity keys.
- **GitHub Action** — `action.yml` with pip and container execution modes,
  PR comments, SARIF upload, issue sync, and baseline diffing.
- **Rule catalogue site** — browsable HTML catalogue published to GitHub
  Pages via `scripts/generate_catalogue.py`.

- Multi-language AST analysis for Java, Python, Go, C#, and Node.js
- Infrastructure scanning: Kubernetes manifests, Helm charts, Terraform,
  Dockerfiles, Istio service mesh, OpenTelemetry, Skaffold, and Protobuf
- CI/CD pipeline analysis (GitHub Actions)
- ADR (Architecture Decision Record) lifecycle checks
- LLM-assisted rules via Anthropic API: PII detection, ADR drift analysis
- Spring Boot configuration and API Management policy analysis
- CSV and JSONL output formats
- YAML-based project configuration with tech auto-detection
- Pluggable collector/rule architecture with registry-based discovery
- Evidence-based findings with RAG severity rating (Red/Amber/Green)

### Fixed

- Reduced CPP-001 (`cpp-raw-memory`) false positives for VSTGUI
  ref-counted patterns, placement new, and operator overloads.
- Mermaid diagram sanitization for brackets, commas, and annotation
  spacing.
- Replaced broad `except Exception` catches with specific exception types.
