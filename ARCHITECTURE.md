# Architecture

This document defines where logic belongs in nfr-review. Read it before adding
a collector, rule, output format, or config option.

## Data Flow

```
CLI (cli.py)
  |
  v
load_config() --> Config
  |
  v
detect_technologies() --> dict[str, bool]  (merged into Config.tech)
  |
  v
Engine.run(target, config)
  |
  +-- Phase 1: Collectors  -->  list[Evidence]
  |
  +-- Phase 2: Rules       -->  list[RuleResult]  (each contains list[Finding])
  |
  +-- Phase 3: Metadata    -->  RunMetadata (git SHA, versions, timestamps)
  |
  v
RunResult(findings, rule_results, run_metadata, warnings)
  |
  +-- write_csv()   --> 10-column CSV
  +-- write_jsonl() --> JSONL (metadata line + finding lines)
  |
  v
Exit code: 0 (clean), 1 (error), 2 (severity threshold exceeded)

report command (nfr-review report <target>):

  NFR Engine.run()     -->  RunResult (nfr_result)
  Hygiene Engine.run() -->  RunResult (hygiene_result)
  run_pytest()         -->  PytestResult (optional, --no-tests to skip)
  analyze_deps()       -->  list[DepReport] (optional, --no-deps to skip)
        |
        v
  partition_findings()  -->  (source_findings, test_findings)
        |
        v
  render_markdown_report()  -->  Markdown report
        |
        +-- write_csv()      (combined findings)
        +-- write_jsonl()    (combined findings)
        |
        v  [--no-pdf to skip]
  generate_executive_summary()  -->  SummaryResult  (LLM, --no-summary skips)
        |
        v
  render_pdf_report()  -->  PDF (weasyprint)
        |
  Timestamped files in reports/:
    {repo}-nfr-review-{timestamp}.md
    {repo}-nfr-review-{timestamp}.csv
    {repo}-nfr-review-{timestamp}.jsonl
    {repo}-nfr-review-{timestamp}.pdf  (--no-pdf to skip)

deps command (nfr-review deps <target>):

  analyze_deps()  -->  list[DepReport]
        |
        +-- render_deps_terminal()  -->  stdout summary table
        +-- render_deps_section()   -->  Markdown (--output)
        +-- render_dot_dependency_graph()  -->  DOT file (--dot)
        +-- render_dot_to_file()           -->  SVG (--render-diagrams)

arch command (nfr-review arch <targets...>):

  Collectors  -->  list[Evidence]  (multi-repo)
        |
        v
  arch_integrations  -->  components, integrations, risks, recommendations
        |
        +-- JSON report    -->  {repo}-architecture.json
        +-- Markdown report  -->  {repo}-architecture.md
        +-- arch_diagrams    -->  Mermaid diagrams (C4 levels)
        +-- PDF report       -->  {repo}-architecture.pdf  (via weasyprint)

issues command (nfr-review issues <scan|sync>):

  issues scan:  Engine.run() --> file issues for red/high-severity findings
  issues sync:  JSONL input  --> create/update/close GitHub issues

all command (nfr-review all <target1> <target2> ...):

  Phase 1:  run_arch_review(all targets)  -->  architecture report (cross-repo)
  Phase 2:  run_report_pipeline(target)   -->  NFR report (per target, loop)
  Output:   {repo}-architecture.* + {repo}-nfr-review-{ts}.* per repo
```

## Module Responsibility Map

