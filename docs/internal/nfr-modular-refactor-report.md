# NFR Review — Modular Refactor Report

Date: 2026-10-25  
Branch: `main` (commits `c323511` → `174ee9c`)

---

## Summary

Five commits restructured nfr-review's dependency model so that language support is opt-in rather than bundled. Python stays in core; all other languages become separately installable extras. A minimal install now ships without tree-sitter grammars for languages the team doesn't use.

---

## Changes by Area

### Packaging (`pyproject.toml`)

- Tree-sitter grammars for Java, Go, Rust, C#, Node.js, C++, and Gatling moved from hard dependencies to `lang-*` optional extras
- Utils extras consolidated: `llm`, `diagrams`, `monitor`, `pdf`, `scancode`, `otel`
- Meta-extras added: `langs` (all lang packs), `full` (everything)
- `[llm-anthropic]` extra renamed to `[llm]` throughout

### Core vs. Lang Pack boundary

- Python collectors and rules kept in `nfr-core` — the tool scans Python repos by default and its own hygiene rules depend on Python AST
- Java, Go, Rust, C#, Node.js, C++, and Gatling designated optional lang packs
- CLAUDE.md updated with repo role, scope rules, and modularisation guidance

### Startup and registry (`_payload_registry.py`)

- Core payloads always registered at startup
- Optional lang pack payloads (Java, Go, Rust, C#, Node.js, C++, Gatling, graphify) wrapped in `try/except ImportError`
- Missing lang pack no longer crashes startup — silently skipped

### Auto-import (`collectors/__init__.py`, `rules/__init__.py`)

- Core and Python modules load unconditionally
- All other lang modules wrapped in `try/except ImportError`
- Missing packs logged at DEBUG level and skipped — no user-visible error

### AST common collector (`ast_common.py`)

- Updated to gracefully skip (not raise) when a grammar is not installed
- Companion fix for Python 3.13 where certain grammars were absent

### Documentation (`docs/install.md`)

- Old extras table (listing `llm-anthropic`, `graphify` as top-level examples) replaced with the `lang-*` pack structure
- Enterprise install example added
- LLM section references updated from `[llm-anthropic]` to `[llm]`

---

## Install Surface — Before vs. After

| Scenario | Before | After |
|---|---|---|
| Minimal install | All grammars pulled in | Python only |
| Java teams | Same as minimal | `nfr-review[lang-java]` |
| All languages | Same as minimal | `nfr-review[langs]` |
| Everything | Same as minimal | `nfr-review[full]` |

---

## Design Decisions

**Python in core, not a lang pack.** The tool is written in Python and its own repo hygiene rules (e.g. pyproject.toml checks) require Python AST. Separating Python would break self-scan on every install.

**Graceful skip, not hard fail.** A missing lang pack is a packaging choice, not an error. Collectors and rules that can't import their grammar log at DEBUG and continue — the rest of the scan runs normally.

**Entry-point self-registration unchanged.** Lang packs still self-register via `importlib.metadata` entry points on import. The modular split didn't change the registration contract — it just made the import conditional.

---

## Open Items

None. All changes are in `main`. No outstanding issues raised against this refactor.
