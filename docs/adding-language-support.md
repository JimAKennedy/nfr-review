# Adding Support for a New Language

Covers adding a new **AST-backed programming language** to nfr-review — Go, Python,
Rust, etc. For general "technology" support (Kubernetes, Terraform, Helm, and similar
config-driven infrastructure), see
[Adding a New Collector](../CONTRIBUTING.md#adding-a-new-collector) instead.

## Table of contents

1. [Overview](#1-overview)
2. [Steps](#2-steps)
3. [Decision guide](#3-decision-guide)
4. [Reference appendix](#4-reference-appendix)

## 1. Overview

| Piece | Required? |
|---|---|
| A tech key + detector in `detect.py` | Always |
| An AST collector + payload model | Always |
| A deps collector | Only if the ecosystem is supported by deps.dev — see [§3](#3-decision-guide) |
| Auxiliary collectors (build-config/tool-output parsers) | Only if warranted — see [§3](#3-decision-guide) |
| One or more `FieldRule[P]` rules | Always |

Everything wires itself in automatically. `src/nfr_review/collectors/__init__.py` and
`src/nfr_review/rules/__init__.py` both use `pkgutil.iter_modules()` to import every
module in their package, which triggers each module's own `_register()` call (or, for
rules, `FieldRule.__init_subclass__`) at import time. There is no central registry
file to edit — dropping a correctly-shaped module into `collectors/` or `rules/` is
sufficient.

## 2. Steps

### Step 1 — Tech detection

Add a key to `ALL_TECH_KEYS` and a `_detect_<lang>` predicate in
`src/nfr_review/detect.py`, registered in the `_DETECTORS` dict. Keep it to cheap
filesystem checks — no parsing.

```python
# src/nfr_review/detect.py
def _detect_go(repo: Path) -> bool:
    return _safe_exists(repo / "go.mod")
```

A single manifest check is the common case. Checking several candidate files is also
valid when there's no one canonical manifest.

### Step 2 — Tree-sitter grammar

Add the grammar package to **two** places in `pyproject.toml` — they must stay in
sync:

```toml
# [project] dependencies
"tree-sitter-go>=0.23",
```
```toml
# [[tool.mypy.overrides]] module list
"tree_sitter_go.*",
```

Then register it in `_GRAMMAR_LOADERS` in `src/nfr_review/collectors/ast_common.py`:

```python
_GRAMMAR_LOADERS: dict[str, tuple[str, str]] = {
    ...
    "go": ("tree_sitter_go", "language"),
}
```

The tuple is `(module_name, function_name_on_that_module)` — `make_parser()` imports
the module and calls that function to get the grammar pointer.

### Step 3 — AST collector + payload

Subclass `BaseASTCollector` (also in `ast_common.py`):

```python
# src/nfr_review/collectors/go_ast.py
class GoAstCollector(BaseASTCollector):
    name = "go-ast"
    version = "0.1.0"
    language = "go"
    file_extensions = (".go",)
    evidence_kind = "go-ast-file"

    def _parse_file(self, source: bytes, rel_path: str) -> GoAstFilePayload:
        assert self._parser is not None
        tree = self._parser.parse(source)
        root = tree.root_node
        return GoAstFilePayload(
            file_path=rel_path,
            structs=_extract_structs_and_interfaces(root, source),
            catch_blocks=_extract_catch_blocks(root, source, rel_path),
            functions=_extract_functions(root, source),
            # ... one extractor per thing your rules will need to see
        )


def _register() -> None:
    if "go-ast" not in collector_registry:
        collector_registry.register("go-ast", GoAstCollector())


_register()
```

`BaseASTCollector` handles file discovery by extension, hidden-directory skipping,
parser setup, path exclusion, and wrapping the payload into `Evidence` — you only
implement `_parse_file()`. `file_extensions` is a tuple, so languages with multiple
source extensions are supported without extra work.

Define the payload in `src/nfr_review/collectors/payloads/<lang>_ast.py` as a
`BasePayload` subclass (from `nfr_review.models`). Model exactly what the language's
rules need to see — the shape isn't fixed. Omit fields that don't apply (e.g. a
`classes` list) if the language doesn't have that concept.

### Step 4 — Deps collector

Only build this if [§3](#3-decision-guide) says the ecosystem is supported. Parse the
manifest, enrich via the shared `DepsDevClient`, and reuse the shared `DepsPayload` /
`DependencyItem` model — every deps collector reuses this one payload; there's no
reason to invent a per-language deps payload.

```python
# src/nfr_review/collectors/go_deps.py
class GoDepsCollector:
    name = "go-deps"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        raw_deps = [...]  # parse go.mod
        if not raw_deps:
            return []

        client = DepsDevClient()
        client.prefetch_package_versions("go", [name for _, name, _, _ in raw_deps])
        dependencies = [_enrich(client, ...) for ... in raw_deps]

        payload = DepsPayload(dependencies=dependencies, manifest_files_found=[...])
        return [Evidence(collector_name=self.name, collector_version=self.version,
                          locator=".", kind="go-deps", payload=payload)]


def _register() -> None:
    if "go-deps" not in collector_registry:
        collector_registry.register("go-deps", GoDepsCollector())


_register()
```

`client.prefetch_package_versions(<ecosystem>, names)` followed by
`client.get_package_versions(<ecosystem>, name)` + `pick_latest_version(...)` is the
whole enrichment contract. `<ecosystem>` is a deps.dev ecosystem key (`"go"`,
`"pypi"`, `"npm"`, `"nuget"`, `"cargo"` for Rust) — confirm the exact key deps.dev
expects before wiring it in.

### Step 5 — Rules

Subclass `FieldRule[P]`. The full attribute/field reference (the `Hit` dataclass,
`rag`/`severity`/`confidence`, all-clear findings, band levels) is documented in
[`docs/custom-rules.md`](custom-rules.md#fieldrule--the-recommended-approach) — this
guide won't repeat it. What matters here is how gating works from the engine's side:

```python
# src/nfr_review/engine.py — _check_rule_eligibility (simplified)
required_tech: list[str] = getattr(rule, "required_tech", [])
missing_tech = [t for t in required_tech if not config.tech.get(t, False)]
if missing_tech:
    return f"tech not declared: {', '.join(missing_tech)}"

missing = [c for c in rule.required_collectors if c not in succeeded_collectors]
if missing:
    return f"missing required collectors: {', '.join(missing)}"
```

`config.tech` is the dict your Step 1 detector populates. `required_collectors` is
derived automatically from `collector_name` by `FieldRule.__init_subclass__` — you
don't set it yourself. `required_tech` is the one gate you do set — **always set it
explicitly** on every rule.

```python
# src/nfr_review/rules/go_defer_in_loop.py
class GoDeferInLoopRule(FieldRule[GoAstFilePayload]):
    id = "go-defer-in-loop"
    collector_name = "go-ast"
    evidence_kind = "go-ast-file"
    payload_type = GoAstFilePayload
    pattern_tag = "go-defer-in-loop"
    required_tech: list[str] = ["go"]
    all_clear_summary = "No defer-in-loop patterns detected."

    def check(self, payload: GoAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for stmt in payload.defer_statements:
            if stmt.in_loop:
                yield Hit(rag="amber", severity="medium", summary=..., recommendation=..., locator=...)
```

### Step 6 — Tests + fixtures

Create:

- `tests/test_<lang>_ast_collector.py`
- `tests/test_<lang>_deps_collector.py` (if you built a deps collector)
- `tests/test_<lang>_rules.py`
- `tests/test_<lang>_integration.py` — full detect → collect → rules engine run
- `tests/fixtures/<lang>-sample-repo/` — one "bad" fixture file per rule, plus a clean
  fixture that should produce zero findings
- `tests/fixtures/<lang>-deps-sample-repo/` (if applicable)

### Step 7 — Payload registry

Add the `(collector_name, evidence_kind) -> Payload` entries to
`src/nfr_review/_payload_registry.py`. This is a manually-maintained list, not
auto-discovered. Deps collectors map to the shared `DepsPayload`; AST collectors map
to your new payload class.

### Step 8 — Docs

Add a row for the language to README's "Supported technologies" table (plus a "Code
quality" row too, if you added an auxiliary tool-output collector).

## 3. Decision guide

**Do I need a deps collector?**
Check whether [deps.dev](https://deps.dev) supports the language's package ecosystem.
If yes, build it — follow Step 4. If no, skip it rather than forcing a workaround.

**Do I need an auxiliary collector?**
Only if a widely-used external tool for the language produces a report or config
worth parsing on its own — a coverage report, a coupling/structure report, build-system
config. Existing examples of this shape ("parse a third-party tool's output format"):
- JaCoCo — parses coverage XML, no subprocess.
- JDepend — shells out to the `jdepend` CLI against compiled bytecode, parses its XML
  output.
- CMake — parses `CMakeLists.txt` for build-config hygiene.

If nothing like this exists for your language yet, skip this step — it's additive,
not required.

## 4. Reference appendix

| Language | Detector signal | AST extensions | Deps ecosystem key | Auxiliary collectors |
|---|---|---|---|---|
| Go | `go.mod` | `.go` | `go` | — |
| Python | `pyproject.toml` / `setup.py` / `setup.cfg` / `requirements.txt` | `.py` | `pypi` | — |
| Node.js/TS | `package.json` | `.js` `.ts` `.jsx` `.tsx` (one TS grammar) | `npm` | — |
| Java | `pom.xml` / `build.gradle(.kts)` / any `.java` under `src/` | `.java` | `maven` | JaCoCo, JDepend |
| C# | any `*.csproj` or `*.sln` | `.cs` | `nuget` | — |
| C++ | `CMakeLists.txt` / `Makefile` / `meson.build` / `.vcxproj` / conan/vcpkg files / any `.cpp`,`.cc`,`.cxx` | `.cpp .cc .cxx .h .hpp .hxx` | none | CMake |

## Further reading

- [`docs/custom-rules.md`](custom-rules.md) — the full `FieldRule[P]` / `Hit` contract,
  registration, scoring integration, and the external plugin API.
- [`docs/rule-framework.md`](rule-framework.md) — design rationale for why `FieldRule`
  exists and what it deliberately doesn't cover.
