# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **C++ scanning** — `cmake` and `cpp_ast` collectors plus 9 new rules:
  `cmake-build-config`, `cmake-fetchcontent-pinning`, `cmake-minimum-version`,
  `cpp-clang-format`, `cpp-clang-tidy`, `cpp-exception-safety`,
  `cpp-include-guards`, `cpp-raw-memory`, `cpp-sanitizer-ci`.
  C++ build readiness also covered in hygiene audits.
- **PDF report generation** — `report --pdf` produces a PDF with rendered
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
- **Path filtering** — `--include-tests` flag on `run`, `hygiene`, and `report`
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

## [0.1.0] - 2026-05-08

### Added

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
