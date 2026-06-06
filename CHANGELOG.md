# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
