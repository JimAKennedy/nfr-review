# NFR Review — Changes Log

## Session: 2026-10-22 — Modularisation Refactor (dev branch)

### Context

Working repo: `TheCharlieKennedy/nfr-review` (dev branch)  
Target PR destination: `JimAKennedy/nfr-review` (when complete)  
Branch: `dev`

---

### Work completed

#### 1. Requirements review and planning
- Read `JK-nfr-review-OSS-reqs.pdf` and produced `docs/internal/nfr-PLAN.md` — full requirements breakdown (33 stories across 6 milestones) and package architecture.
- Produced `nfr-reqs-summary.md` (this directory) — technology dictionary, terms dictionary, requirements by section.
- Decision: Python entry points (already in codebase via `plugin_discovery.py`) as the plugin/extension mechanism. External rule packs self-register into `rule_registry` and `collector_registry` on import — no central file needs editing.
- Decision: enterprise teams without LLM access install `nfr-core` + only approved lang packs via `requirements.txt`. No separate enterprise package needed.

#### 2. Package architecture decision
Split into three tiers:
- **`nfr-core`** — engine, CLI, infra/platform collectors and rules, hygiene, arch analysis, output renderers. Bundles Python, HCL and Dockerfile lang support (no optional deps beyond pydantic, ruamel.yaml, tree-sitter, click).
- **`nfr-utils[llm|monitor|diagrams|pdf|scancode]`** — optional extras, each independently installable.
- **`nfr-lang-<name>`** — additive languages (Java, Go, Rust, C#, Node.js, C++, Gatling) as optional extras. Python stays in core.
- **`nfr-review`** — meta-package pulling in core + all lang packs (unchanged install UX for existing users).

Key correction made during review: Python was initially planned as a separate lang pack but correctly moved to core — nfr-review scans Python repos by default and its own hygiene rules require Python AST support. This was caught during implementation review.

#### 3. CLAUDE.md and .gitignore updates
- Added repo role rules (TheCharlieKennedy = dev, JimAKennedy = prod).
- Added scope rules (no hard LLM/diagrams/scancode deps in core or lang packs, Band 2 graceful skip, no out-of-scope features).
- Added modularisation plan summary.
- Added planning docs location rules.
- Added `docs/internal/nfr-PLAN.md` to `.gitignore`.

#### 4. pyproject.toml restructure (commit `63ec209`)
- Removed lang tree-sitter grammars from hard `[project.dependencies]`.
- `tree-sitter-python` kept in core hard deps (Python bundled in core).
- Added `lang-java`, `lang-go`, `lang-rust`, `lang-csharp`, `lang-nodejs`, `lang-cpp` optional extras.
- Renamed `llm-anthropic` → `llm`, consolidated `graphify` into `diagrams`.
- Added `langs` meta-extra (all lang packs) and updated `full` meta-extra.
- Added `anthropic.*` to mypy overrides (was missing).

#### 5. Graceful skip for missing grammars (commits `93b6de4`, part of `63ec209`)
- `collectors/ast_common.py` — `collect()` changed from raising `RuntimeError` to returning `[]` and logging at INFO when grammar not installed.
- `collectors/dockerfile.py` — same fix; dockerfile grammar has no Python 3.13 wheel yet.
- `pyproject.toml` — constrained `tree-sitter-dockerfile` to `python_version < '3.13'` so install doesn't fail on 3.13.
- Tool now runs cleanly on Python 3.13.

#### 6. `_payload_registry.py` made lazy (commit `346565c`)
- Core payloads always registered at startup.
- Optional lang pack payloads (Java, Go, Rust, C#, Node.js, C++, Gatling, graphify) wrapped in `try/except ImportError` — missing lang pack no longer crashes startup.

#### 7. Conditional auto-import in collectors and rules (commit `790b674`)
- `collectors/__init__.py` — added `_OPTIONAL_LANG_COLLECTORS` set; optional lang collectors wrapped in `try/except ImportError`.
- `rules/__init__.py` — added `_OPTIONAL_LANG_RULES` set; optional lang rules wrapped in `try/except ImportError`.
- Core and Python modules load unconditionally; all other lang modules only load when their grammar package is installed.

#### 8. install.md updated (commit `174ee9c`)
- Replaced old extras table (`llm-anthropic`, `graphify` as separate extra) with new structure.
- Added language packs section with per-language extras.
- Added enterprise install example.
- Updated LLM backend table and setup examples from `[llm-anthropic]` to `[llm]`.

---

### Verified working
- `nfr-review run .` on Python 3.13: completes cleanly, 35 collectors, 111 findings (with Python grammar installed), no crashes.
- Missing lang grammars log gracefully and skip — no RuntimeError.
- LLM unavailability handled gracefully (existing behaviour, confirmed still working).

---

### Commits on dev (this session)

| Commit | Description |
|--------|-------------|
| `63ec209` | refactor: restructure optional deps for modular lang/utils split |
| `93b6de4` | fix: graceful skip for missing grammars on Python 3.13 |
| `49a0a59` | refactor: keep Python in core, separate only additive lang packs |
| `346565c` | refactor: make _payload_registry lazy for optional lang pack payloads |
| `790b674` | refactor: conditional auto-import for optional lang collectors and rules |
| `174ee9c` | docs: update install.md for modular lang pack and extras structure |

---

### Next steps

- Raise PR from `TheCharlieKennedy/nfr-review:dev` to `JimAKennedy/nfr-review` when ready.
- Next milestone (new branch): M1 — Evidence Foundation (OBS-001, OBS-002, OBS-003, IAC-001, IAC-003, JAVA-001, JAVA-002, RULE-001).
