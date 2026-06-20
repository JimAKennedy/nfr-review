# Typed Rule Framework — Analysis & Phased Implementation Plan

Status: **proposal / ready to implement** · Owner: TBD · Created 2026-06-16

This document is the design and step-by-step plan for introducing a **typed,
embedded rule framework** to nfr-review. It reconciles and supersedes the
loosely-scoped tasks **#1 (rule boilerplate)** and **#8 (finish typed payloads)**
in [CLEANUP_TASKS.md](CLEANUP_TASKS.md): rather than two ad-hoc passes, a single
base-class design delivers both *less boilerplate* and *end-to-end typing* together.

It is explicitly designed to be **phased in**. Existing rules keep working
untouched; nothing is a flag day; you adopt the new approach for new rules first
and migrate old ones opportunistically (or never).

---

## 1. Background: how rules work today

A rule is any class satisfying the `Rule` protocol (`src/nfr_review/protocols.py:26`):

```python
class Rule(Protocol):
    id: str
    band: Band                       # 1 deterministic, 2 LLM, 3 quantitative
    required_collectors: list[str]
    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult: ...
```

The engine handles gating (skip/include-only/tech/collector) and fault tolerance;
the rule just consumes a flat `list[Evidence]` and returns a `RuleResult`.

### The uniform anatomy

Across 139 rule files, a Band-1 rule is almost always the same five moves:

1. **Select** evidence by `(collector_name, kind)`.
2. **Skip** if empty.
3. **Walk** a nested path in `ev.payload`.
4. **Predicate** on a field value.
5. **Emit** a `Finding`, plus a green "all-clear" finding if nothing matched.

The only things that vary: *which evidence kind*, *which path*, *which predicate*,
and the *outcome → (rag, severity, message)* mapping.

### Measured shape (justifies the design)

| Signal | Value |
|---|---|
| Rule files | 139 (119 registered rules; some files hold >1) |
| Files < 120 lines (simple field predicates) | ~78 |
| Files 120–250 lines (moderate) | ~52 |
| Files ≥ 250 lines (genuinely complex) | ~7 |
| Rules doing LLM orchestration | 4 |
| Rules using regex | 16 |
| **Rules reading `ev.payload` as a dict (`.get`/`[]`)** | **108** |
| **Rules narrowing to a typed payload (`isinstance`)** | **3** |

### Two structural problems this plan fixes

- **No typing at the rule↔payload boundary.** 54 typed `BasePayload` subclasses
  exist, but 108 rules go through the dict-compat shim (`models.py:15`). A typo in
  `default["default_type"]` or a collector schema change is invisible to mypy.
- **Severity has two sources of truth.** It is declared in `RULE_METADATA`
  (`rule_metadata.py`) *and* hardcoded inline in every `Finding`. They can drift by
  hand (verified: `python-mutable-default` repeats `medium` in both places).

### Why not an external DSL or Semgrep/CodeQL/Rego

Briefly, because the question comes up:

- An **external/custom DSL** (YAML/grammar) pushes field access into *strings*
  evaluated at runtime — mypy can't see into them, so it **removes** the typing we
  want. It also can't express the complex tail (LLM verdicts, p95 math, JDepend
  cycles, cross-evidence joins) without an "escape to Python" hatch, leaving two
  systems to maintain. Net: more machinery, *less* type safety.
- **Semgrep/CodeQL** query source/AST directly and have no model for nfr-review's
  non-code evidence (K8s manifests, OTel traces, deps, CI). **OPA/Rego** evaluates
  JSON but discards typing and adds a second runtime. None consume the `Evidence`
  abstraction that is the project's core seam.

The right "DSL" here is an **embedded, typed one**: declarative Python base classes
generic over the payload type. The closures receive concrete, mypy-checked objects,
so it advances *both* goals at once. `GenericASTRule` (`rules/ast_common.py:32`) is
already a working proof of this shape — we generalise it rather than invent anything.

---

## 2. Design

Three additions, all in a new module `src/nfr_review/rules/framework.py`. No
changes to the `Rule` protocol, the engine, the registry, or registration. A
framework rule *is* a normal `Rule` (it implements `evaluate`), so it registers and
runs identically to a hand-written one.

### 2.1 `Hit` — what a rule author yields

A `Hit` is the variable part of a finding. Everything else (rule_id, collector
name/version, default severity, pattern_tag, the green all-clear) is filled by the
base class.

```python
from dataclasses import dataclass
from nfr_review.models import RAG, Severity

@dataclass(frozen=True, slots=True)
class Hit:
    rag: RAG                          # "red" | "amber" | "green"
    summary: str
    recommendation: str
    locator: str                      # e.g. f"{payload.file_path}:{node.line}"
    severity: Severity | None = None  # default derived from rag (see precedence)
    confidence: float | None = None   # default from rule.default_confidence
    pattern_tag: str | None = None    # default from rule.pattern_tag
    content_hash: str = ""
```

