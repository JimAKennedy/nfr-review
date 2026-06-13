# Cleanup & Refactoring Tasks

Structured, actionable backlog from the 2026-06-13 architecture / fitness-for-purpose
review. The core of nfr-review (engine, registry, protocols, models, config, the
AST-collector base) is sound — these tasks address **consistency and scale-tax**:
modules that outgrew their abstractions, one subsystem (`arch_*`) that diverged from
the core patterns, and good patterns that were only partially adopted.

Estimated net effect: **−1,500 to −2,500 lines** with no loss of capability.

Tasks are ordered by recommended execution sequence. Each is independently shippable.
Lean on the existing test suite (`python -m pytest -n auto tests/`) and `ruff` after
every change. Watch the **R007 finding column-order test** whenever finding
construction changes.

---

## 1. Eliminate rule boilerplate (High value, Medium effort)

**Problem**
- 110 of 112 rule files hand-roll the same "no issues → green/info finding" block
  (~20 lines each).
- ~46 language-specific rules repeat the same 7-line "filter evidence by
  collector/kind, skip if empty" prologue.
- A suitable base already exists — `GenericASTRule` in
  `src/nfr_review/rules/ast_common.py:32` — but only the 2–3 cross-language rules use it.

**Do**
- Add a `make_green_finding(rule_id, pattern_tag, collector_name, collector_version, ...)`
  helper (centralize the green/info message, confidence, `evidence_locator="project-wide"`).
- Add a `RuleBase` (or extend the `Rule` protocol with a mixin) exposing
  `filter_evidence(evidence, collector_name, kind) -> list[Evidence]` plus a standard
  "skipped if empty" `RuleResult`.
- Migrate rules incrementally; prefer routing language-specific AST rules through
  `GenericASTRule` where they fit.

**Acceptance**
- Per-rule finding-construction boilerplate removed; behavior unchanged.
- R007 column-order test still passes (`tests/test_output.py`).
- ~1,000–1,400 fewer lines across `src/nfr_review/rules/`.

---

## 2. Make `JavaAstCollector` inherit `BaseASTCollector` (High value, Small effort)

**Problem**
- 5 of 6 language AST collectors inherit `BaseASTCollector`
  (`src/nfr_review/collectors/ast_common.py:77`). `JavaAstCollector`
  (`src/nfr_review/collectors/java_ast.py:598`) is the outlier — it reimplements
  `collect()`, `_get_parser()`, `_text()`, and `_find_nodes()` (~55 duplicated lines).
- `_text` / `_find_nodes` are also duplicated in `src/nfr_review/collectors/terraform.py:66-76`;
  canonical versions live in `ast_common.py:62-74` as `text()` / `find_nodes()`.

**Do**
- Refactor `JavaAstCollector` to subclass `BaseASTCollector`, implementing only
  `_parse_file()` (matching the other collectors).
- Replace local `_text` / `_find_nodes` in `java_ast.py` and `terraform.py` with imports
  from `ast_common`.

**Acceptance**
- One collection code path for all AST collectors; `tests/` for Java AST still pass.
- ~75 fewer lines.

---

## 3. Auto-discover collectors & rules (High value, Small effort)

**Problem**
- `src/nfr_review/rules/__init__.py` is 369 lines of manual imports for 112 rule files;
  `collectors/__init__.py` similar. A missed import fails **silently** (rule never registers).

**Do**
- Replace the explicit import lists with `pkgutil.iter_modules` + `importlib.import_module`
  directory scanning, triggering each module's `_register()` side effect.
- Keep the same registries (`rule_registry`, `collector_registry`, hygiene equivalents).
- Apply the same treatment to `hygiene/rules/__init__.py` and `hygiene/collectors/__init__.py`.

**Acceptance**
- All currently-registered rules/collectors still register (assert counts in a test).
- Adding a new rule/collector file requires no `__init__.py` edit.
- `__init__.py` files shrink to a few lines each.

---

## 4. Decompose `run_report_pipeline` (Medium value, Medium effort)

**Problem**
- `src/nfr_review/cli.py:834-1262` is a ~430-line procedural function mixing config-merge,
  suppressions, scoring, LLM resolution, and 6 output writers.
- `all_findings = nfr + hygiene` is recomputed **4 times** (lines 991, 1050, 1082, 1144)
  and `combined_result` is rebuilt repeatedly.

**Do**
- Extract phase helpers, e.g. `_run_scans()`, `_build_sections()`, `_compute_score()`,
  `_resolve_llm_info()`, `_write_outputs()`.
- Compute the combined finding list and `combined_result` **once** and thread them through.

**Acceptance**
- `run_report_pipeline` becomes a readable orchestration shell; existing CLI/report tests pass.
- No duplicated finding-list concatenation.

---

## 5. Extract `arch_utils.py` and table-drive build-dep matchers (Medium value, Medium effort)