| Module | Owns | Does NOT own |
|--------|------|-------------|
| `cli.py` | Argument parsing, config loading, orchestration (`run`, `report`, `hygiene`, `arch`, `deps`, `issues`, `init`, `all`, `list-rules`, `explain`, `version`), `run_report_pipeline()` reusable pipeline, exit codes, summary output | Evidence gathering, rule evaluation, output formatting |
| `config.py` | YAML loading, Pydantic validation, `Config`/`RulesConfig`/`CollectorsConfig` models | Tech detection, defaults beyond schema defaults |
| `detect.py` | File-system probing for 18 tech keys, `_DETECTORS` dispatch dict | Config merging (CLI does that), collector logic |
| `engine.py` | Collector execution, rule filtering (skip/include_only/tech/collectors), rule evaluation, fault tolerance | Individual collector or rule logic, output writing |
| `models.py` | `Evidence`, `Finding`, `RuleResult`, `RunResult`, `RunMetadata`, `RAG`, `Severity`, `Band` | Serialization format details (CSV column order lives in output/) |
| `protocols.py` | `Collector` and `Rule` runtime-checkable protocols | Registration, instantiation |
| `registry.py` | Generic `Registry[T]` container, global singletons `rule_registry` / `collector_registry` | What gets registered (that's the plugin modules' job) |
| `llm_client.py` | Anthropic SDK wrapper, availability gating, `ClaudeClient` | Prompt design (rules own their prompts), evidence selection |
| `auditability.py` | Git probe (SHA, branch, dirty), `RunMetadata` assembly | Output writing, config |
| `collectors/*` | Evidence gathering from target repo files | Evaluating findings, accessing config.rules |
| `rules/*` | Evaluating evidence into findings with RAG/severity/recommendation | Gathering evidence, file I/O on target repo |
| `hygiene/collectors/license_scan.py` | scancode-based license/copyright scanning (`license-scan` + `license-scan-summary` evidence), optional dependency with graceful skip | Rule evaluation, SPDX validation |
| `hygiene/rules/lic_*.py` | License compliance rules: copyleft detection (HYG-LIC-001), NOTICE completeness (HYG-LIC-002), header presence (HYG-LIC-003), SPDX validation (HYG-LIC-004) | Evidence gathering, scancode API calls |
| `output/*` | CSV and JSONL serialization, `OutputError` | Finding logic, metadata assembly |
| `path_filter.py` | Pre-aggregation test-path detection (`is_test_path`), configurable path exclusion (`should_exclude_path`, `compile_exclude_patterns`); used by collectors to drop evidence before it reaches rules | Rule evaluation, output classification |
| `output/classify.py` | Path-based source/test classification (`classify_region`, `partition_findings`) | Finding evaluation, rule logic |
| `output/markdown.py` | Markdown report rendering with partitioned findings, summary tables, test results, and dependency section | Data collection, engine orchestration |
| `output/pytest_runner.py` | Subprocess pytest execution, summary line parsing, `PytestResult` | Test framework logic, assertions |
| `output/pdf.py` | PDF report generation via weasyprint; assembles HTML from rendered Markdown + diagrams + summary section, converts to PDF | Markdown rendering, diagram rendering, LLM calls |
| `output/render.py` | Mermaid diagram rendering to PNG/SVG via subprocess; image embedding helpers for PDF | Diagram content generation, rule logic |
| `output/summarize.py` | LLM executive summary generation; calls `ClaudeClient` with structured findings, returns `SummaryResult` | PDF assembly, finding evaluation |
| `output/summary_models.py` | Pydantic models for executive summary: `SummaryResult`, `SummarySection`, `RiskItem` | LLM prompt design, serialization |
| `output/diagrams.py` | Mermaid diagram section helpers; generates architecture and dependency diagrams for Markdown and PDF | Diagram rendering (that's `render.py`), rule logic |
| `output/dot.py` | Graphviz DOT graph generation from `DepReport` list; `render_dot_to_file()` for SVG output | Dependency resolution, rule logic |
| `output/deps_report.py` | Markdown and terminal rendering of dependency analysis results (`render_deps_section`, `render_deps_terminal`) | Dependency resolution, finding evaluation |
| `deps_analysis.py` | Orchestrates per-ecosystem dependency analysis; calls dep solvers and `deps_dev_client`; returns `list[DepReport]` | Individual resolver logic, HTTP calls |
| `dep_solver.py` | resolvelib-based transitive dependency solver; `DepReport` model | Network I/O (delegated to `deps_dev_client`), output formatting |
| `deps_dev_client.py` | HTTP client for deps.dev API; package version and dependency metadata retrieval | Solving logic, caching policy |
| `arch_orchestrator.py` | Architecture report orchestration: multi-repo scanning, collector dispatch, report assembly | Individual collector or rule logic |
| `arch_models.py` | Pydantic models for architecture reports: `ArchComponent`, `ArchIntegration`, `ArchRisk`, `ArchRecommendation` | Report rendering, diagram generation |
| `arch_integrations.py` | Integration discovery, infra materialization, environment inference | Diagram rendering, report rendering |
| `arch_diagrams.py` | Mermaid C4 diagram generation (context, container, component, code levels) | Integration discovery, report assembly |
| `arch_discovery.py` | Component and boundary discovery from collected evidence | Rule evaluation, evidence gathering |
| `arch_domain_model.py` | LLM-assisted domain model enhancement for architecture reports | Evidence gathering, diagram rendering |
| `arch_market_comparison.py` | LLM-assisted market comparison and maturity assessment | Evidence gathering, diagram rendering |
| `arch_risk_analysis.py` | Risk identification and scoring for architecture reports | Evidence gathering, output formatting |
| `arch_recommendations.py` | Architecture improvement recommendations | Evidence gathering, output formatting |
| `arch_report_render.py` | Architecture report rendering (JSON, Markdown, PDF) | Integration discovery, risk analysis |
| `arch_test_coverage.py` | Test coverage analysis for architecture reports | Evidence gathering, rule evaluation |
| `collectors/cmake.py` | CMake build system evidence: `CMakeLists.txt` parsing, FetchContent detection, minimum version | Rule evaluation, C++ AST analysis |
| `collectors/cpp_ast.py` | C++ source evidence: header guard detection, raw memory patterns, exception handling patterns | Rule evaluation, build system analysis |

## Key Types

```
Evidence
  collector_name: str        # who produced it
  collector_version: str
  locator: str               # file path or identifier
  kind: str                  # e.g. "java-ast-file", "repo-structure-summary"
  payload: dict[str, Any]    # raw data — schema is per-collector

Finding
  rule_id, rag, severity, summary, recommendation,
  evidence_locator, collector_name, collector_version,
  confidence, pattern_tag

RuleResult
  rule_id: str
  findings: list[Finding]
  skipped: bool
  skip_reason: str | None

RunMetadata
  tool_version, target_repo, git_sha, git_branch, git_dirty,
  git_error, timestamp, collector_versions, rules_run, rules_skipped

RunResult
  findings: list[Finding]
  rule_results: list[RuleResult]
  run_metadata: RunMetadata
  warnings: list[str]

PytestResult (output/pytest_runner.py)
  passed, failed, skipped, errors: int
  duration_seconds: float
  warnings: list[str]
  raw_output: str
  exit_code: int               # -1 = pytest not found / timed out
```

## Engine Filtering Pipeline

Rules pass through four gates in order. Failing any gate skips the rule
(recorded in `RunMetadata.rules_skipped` with the reason).

1. **Config skip** -- `rule.id` in `config.rules.skip`
2. **Config include_only** -- `config.rules.include_only` is set and rule.id not in it
3. **Tech gate** -- `rule.required_tech` lists a tech key where `config.tech[key]` is false/missing
4. **Collector gate** -- `rule.required_collectors` lists a collector that failed or was skipped

After passing all gates, `rule.evaluate(evidence, config)` is called. Exceptions
are caught and recorded as skipped (R012: never abort mid-run).

## Registration Pattern

Collectors and rules self-register via import side-effects:

```python
# Bottom of every collector/rule file:
def _register() -> None:
    if "my-collector" not in collector_registry:
        collector_registry.register("my-collector", MyCollector())

_register()
```

`collectors/__init__.py` and `rules/__init__.py` import all plugin modules,
triggering registration. The CLI imports these packages at startup.

## Decision Guide

| You want to... | Put it in... | Also update... |
|-----------------|-------------|----------------|
| Add a new language/format collector | `collectors/<name>.py` with `_register()` | `collectors/__init__.py` (import), add test fixtures |
| Add a new NFR rule | `rules/<name>.py` with `_register()` | `rules/__init__.py` (import), test with positive + negative fixtures |
| Add a new tech detection | `detect.py` -- add key to `ALL_TECH_KEYS` + detector function | Config docs if users need to override it |
| Add a new config option | `config.py` Pydantic model | CLI if it needs a flag, docs |
| Add a new output format | `output/<format>.py` | `cli.py` (new flag + writer call) |
| Add a new report section | `output/markdown.py` (new `_section()` helper) | `output/pdf.py` if the section should appear in PDF output |
| Add a new PDF section | `output/pdf.py` (extend HTML assembly) | `output/summarize.py` if LLM input is needed |
| Add a new diagram type | `output/diagrams.py` (new helper) | `output/render.py` if new Mermaid syntax is needed |
| Add a new dependency ecosystem | `deps_analysis.py` (new resolver branch) | `dep_solver.py` if resolvelib model changes, `output/deps_report.py` for display |
| Change pre-collector path exclusion | `path_filter.py` (edit `_TEST_PATH_PATTERNS` or `should_exclude_path`) | Tests in `test_path_filter.py` |
| Change source/test classification | `output/classify.py` (add patterns to `_TEST_PATH_PATTERNS`) | Tests in `test_classify.py` |
| Add a Band 2 (LLM) rule | `rules/<name>.py` with `band = 2`, inject `ClaudeClient` | Tests must mock `nfr_review.llm_client.anthropic` |
| Change finding field order | `models.py` (reorder `Finding` fields) | `tests/test_output.py` R007 column-order assertion |
| Add a new hygiene collector | `hygiene/collectors/<name>.py` with `_register()` | `hygiene/collectors/__init__.py` (import), test fixtures |
| Add a new hygiene rule | `hygiene/rules/<prefix>_<name>.py` with `_register()` | `hygiene/rules/__init__.py` (import), category prefix convention: `lic_`, `com_`, `ci_`, `doc_`, `bld_`, `prv_` |
| Add an optional dependency | `pyproject.toml` `[project.optional-dependencies]`, try/except ImportError with fallback stubs | mypy `[[tool.mypy.overrides]]` for untyped package |
| Add architecture report feature | `arch_*.py` (models, discovery, integrations, diagrams, risk, recommendations) | `arch_orchestrator.py` for orchestration, `arch_report_render.py` for output |

## Collector Contract

A collector implements the `Collector` protocol:

```python
class MyCollector:
    name = "my-collector"        # unique, kebab-case
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        # Scan files under repo_path
        # Return Evidence records with kind="my-collector-*"
        # Return empty list if nothing relevant found
        # Never raise -- return empty + log warning if something fails
```

Conventions:
- Always emit a summary Evidence record (even for empty repos) so rules have a guaranteed record to inspect
- Use `kind` prefixed with collector name: `"helm-chart"`, `"java-ast-file"`
- Payload schema is collector-specific but must be stable -- rules depend on it
- Use `shutil.which()` for external binary dependencies; skip gracefully when absent
- Never evaluate findings -- that's rules' job

## Rule Contract

A rule implements the `Rule` protocol:

```python
class MyRule:
    id = "my-rule-name"                        # unique, kebab-case
    band: Band = 1                             # 1 = deterministic, 2 = LLM-augmented
    required_collectors: list[str] = ["my-collector"]
    required_tech: list[str] = ["relevant_tech"]  # omit for universal rules

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        relevant = [e for e in evidence if e.collector_name == "my-collector"]
        # Produce Finding objects with RAG + severity + evidence_locator
        # Return RuleResult(rule_id=self.id, findings=[...])
        # Return RuleResult(skipped=True, skip_reason="...") if not applicable
```

Conventions:
- Universal rules (ADR lifecycle, CI checks) omit `required_tech`
- Tech-specific rules (Spring, APIM) declare `required_tech`
- Filter evidence by `collector_name` -- don't scan all evidence
- Band 2 rules: inject `ClaudeClient`, check `self._llm.available` before calling
- Never do file I/O on the target repo -- consume evidence only

## Optional Dependency Pattern

Some collectors depend on heavy third-party packages (e.g., scancode-toolkit).
These use try/except ImportError with fallback stubs:

```python
_AVAILABLE = False
try:
    from heavy_lib import func  # type: ignore[import-untyped]
    _AVAILABLE = True
except ImportError:
    def func(**kwargs):  # type: ignore[misc]
        raise RuntimeError("heavy_lib not installed")
```

The collector checks `_AVAILABLE` and returns an empty evidence list when the
dependency is absent. Rules that depend on that collector's evidence gracefully
skip via the engine's collector gate. Install via extras: `pip install nfr-review[scancode]`.

## License Compliance Rules

The `license` category contains four hygiene rules:

| Rule | ID | Evidence | Behaviour |
|------|----|----------|-----------|
| Copyleft detection | HYG-LIC-001 | `license-scan` | Red for strong copyleft (GPL, AGPL), amber for weak (LGPL, MPL) |
| NOTICE completeness | HYG-LIC-002 | `license-scan` | Cross-references holders against NOTICE file; red if missing, amber if incomplete |
| License headers | HYG-LIC-003 | `license-scan` | Amber for source files missing copyright/license headers |
| SPDX validation | HYG-LIC-004 | none (reads metadata files) | Validates license expressions in pyproject.toml, package.json, pom.xml against SPDX identifiers |

HYG-LIC-004 is the only rule that does not require the `license-scan` collector —
it reads project metadata files directly and works without scancode installed.

## Fault Tolerance (R012)

The engine never aborts mid-run:
- Collector exception -> warning, skip collector, continue
- Rule exception -> RuleResult(skipped=True), continue
- All skip reasons appear in `RunMetadata.rules_skipped`
- Output errors raise `OutputError` (not raw OSError)

## Exit Code Matrix

| Code | Meaning |
|------|---------|
| 0 | Success -- all rules ran, no findings exceed threshold |
| 1 | Recoverable error -- missing target, ConfigError, EngineError, OutputError, unknown rule |
| 2 | Findings exceed `config.severity_threshold` |