### 2.2 `make_finding` — the single finding builder

A standalone helper so even **imperative** rules can drop their inline `Finding`
construction and severity hardcoding. Severity precedence is defined once here:

```python
_RAG_SEVERITY: dict[RAG, Severity] = {"red": "high", "amber": "medium", "green": "info"}

def make_finding(
    *, rule_id: str, hit: Hit, ev: Evidence,
    pattern_tag: str, default_confidence: float = 0.9,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rag=hit.rag,
        severity=hit.severity or _RAG_SEVERITY[hit.rag],
        summary=hit.summary,
        recommendation=hit.recommendation,
        evidence_locator=hit.locator,
        collector_name=ev.collector_name,
        collector_version=ev.collector_version,
        confidence=hit.confidence if hit.confidence is not None else default_confidence,
        pattern_tag=hit.pattern_tag or pattern_tag,
        content_hash=hit.content_hash,
    )
```

**Severity precedence:** `Hit.severity` (explicit override) → `_RAG_SEVERITY[rag]`
(default). Rules that need finer control (e.g. red-but-critical) set `Hit.severity`.
This removes inline severity from the common case; `RULE_METADATA.severity` remains
the catalogue/scoring **headline** for the rule. (A later, optional step can assert
in a test that metadata severity matches a rule's worst-case finding severity.)

### 2.3 `FieldRule[P]` — the declarative base (covers Band 1, most rules)

```python
from typing import Generic, TypeVar
from collections.abc import Iterable
from nfr_review.models import BasePayload, Evidence, RuleResult
from nfr_review.protocols import Band

P = TypeVar("P", bound=BasePayload)

class FieldRule(Generic[P]):
    """Declarative single-evidence-kind rule with typed payload access.

    Subclasses set ``id``, ``payload_type``, ``collector_name``,
    ``evidence_kind``, ``pattern_tag``, and implement ``check()``.
    The base handles selection, skip-if-empty, payload coercion (typed),
    the green all-clear finding, and Finding construction.
    """

    id: str
    band: Band = 1
    collector_name: str
    evidence_kind: str
    payload_type: type[P]
    pattern_tag: str
    required_tech: list[str] = []
    default_confidence: float = 0.9
    all_clear_summary: str = "No issues detected."
    all_clear_recommendation: str = "No action required."

    # populated by __init_subclass__ so the engine's collector gate works
    required_collectors: list[str] = []

    def __init_subclass__(cls, **kw: object) -> None:
        super().__init_subclass__(**kw)
        if not cls.__dict__.get("required_collectors") and hasattr(cls, "collector_name"):
            cls.required_collectors = [cls.collector_name]

    def check(self, payload: P, ev: Evidence) -> Iterable[Hit]:
        """Return Hits for one typed payload. Yield nothing when clean."""
        raise NotImplementedError

    def _coerce(self, raw: object) -> P:
        if isinstance(raw, self.payload_type):
            return raw
        if isinstance(raw, BasePayload):              # different typed payload
            return self.payload_type.model_validate(raw.model_dump())
        return self.payload_type.model_validate(raw)  # dict (today's common case)

    def evaluate(self, evidence: list[Evidence], context: object) -> RuleResult:
        relevant = [
            e for e in evidence
            if e.collector_name == self.collector_name and e.kind == self.evidence_kind
        ]
        if not relevant:
            return RuleResult(
                rule_id=self.id, skipped=True,
                skip_reason=f"no {self.evidence_kind} evidence available",
            )
        findings: list[Finding] = []
        for ev in relevant:
            payload = self._coerce(ev.payload)
            for hit in self.check(payload, ev):
                findings.append(make_finding(
                    rule_id=self.id, hit=hit, ev=ev,
                    pattern_tag=self.pattern_tag,
                    default_confidence=self.default_confidence,
                ))
        if not findings:
            findings.append(make_finding(
                rule_id=self.id, ev=relevant[0], pattern_tag=self.pattern_tag,
                hit=Hit(rag="green", summary=self.all_clear_summary,
                        recommendation=self.all_clear_recommendation,
                        locator="project-wide", confidence=0.9),
            ))
        return RuleResult(rule_id=self.id, findings=findings)
```

#### The key phasing enabler: coercion bridges the collector migration

`_coerce()` accepts **either** a typed payload **or** today's raw dict and returns a
typed object. This means a rule can be typed **immediately**, *before* its collector
is migrated to emit typed payloads. The rule-side typing migration is therefore
**decoupled** from the collector-side one — you don't have to do both at once.

Trade-off: coercing a dict runs Pydantic validation per evidence record. The
`isinstance` fast-path skips it once collectors emit typed payloads. If validation
ever shows up in a profile on huge repos, see Risks (§7).

If a payload fails validation (schema drift), `model_validate` raises; the engine
catches it (R012) and records the rule as skipped with the reason — drift surfaces
as an auditable skip rather than a silent wrong answer.

### 2.4 Out of scope for `FieldRule` (kept imperative, or future bases)

- **Cross-evidence joins** (e.g. `dockerfile-k8s-image-drift` joins two collectors).
  Keep imperative for now; a `MultiEvidenceRule` base can come later if a pattern emerges.
- **Band 2 (LLM)** — a future `RegexPrefilterLlmRule` base could declare patterns +
  prompt + verdict→rag map (`pii_logging` → ~30 lines). **Build only if ≥3 rules fit.**
- **Band 3 (quantitative)** — a future `MetricThresholdRule` base could declare an
  aggregator + target key + band thresholds (`dyn_latency_p95`). Same gate: ≥3 rules.
- **`GenericASTRule`** already covers cross-language AST rules. Re-express its
  green/finding logic on top of `make_finding` so the builder is shared (Phase 2).

These keep implementing `evaluate()` directly — the documented, permanent escape hatch.

---

## 3. Phased rollout

Each phase is independently shippable and leaves the suite green. **No phase
requires touching rules from a previous phase.**

### Phase 0 — Land the framework (no rule changes)
- Add `src/nfr_review/rules/framework.py` with `Hit`, `make_finding`, `FieldRule`.
- Unit-test the base directly: selection, skip-if-empty, all-clear, severity
  precedence, dict-coercion, typed-payload fast-path, validation-failure path.
- Export from `rules/__init__` as needed; no existing rule is modified.
- **Acceptance:** new module at 100% coverage; full suite unchanged & green.

### Phase 1 — Author all *new* rules with the framework + update docs
- From here, new Band-1 rules subclass `FieldRule` (see §5 guide).
- **Update project documentation** (this is a Phase-1 deliverable, see §6).
- Convert **2–3 simple existing rules** (e.g. `python-mutable-default`) as worked
  references — picked because they have existing positive/negative fixtures to prove
  byte-identical findings.
- **Acceptance:** ≥1 reference rule migrated with identical findings (snapshot/diff);
  docs updated; CONTRIBUTING/ARCHITECTURE point authors at the new base.

### Phase 2 — Opportunistic migration (no big bang)
- Migrate a rule **only** when you touch it for another reason, or migrate **one
  category at a time** (e.g. all `python_*`, then `go_*`) in small PRs.
- Re-express `GenericASTRule`'s finding construction on `make_finding`.
- Each migration must show **before/after findings are identical** for that rule's
  fixtures (the R007 column-order test and per-rule fixtures are the safety net).
- **Acceptance:** migrated rules unchanged in output; net line reduction tracked.

### Phase 3 — Optional Band 2/3 bases (gated)
- Only if the ≥3-rules-fit bar is met. Otherwise leave Band 2/3 imperative.
- **Acceptance:** PII / dyn-* rules reduced with identical output, or explicitly
  deferred with a note here.

### Phase 4 — Tighten typing enforcement (after enough adoption)
- Once most rules are typed, raise mypy strictness for `src/nfr_review/rules/`
  (e.g. `disallow_any_expr` scoped via per-module override) so new dict access is a
  CI failure, not a style nit.
- Consider deprecating the `BasePayload` dict shim (`models.py`) once no rule relies
  on it (CLEANUP_TASKS #8 endgame).
- **Acceptance:** rules dir passes stricter mypy; shim removal scheduled or done.

**You can stop after any phase.** Phase 1 alone delivers the new authoring path and
the docs; Phases 2–4 are pure cleanup that can proceed indefinitely in the background.

---

## 4. Coexistence & backward compatibility

- **Protocol unchanged.** `FieldRule` implements `evaluate`, so it satisfies `Rule`.
- **Registration unchanged.** Same `_register()` side-effect at file bottom.
- **Engine unchanged.** It never sees the difference; gating still works because
  `required_collectors` is auto-populated in `__init_subclass__`.
- **Mixed registry is fine.** Framework rules and imperative rules run side by side
  forever. There is no migration deadline.
- **Output stability.** `make_finding` produces the same `Finding` field order
  (R007). Per-rule fixtures + the column-order test guard against regressions.

---

## 5. Authoring guide — writing a rule the new way

> This section is the seed for the documentation update in §6. Keep it in sync.

### Step 1 — Identify the evidence and payload type
Find the collector you depend on and its typed payload in
`collectors/payloads/`. For Python AST: collector `python-ast`, kind
`python-ast-file`, payload `PythonAstFilePayload`.

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
__all__ = ["PythonMutableDefaultRule"]
```

Compare to the [original 90-line imperative version] — the boilerplate (selection,
skip, green finding, Finding plumbing, inline severity) is gone, and field access is
**statically typed**.

### Step 3 — What you do *not* write
- No evidence-selection list comprehension (base does it from `collector_name`/`evidence_kind`).
- No skip-if-empty branch.
- No green/all-clear `Finding`.
- No `collector_name`/`collector_version`/`severity` plumbing on each finding
  (severity defaults from `rag`; override per `Hit` only when needed).

### Step 4 — Add metadata & tests (unchanged from today)
- Add a `RULE_METADATA["your-rule-id"]` entry (severity/category/tags/description/refs).
- Add positive **and** negative fixtures; assert findings as before.

### When to *not* use `FieldRule`
Use a plain `evaluate()` class (today's style) when the rule:
- joins **multiple** collectors/evidence kinds,
- needs LLM orchestration (until/unless a Band-2 base exists), or
- does cross-record aggregation (until/unless a Band-3 base exists).
Even then, use `make_finding`/`Hit` to avoid inline `Finding` boilerplate.

---

## 6. Documentation updates required (Phase 1 deliverable)

The new approach **must** be reflected in the project docs, or authors will keep
copying the old pattern. Treat these as part of Phase 1, not optional follow-up:

1. **`ARCHITECTURE.md`**
   - **Rule Contract** section: add the `FieldRule[P]` pattern as the *default* way
     to write a Band-1 rule; present the raw `evaluate()` protocol as the escape hatch.
   - **Decision Guide** table: change the *"Add a new NFR rule"* row to point at
     `FieldRule`; add a row *"Add a typed evidence payload"* cross-referencing
     `_coerce`'s expectations.
   - Add a short subsection describing `Hit` / `make_finding` / severity precedence.
2. **`README.md`** — in the **Rules** section, mention rules are typed against
   collector payloads and link to this plan and the authoring guide (§5).
3. **`CONTRIBUTING.md`** — update the "adding a rule" instructions to the new flow;
   note the mypy expectation for typed payload access.
4. **`CLEANUP_TASKS.md`** — mark **#1** and **#8** as *superseded by this plan* and
   link here, so the backlog has one source of truth.
5. **Module docstring** in `rules/framework.py` — concise version of §5 so it's
   discoverable from the code.
6. **This file** — keep §5 and §2 in sync as the framework evolves; it is the
   canonical design reference.

A migration PR that adds/changes the framework **without** these doc edits should be
considered incomplete.

---

## 7. Testing & risks

### Testing
- **Framework unit tests** (Phase 0): selection, skip, all-clear, severity
  precedence, dict-coercion vs typed fast-path, validation-failure → engine skip.
- **Per-rule equivalence**: every migrated rule must produce byte-identical findings
  on its existing fixtures (diff old vs new). The R007 column-order test
  (`tests/test_output.py`) guards field order globally.
- **mypy**: framework module fully typed; rules dir strictness raised in Phase 4.
- Run `python -m pytest -n auto tests/` and `ruff check`/`ruff format` per change.

### Risks & mitigations
| Risk | Mitigation |
|---|---|
| Pydantic validation cost when coercing dicts on large repos | `isinstance` fast-path once collectors emit typed payloads (Phase 2+); profile before optimizing; validation is per-evidence, not per-node |
| Over-abstraction of Band 2/3 | Gate new bases on "≥3 rules fit"; otherwise stay imperative |
| Severity drift between `RULE_METADATA` and findings | `make_finding` derives severity from `rag`; optional Phase-4 test asserts metadata headline ≥ worst finding severity |
| Authors keep copying the old pattern | Phase-1 doc updates (§6) + reference migrations make the new path the path of least resistance |
| Payload schema mismatch hidden behind dict shim | Coercion turns drift into an explicit, auditable rule-skip reason |

---

## 8. Summary

- **Don't** build an external DSL or adopt Semgrep/CodeQL/Rego — they fight the
  Evidence-centric architecture and *remove* type safety.
- **Do** add a typed, embedded framework (`Hit` + `make_finding` + `FieldRule[P]`),
  which is the unification of CLEANUP_TASKS #1 and #8.
- It is **fully phaseable**: ship the base (Phase 0), author new rules + docs with it
  (Phase 1), migrate old rules opportunistically (Phase 2), add Band 2/3 bases only
  if justified (Phase 3), and tighten typing enforcement last (Phase 4).
- Expected payoff: ~1,000–1,400 fewer lines, static typing at the rule↔payload
  boundary, one source of truth for severity — with **no flag day** and **no
  requirement to remediate existing rules immediately**.