**Problem**
- `_safe_read_text`, `_safe_yaml_load`, `_safe_yaml_load_all`, `_safe_json_load`, `_make_id`
  are reimplemented in `arch_discovery.py`, `arch_integrations.py`, and `arch_domain_model.py`.
- `arch_integrations.py:2301-2670` contains 7 near-identical build-dependency matchers
  (`_match_maven_deps` … `_match_dotnet_deps`, ~370 lines) differing only by lookup table.

**Do**
- Create `src/nfr_review/arch_utils.py` with the shared safe-IO / id helpers; import everywhere.
- Collapse the 7 matchers into one table-driven factory keyed by ecosystem
  (`{ecosystem: (lookup_table, predicate)}`).

**Acceptance**
- Single source of truth for the helpers; arch tests pass.
- ~400 fewer lines in `arch_integrations.py`.

---

## 6. Route `arch` collection through the Engine/registry (High value, Large effort)

**Problem**
- The architecture-report feature bypasses the core pipeline. `arch_orchestrator.py:118-144`
  instantiates collectors ad-hoc via `importlib` and calls `collector.collect(target, config=None)`
  directly — discarding collector config and the engine's filtering, tracing, and
  fault-tolerance (R012). This creates two divergent collection pipelines.
- `arch_integrations.py` (3,133 lines) is a god-module: 10 copy-paste discovery strategies
  dispatched by sequential `extend()` calls (`arch_integrations.py:2861-2938`) rather than
  a strategy registry.

**Do**
- Feed `arch` from the same registry-driven `Engine.run()` so collector config and
  fault-tolerance are shared (a real `Config` instead of `config=None`).
- Split `arch_integrations.py` into focused modules
  (`arch_integrations_k8s.py`, `_compose.py`, `_build.py`, `_config.py`, `_core.py`).
- Introduce a strategy registry/list so discovery strategies can be ordered/enabled/disabled.

**Acceptance**
- `arch` and `report` share one collection path; arch regression snapshots
  (`tests/regression/`) still match.
- `arch_integrations.py` no longer exceeds ~800 lines per module.

---

## 7. LLM client: shared base + resilience (Medium value, Medium effort)

**Problem**
- `src/nfr_review/llm_client.py` carries a deprecated `ClaudeClient` alongside three new
  backends (`AnthropicClient`, `OpenAICompatibleClient`, `ClaudeCliClient`) whose `analyze()`
  methods are near-identical (available-check → `combined = prompt + "\n\n" + bundle` →
  log → call).
- No retry/backoff and no timeout on the API backends (only the CLI backend has a 120s timeout).

**Do**
- Extract a small base/mixin for the shared `analyze()` scaffolding.
- Add bounded retry with backoff on transient API errors; add a request timeout to the
  API backends.
- Plan removal of the deprecated `ClaudeClient` (confirm no remaining callers first).

**Acceptance**
- One shared analyze scaffold; backends differ only in the provider call.
- Transient-failure retry covered by a unit test (mock the SDK per ARCHITECTURE.md guidance).

---

## 8. Finish the typed-payload migration (Medium value, Large effort)

**Problem**
- Collectors emit typed `BasePayload` subclasses, but rules still read them as dicts
  (`ev.payload.get("catch_blocks", [])`), kept working only by the dict-compat shim on
  `BasePayload` (`src/nfr_review/models.py:15-56`). The shim is the visible evidence of an
  unfinished migration; static type checking is lost at the rule boundary.

**Do**
- Narrow payload access in rules to the concrete payload type (`isinstance` / type-narrowing).
- Once rules no longer rely on dict access, deprecate and remove the `BasePayload` dict shim
  (`get`/`__getitem__`/`keys`/`values`/`items`/`__contains__`).

**Acceptance**
- mypy catches payload key typos at the rule boundary.
- Dict shim removed (or scheduled for removal with no remaining callers).

---

## Quick reference — recommended order

| # | Task | Effort | Primary payoff |
|---|------|--------|----------------|
| 1 | Rule boilerplate helpers | M | −~1,200 lines, consistency |
| 2 | `JavaAstCollector` inherits base | S | −~75 lines, one code path |
| 3 | Auto-discover plugins | S | kills silent-omission bugs |
| 4 | Split `run_report_pipeline` | M | readability, fewer bugs |
| 5 | `arch_utils.py` + matcher factory | M | −~400 lines |
| 6 | `arch` through the Engine | L | one pipeline, shared config/fault-tolerance |
| 7 | LLM base + retry/timeout | M | robustness |
| 8 | Finish typed payloads | L | type safety |

Tasks 1–4 are high-value, low-blast-radius quick wins. Tasks 6 and 8 are the strategic
ones — they resolve the two half-finished migrations in the codebase (arch-vs-engine,
dict-vs-typed-payload).
