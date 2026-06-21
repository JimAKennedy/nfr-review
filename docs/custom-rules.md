<!-- Copyright 2026 nfr-review contributors — Licensed under Apache-2.0 -->

# Creating Custom Rules

This guide walks through creating, registering, and running a custom nfr-review
rule from scratch. By the end you will have a working rule that evaluates
evidence, emits findings, and appears in `nfr-review list-rules`.

---

## Table of contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [FieldRule — the recommended approach](#fieldrule--the-recommended-approach)
4. [Imperative rules — the escape hatch](#imperative-rules--the-escape-hatch)
5. [Registration, metadata, scoring, tests, and running](#step-3--register-the-rule)
6. [Complete example (FieldRule)](#complete-example-fieldrule)
7. [Complete example (imperative)](#complete-example-imperative)
8. [External rule packs (plugin API)](#external-rule-packs-plugin-api)
9. [Reference](#reference)

---

## 1. Overview

nfr-review uses a three-stage pipeline:

```
Collectors  →  Rules  →  Output
(gather evidence)  (evaluate patterns)  (CSV, JSONL, SARIF, PDF)
```

A **rule** receives evidence from one or more collectors and emits zero or more
**findings** — each with a RAG status (red/amber/green), severity, and
recommendation. Rules never do file I/O on the target repo; they only consume
evidence objects.

Rules are organized into two registries:

| Registry | Rule ID convention | Command |
|----------|--------------------|---------|
| **NFR rules** | lowercase-kebab-case (e.g. `ci-test-stage-missing`) or PATCH-PREFIX | `nfr-review run` |
| **Hygiene rules** | `HYG-XXX-NNN` prefix (e.g. `HYG-DOC-001`) | `nfr-review hygiene` |

This guide covers NFR rules. Hygiene rules follow the same pattern but register
into `hygiene_rule_registry` from `nfr_review.hygiene`.

---

## 2. Prerequisites

```bash
git clone https://github.com/JimAKennedy/nfr-review.git
cd nfr-review
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## FieldRule — the recommended approach

For most Band-1 rules (deterministic, single-collector), subclass
`FieldRule[P]` from `nfr_review.rules.framework`. It handles evidence
selection, skip-if-empty, payload coercion, the green all-clear finding, and
`Finding` construction — you write only the detection logic.

See [docs/rule-framework.md](rule-framework.md) for the full design rationale.

### Step 1 — Identify the evidence and payload type

Find the collector you depend on and its typed payload in
`src/nfr_review/collectors/payloads/`. For example, for Python AST rules:
collector `python-ast`, evidence kind `python-ast-file`, payload
`PythonAstFilePayload`.

### Step 2 — Subclass `FieldRule[YourPayload]`

```python
# src/nfr_review/rules/python_mutable_default.py
from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.python_ast import PythonAstFilePayload
from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.framework import FieldRule, Hit

_MUTABLE = frozenset({"list", "dict", "set"})


class PythonMutableDefaultRule(FieldRule[PythonAstFilePayload]):
    id = "python-mutable-default"
    collector_name = "python-ast"
    evidence_kind = "python-ast-file"
    payload_type = PythonAstFilePayload
    pattern_tag = "mutable-default"
    all_clear_summary = "No mutable default arguments detected."

    def check(self, p: PythonAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for func in p.functions:                 # typed — mypy knows .functions
            for d in func.default_args:           # typed — .default_type, .line
                if d.default_type in _MUTABLE:
                    yield Hit(
                        rag="amber",
                        summary=f"Mutable default argument ({d.default_type}) in {func.name}()",
                        recommendation=(
                            "Use None as default and initialize in the body:"
                            " if arg is None: arg = []"
                        ),
                        locator=f"{p.file_path}:{d.line}",
                    )


def _register() -> None:
    if "python-mutable-default" not in rule_registry:
        rule_registry.register("python-mutable-default", PythonMutableDefaultRule())


_register()
```

### What you do *not* write

- No evidence-selection list comprehension (base handles it from
  `collector_name` / `evidence_kind`).
- No skip-if-empty branch.
- No green/all-clear `Finding`.
- No `collector_name` / `collector_version` / `severity` plumbing on each
  finding (severity defaults from `rag`; override per `Hit` only when needed).

### FieldRule class attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` | Unique rule identifier (lowercase-kebab-case) |
| `collector_name` | `str` | The collector to consume evidence from |
| `evidence_kind` | `str` | Filter evidence to this kind |
| `payload_type` | `type[P]` | The typed payload class for coercion |
| `pattern_tag` | `str` | Default pattern tag for findings |
| `band` | `Band` | Default `1` (deterministic) |
| `required_tech` | `list[str]` | Technology gates (optional, default `[]`) |
| `default_confidence` | `float` | Default confidence (default `0.9`) |
| `all_clear_summary` | `str` | Summary for the green finding when no issues detected |
| `all_clear_recommendation` | `str` | Recommendation for the green finding |

`required_collectors` is set automatically from `collector_name` — you do not
need to declare it.

### The `Hit` dataclass

`Hit` is what you yield from `check()`. The framework fills everything else.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `rag` | `RAG` | — | `"red"` / `"amber"` / `"green"` |
| `summary` | `str` | — | What was found |
| `recommendation` | `str` | — | Remediation guidance |
| `locator` | `str` | — | File path or resource (e.g. `f"{p.file_path}:{line}"`) |
| `severity` | `Severity \| None` | `None` | Override; defaults to `red→high`, `amber→medium`, `green→info` |
| `confidence` | `float \| None` | `None` | Override; defaults to `default_confidence` |
| `pattern_tag` | `str \| None` | `None` | Override; defaults to rule's `pattern_tag` |
| `content_hash` | `str` | `""` | For stable baseline diffing |

### `make_finding` — standalone builder

Even imperative rules can use `make_finding` to avoid inline `Finding`
construction and severity hardcoding:

```python
from nfr_review.rules.framework import Hit, make_finding

finding = make_finding(
    rule_id=self.id,
    hit=Hit(rag="amber", summary="...", recommendation="...", locator="..."),
    ev=evidence_obj,
    pattern_tag="my-pattern",
)
```

**Severity precedence:** `Hit.severity` (explicit) → `_RAG_SEVERITY[rag]`
(`red→high`, `amber→medium`, `green→info`).

### When *not* to use `FieldRule`

Use a plain `evaluate()` class when the rule:

- Joins **multiple** collectors or evidence kinds
- Needs LLM orchestration (Band 2)
- Does cross-record aggregation (Band 3)
- Needs custom skip logic beyond "no evidence of this kind"

Even in these cases, use `make_finding` / `Hit` to avoid inline `Finding`
boilerplate.

---

## Imperative rules — the escape hatch

For rules that don't fit `FieldRule` (multi-collector joins, LLM calls,
aggregation), implement `evaluate()` directly. This is the original rule
pattern and remains a first-class, permanent API.

### Step 1 — Choose a collector dependency

Every rule declares which collectors it needs via `required_collectors`. The
engine skips rules whose collectors did not run.

Run `nfr-review list-rules --format json | python -c "import json,sys; print('\n'.join(sorted(set(c for r in json.load(sys.stdin) for c in r.get('required_collectors',[])))))"` to see all collector names, or use this reference:

| Collector | Evidence kind(s) | What it provides |
|-----------|-----------------|------------------|
| `repo-structure` | `repo-structure-summary` | README presence, file tree, tech markers |
| `ci-artifact` | `ci-pipeline` | CI workflow definitions, stages, actions |
| `k8s-manifest` | `k8s-resource` | Kubernetes deployments, services, pods |
| `dockerfile` | `dockerfile-instruction` | Dockerfile instructions, base images |
| `java-ast` | `ast-class`, `ast-method` | Java AST nodes (classes, methods, annotations) |
| `python-ast` | `ast-class`, `ast-method` | Python AST nodes |
| `go-ast` | `ast-class`, `ast-method` | Go AST nodes |
| `cpp-ast` | `ast-class`, `ast-method` | C++ AST nodes |
| `helm` | `helm-chart`, `helm-values` | Helm chart metadata and values |
| `terraform` | `terraform-resource` | Terraform resources and providers |
| `spring-config` | `spring-property` | Spring Boot configuration properties |
| `adr` | `adr-record` | Architecture Decision Records |
| `otel` | `otel-config` | OpenTelemetry configuration |
| `proto` | `proto-service` | gRPC/Protobuf service definitions |

For a complete list, run `nfr-review run --help` or inspect
`src/nfr_review/collectors/`.

---

## Step 2 — Create the rule module

Create a new file in `src/nfr_review/rules/`. The filename should match your
rule's concern (e.g. `ci_coverage_gate.py`).

A rule is any class with these attributes and one method:

```python
from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class CiCoverageGateRule:
    """Flag CI pipelines that have no coverage enforcement step."""

    id = "ci-coverage-gate-missing"
    band: Band = 1
    required_collectors: list[str] = ["ci-artifact"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ci_evidence = filter_evidence(evidence, "ci-artifact", kind="ci-pipeline")

        if not ci_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no ci-artifact evidence available",
            )

        findings: list[Finding] = []

        for ev in ci_evidence:
            steps = ev.payload.get("steps", [])
            has_coverage = any(
                "coverage" in str(step).lower() or "codecov" in str(step).lower()
                for step in steps
            )

            if has_coverage:
                findings.append(
                    make_green_finding(
                        self.id,
                        "ci-coverage-gate",
                        ev,
                        summary=f"Coverage gate found in {ev.locator}",
                        evidence_locator=ev.locator,
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=f"No coverage gate found in CI pipeline: {ev.locator}",
                        recommendation=(
                            "Add a coverage enforcement step (e.g. codecov, "
                            "coverage threshold check) to fail builds when "
                            "coverage drops."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="ci-coverage-gate",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)
```

### Key points

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` | Unique, stable rule identifier. Use lowercase-kebab-case. |
| `band` | `Band` (Literal[1, 2, 3]) | 1 = deterministic, 2 = LLM-augmented, 3 = dynamic analysis |
| `required_collectors` | `list[str]` | Collectors that must run for this rule to execute |
| `required_tech` | `list[str]` | *(Optional)* Technology gates — rule is skipped unless these techs are detected |

### Helper functions

Import from `nfr_review.rules.rule_helpers`:

- **`filter_evidence(evidence, collector_name, kind=None)`** — filter the
  evidence list by collector name and optionally by `kind`.
- **`make_green_finding(rule_id, pattern_tag, evidence_ref, ...)`** — build a
  green/info Finding with standard defaults. Pulls `collector_name` and
  `collector_version` from the evidence object automatically.

### The Finding model

Every finding must include these 10 fields:

| Field | Type | Description |
|-------|------|-------------|
| `rule_id` | `str` | Must match `self.id` |
| `rag` | `"red"` / `"amber"` / `"green"` | Red = immediate action, amber = attention needed, green = good practice |
| `severity` | `"critical"` / `"high"` / `"medium"` / `"low"` / `"info"` | Impact level |
| `summary` | `str` | Human-readable description of what was found |
| `recommendation` | `str` | Specific remediation guidance |
| `evidence_locator` | `str` | File path or resource that triggered the finding |
| `collector_name` | `str` | Which collector produced the evidence |
| `collector_version` | `str` | Collector version string |
| `confidence` | `float` | 0.0 to 1.0 — how confident the detection is |
| `pattern_tag` | `str` | Classification tag (used for baseline diffing and grouping) |

### Returning results

- **Findings found:** `RuleResult(rule_id=self.id, findings=[...])`
- **No evidence available:** `RuleResult(rule_id=self.id, skipped=True, skip_reason="...")`
- **All clear (green):** Include a green finding so the report shows the rule ran

---

## Step 3 — Register the rule

Add a `_register()` function at the bottom of your module. This is called
automatically when the module is imported:

```python
def _register() -> None:
    if "ci-coverage-gate-missing" not in rule_registry:
        rule_registry.register("ci-coverage-gate-missing", CiCoverageGateRule())


_register()
```

**That's it.** The `__init__.py` in `src/nfr_review/rules/` uses
`pkgutil.iter_modules()` to auto-import every `.py` file in the directory, which
triggers `_register()`. No manual import list to maintain.

### Files excluded from auto-import

These module names are excluded from auto-discovery (they are shared utilities,
not rules):

- `__init__`
- `ast_common`
- `rule_helpers`
- `_cross_language`

If your module name starts with `_`, it will still be auto-imported unless you
add it to the exclude list in `src/nfr_review/rules/__init__.py`.

---

## Step 4 — Add rule metadata

Rule metadata powers `nfr-review list-rules`, `nfr-review explain <rule-id>`,
and the GitHub Pages rule catalogue. Add an entry to the `RULE_METADATA` dict in
`src/nfr_review/rule_metadata.py`:

```python
"ci-coverage-gate-missing": _m(
    "medium",                                              # severity
    "maintainability",                                     # ISO 25010 category
    "Flags CI pipelines without a coverage enforcement "   # description
    "step such as codecov or a threshold check.",
    ["ci", "coverage", "quality-gate"],                    # tags
    ["ISO 25010:Maintainability"],                         # compliance_refs
),
```

The `_m()` helper builds a `RuleMetadata` instance. Parameters:

| Position | Field | Values |
|----------|-------|--------|
| 1 | `severity` | `"critical"`, `"high"`, `"medium"`, `"low"`, `"info"` |
| 2 | `category` | ISO 25010: `"security"`, `"reliability"`, `"performance"`, `"maintainability"` |
| 3 | `description` | One-paragraph explanation of what the rule checks |
| 4 | `tags` | List of searchable tags |
| 5 | `compliance_refs` | Compliance framework references (e.g. `"SOC2:CC8.1"`) |

---

## Step 5 — Add scoring integration

For your rule's findings to appear in the design maturity score, verify that the
rule ID maps to a scoring category. The engine uses keyword matching in
`src/nfr_review/scoring.py` (`_CATEGORY_KEYWORDS` dict).

Most rule IDs are matched automatically by prefix (e.g. `ci-` maps to `"ops"`,
which aliases to `"maintainability"`). If your rule ID uses an unusual prefix,
add a keyword entry:

```python
# In _CATEGORY_KEYWORDS:
"coverage-gate": "ops",
```

The display categories and their weights are defined in
`src/nfr_review/config.py` (`DEFAULT_CATEGORY_WEIGHTS`):

| Category | Aliases | Weight |
|----------|---------|--------|
| `security` | — | 1.0 |
| `reliability` | `observability`, `obs` | 1.0 |
| `performance` | — | 1.0 |
| `maintainability` | `ops` | 1.0 |
| `OTEL` | — | 1.0 |

If your rule introduces a **new category**, also add a description in
`src/nfr_review/output/markdown.py` (`_methodology_appendix` function) so the
report explains what the category covers.

---

## Step 6 — Write tests

Create a test file in `tests/` (e.g. `tests/test_ci_coverage_gate.py`):

```python
from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.rules.ci_coverage_gate import CiCoverageGateRule


def _make_ci_evidence(steps: list[dict]) -> list[Evidence]:
    return [
        Evidence(
            collector_name="ci-artifact",
            collector_version="1.0.0",
            locator=".github/workflows/ci.yml",
            kind="ci-pipeline",
            payload={"steps": steps},
        )
    ]


class TestCiCoverageGateRule:
    def test_green_when_coverage_present(self):
        evidence = _make_ci_evidence([{"name": "Upload coverage", "uses": "codecov/codecov-action@v4"}])
        result = CiCoverageGateRule().evaluate(evidence, context=None)

        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_amber_when_no_coverage(self):
        evidence = _make_ci_evidence([{"name": "Run tests", "run": "pytest"}])
        result = CiCoverageGateRule().evaluate(evidence, context=None)

        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"

    def test_skipped_when_no_evidence(self):
        result = CiCoverageGateRule().evaluate([], context=None)

        assert result.skipped
        assert "no ci-artifact evidence" in result.skip_reason
```

Run with:

```bash
pytest tests/test_ci_coverage_gate.py -v
```

---

## Step 7 — Run it

Your rule is now active. Run nfr-review against any target:

```bash
# Scan a repo — your rule will run automatically
nfr-review run /path/to/target/repo

# Verify it appears in the rule list
nfr-review list-rules | grep ci-coverage-gate

# Get detailed info
nfr-review explain ci-coverage-gate-missing

# Run with verbose output to see rule execution
nfr-review run /path/to/target/repo -v
```

### Skipping your rule

Users can skip any rule via config:

```yaml
# nfr-review.yaml
rules:
  skip:
    - ci-coverage-gate-missing
```

---

## Complete example (FieldRule)

Here is a minimal but complete FieldRule. Copy this as a starting template:

```python
# src/nfr_review/rules/python_mutable_default.py
# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: flag mutable default arguments in Python functions."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.python_ast import PythonAstFilePayload
from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.framework import FieldRule, Hit

_MUTABLE = frozenset({"list", "dict", "set"})


class PythonMutableDefaultRule(FieldRule[PythonAstFilePayload]):
    id = "python-mutable-default"
    collector_name = "python-ast"
    evidence_kind = "python-ast-file"
    payload_type = PythonAstFilePayload
    pattern_tag = "mutable-default"
    all_clear_summary = "No mutable default arguments detected."

    def check(self, p: PythonAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for func in p.functions:
            for d in func.default_args:
                if d.default_type in _MUTABLE:
                    yield Hit(
                        rag="amber",
                        summary=f"Mutable default argument ({d.default_type}) in {func.name}()",
                        recommendation=(
                            "Use None as default and initialize in the body:"
                            " if arg is None: arg = []"
                        ),
                        locator=f"{p.file_path}:{d.line}",
                    )


def _register() -> None:
    if "python-mutable-default" not in rule_registry:
        rule_registry.register("python-mutable-default", PythonMutableDefaultRule())


_register()
```

### FieldRule checklist

- [ ] Rule module in `src/nfr_review/rules/`
- [ ] Subclass `FieldRule[YourPayload]` with `id`, `collector_name`, `evidence_kind`, `payload_type`, `pattern_tag`
- [ ] `check()` yields `Hit` objects
- [ ] `_register()` function at module scope
- [ ] Entry in `RULE_METADATA` (`src/nfr_review/rule_metadata.py`)
- [ ] Scoring keyword if prefix is non-standard (`src/nfr_review/scoring.py`)
- [ ] Tests with positive and negative cases
- [ ] Verify with `nfr-review list-rules` and `nfr-review explain`

---

## Complete example (imperative)

Here is a minimal but complete imperative rule file for cases that don't fit
`FieldRule` (multi-collector, LLM, aggregation):

```python
# src/nfr_review/rules/ci_coverage_gate.py
# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: flag CI pipelines without coverage enforcement."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class CiCoverageGateRule:
    """Flag CI pipelines that have no coverage enforcement step."""

    id = "ci-coverage-gate-missing"
    band: Band = 1
    required_collectors: list[str] = ["ci-artifact"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ci_evidence = filter_evidence(evidence, "ci-artifact", kind="ci-pipeline")

        if not ci_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no ci-artifact evidence available",
            )

        findings: list[Finding] = []
        for ev in ci_evidence:
            steps = ev.payload.get("steps", [])
            has_coverage = any(
                "coverage" in str(s).lower() or "codecov" in str(s).lower()
                for s in steps
            )

            if has_coverage:
                findings.append(
                    make_green_finding(
                        self.id,
                        "ci-coverage-gate",
                        ev,
                        summary=f"Coverage gate found in {ev.locator}",
                        evidence_locator=ev.locator,
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=f"No coverage gate in CI pipeline: {ev.locator}",
                        recommendation=(
                            "Add a coverage enforcement step to fail builds "
                            "when coverage drops below threshold."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="ci-coverage-gate",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "ci-coverage-gate-missing" not in rule_registry:
        rule_registry.register("ci-coverage-gate-missing", CiCoverageGateRule())


_register()
```

### Imperative checklist

- [ ] Rule module in `src/nfr_review/rules/`
- [ ] Class with `id`, `band`, `required_collectors`, `evaluate()`
- [ ] `_register()` function at module scope
- [ ] Entry in `RULE_METADATA` (`src/nfr_review/rule_metadata.py`)
- [ ] Scoring keyword if prefix is non-standard (`src/nfr_review/scoring.py`)
- [ ] Tests with positive and negative cases
- [ ] Verify with `nfr-review list-rules` and `nfr-review explain`

---

## External rule packs (plugin API)

If you want to distribute rules as a separate pip-installable package (without
forking nfr-review), use the entry-point plugin API.

### 1. Write your rules

Follow the same pattern above, but in your own package:

```python
# my_org_rules/internal_api_check.py
from nfr_review.registry import rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band


class InternalApiVersionRule:
    id = "MYORG-api-version-header"
    band: Band = 1
    required_collectors = ["repo-structure"]

    def evaluate(self, evidence, context):
        # ... your logic ...
        return RuleResult(rule_id=self.id, findings=[])


def _register():
    if "MYORG-api-version-header" not in rule_registry:
        rule_registry.register("MYORG-api-version-header", InternalApiVersionRule())


_register()
```

### 2. Declare the entry point

In your package's `pyproject.toml`:

```toml
[project]
name = "nfr-review-myorg-rules"
version = "0.1.0"
dependencies = ["nfr-review"]

[project.entry-points."nfr_review.rules"]
myorg_rules = "my_org_rules.internal_api_check"
```

For hygiene rules, use the `nfr_review.hygiene_rules` group and register into
`hygiene_rule_registry` from `nfr_review.hygiene`.

### 3. Install alongside nfr-review

```bash
pip install nfr-review-myorg-rules
```

Your rules are discovered and loaded automatically on the next run.

### Conflict handling

Built-in rules load first. If an external rule uses an ID that already exists,
the registration is skipped and a warning is logged. Use a unique prefix for
your rule IDs (e.g. `MYORG-`) to avoid conflicts.

---

## Reference

### Rule protocol

```python
class Rule(Protocol):
    id: str
    band: Band                        # Literal[1, 2, 3]
    required_collectors: list[str]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult: ...
```

### Evidence model

```python
class Evidence(BaseModel):
    collector_name: str
    collector_version: str
    locator: str          # file path or resource identifier
    kind: str             # evidence type (e.g. "ci-pipeline", "ast-method")
    payload: Any          # typed payload or dict
```

### Finding model

```python
class Finding(BaseModel):
    rule_id: str
    rag: Literal["red", "amber", "green", "skipped"]
    severity: Literal["critical", "high", "medium", "low", "info"]
    summary: str
    recommendation: str
    evidence_locator: str
    collector_name: str
    collector_version: str
    confidence: float     # 0.0 to 1.0
    pattern_tag: str
    content_hash: str     # optional, for stable baseline diffing
```

### RuleResult model

```python
class RuleResult(BaseModel):
    rule_id: str
    findings: list[Finding]
    skipped: bool = False
    skip_reason: str | None = None
```

### Band levels

| Band | Type | Description |
|------|------|-------------|
| 1 | Deterministic | Pattern matching, config checks, AST analysis — no external calls |
| 2 | LLM-augmented | Uses optional LLM backend; falls back gracefully when unavailable |
| 3 | Dynamic | Analyses runtime traces (OTel); only runs when trace data is provided |

### Severity guidelines

| Severity | When to use |
|----------|-------------|
| `critical` | Security vulnerability, data loss risk, production outage potential |
| `high` | Significant operational risk, missing essential safeguards |
| `medium` | Best practice violation, moderate risk |
| `low` | Minor improvement opportunity, style concern |
| `info` | Informational observation, no action needed |

### RAG guidelines

| RAG | When to use |
|-----|-------------|
| `red` | Clear violation requiring immediate remediation |
| `amber` | Concern worth investigating, may need action |
| `green` | Good practice detected, no issues found |

### Further reading

- [docs/rule-framework.md](rule-framework.md) — typed rule framework design and phased rollout plan
- [ARCHITECTURE.md](../ARCHITECTURE.md) — module responsibility map and data flow
- [CONTRIBUTING.md](../CONTRIBUTING.md) — development setup and PR expectations
- [docs/install.md](install.md) — full install guide
- [docs/continuous-compliance.md](continuous-compliance.md) — compliance framework mappings
