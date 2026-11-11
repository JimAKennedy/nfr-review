# M001/S03 plan — Grammar loading and its tests

**Slice:** M001/S03 — ledger `docs/plans/pr255-remediation/ledger.md`

**Task status**

- [ ] Task 1 — G1: `tree-sitter-dockerfile>=0.2` behind a marker for the two published wheels
- [ ] Task 2 — G3 + T1: reset grammar warnings per run, record each once; rewrite the "Raises…" tests to assert the warning
- [ ] Task 3 — G2 + T1: only a missing grammar module or a failing `getattr(mod, func_name)` counts as "not installed"
- [ ] Task 4 — Slice gate and evidence

**Definition of Done**

- [ ] On a platform without a 0.2 wheel, `tree-sitter-dockerfile` is not installed at all rather than as a placeholder, and aarch64 stays excluded
- [ ] Only a failing `getattr(mod, func_name)` is treated as "grammar not installed"; an `AttributeError` raised elsewhere propagates
- [ ] Repeated runs on the same collector instance report each grammar warning once
- [ ] The tests named "Raises…" assert the recorded warning, and the `BaseASTCollector` warning path is asserted

**Validation**

Run from the worktree root with the venv active (`source .venv/bin/activate`, so
`python` is `.venv/bin/python`):

- `format` → `pre-commit run --all-files`
- `unit` → `python -m pytest -n auto -m "not regression" tests/`
- `gate` → `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`


> **Evidence rule (ledger standard):** evidence is appended per task as it lands and never names a commit SHA; the commits are found with `git log --grep="Slice: M001/S03"`. Earlier wording in this plan that asked for SHAs was removed on 2026-11-11 before execution.

## Context the executor needs

- `src/nfr_review/collectors/ast_common.py`: `make_parser(language)` does
  `importlib.import_module(module_name)` then `getattr(mod, func_name)()` then
  `tree_sitter.Parser(tree_sitter.Language(...))` in one expression chain.
  `BaseASTCollector._get_parser()` catches `(ImportError, ModuleNotFoundError,
  AttributeError)`, appends a warning to `self.grammar_warnings`, and returns
  `None`; on failure `self._parser` stays `None`, so every later call retries
  and appends again.
- `src/nfr_review/collectors/dockerfile.py`: `DockerfileCollector` does not
  subclass `BaseASTCollector`; it imports `make_parser` from `ast_common` and
  duplicates `_get_parser()` with the same catch and the same append.
- `src/nfr_review/engine.py` `Engine._run_one_collector` copies
  `getattr(collector, "grammar_warnings", [])` **after** `collector.collect()`
  returns. Resetting the list at the start of `collect()` is therefore enough
  for G3; `engine.py` needs no edit. The ledger lists `engine.py` under G3's
  "Lands in"; the engine-level test in Task 2 is its verification.
- Both collectors are registered as module-level singletons
  (`collector_registry.register("go-ast", GoAstCollector())`, likewise
  `"dockerfile"`), which is why warnings accumulated across runs.
- PyPI facts (checked 2026-11-10): `tree-sitter-dockerfile` has releases
  `0.0.0a1` and `0.2.0`; 0.2.0 ships exactly
  `tree_sitter_dockerfile-0.2.0-cp38-abi3-macosx_11_0_arm64.whl` and
  `tree_sitter_dockerfile-0.2.0-cp38-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`,
  and no sdist.
- The venv has no `pip`; use `uv pip` (on PATH at `/opt/homebrew/bin/uv`).
- Do not regenerate `requirements.txt` / `requirements-dev.txt` in this
  slice; M001/S10 does that after S03 and S04 land.
- After editing any `.py` file run `ruff format <file>` before committing
  (project CLAUDE.md).
- Known pre-existing issue that affects `gate` (and `regression`): on
  2026-11-10 the `httpx` and `gin` regression snapshots fail with new
  `dep-freshness` findings ("no release in N months"), with or without any
  S03 change and with or without `ANTHROPIC_API_KEY`. `gate` runs them twice
  (its `tests/` step includes `tests/regression/`). If they still fail when
  you reach Task 4, do not refresh snapshots in this slice (no S03 change
  touches rule output); record the failure and its cause in the evidence and
  stop for the owner, per the snapshot-refresh workflow.
- `tests/fixtures/*/graphify-out/` directories (gitignored) exist in this
  worktree: graphify writes into the scanned fixture repos during the test
  run (row GR1, fixed by M001/S04). Leave them; they are not part of S03.

## Task 1 — G1: `tree-sitter-dockerfile>=0.2` behind a marker for the two published wheels

**Rows:** G1
**Files:** `pyproject.toml` (modify), `tests/test_pyproject_dependencies.py` (create)
**Consumes:** the PyPI wheel list above.
**Produces:** the dependency line
`"tree-sitter-dockerfile>=0.2; (sys_platform == 'darwin' and platform_machine == 'arm64') or (sys_platform == 'linux' and platform_machine == 'x86_64')"`
and the dry-run resolution recorded for evidence.

Steps:

1. Write the failing test. Create `tests/test_pyproject_dependencies.py`:

   ```python
   """G1: tree-sitter-dockerfile is a dependency only where a 0.2 wheel exists.

   PyPI publishes tree-sitter-dockerfile 0.2.0 as two wheels (macOS arm64 and
   manylinux x86_64) and no sdist. Everywhere else the only installable release
   is the 0.0.0a1 "coming soon" placeholder, which has no grammar in it, so the
   requirement must not resolve there at all.
   """

   from __future__ import annotations

   import tomllib
   from pathlib import Path

   import pytest
   from packaging.markers import default_environment
   from packaging.requirements import Requirement

   _PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


   def _dockerfile_requirement() -> Requirement:
       data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
       matches = [
           req
           for req in (Requirement(line) for line in data["project"]["dependencies"])
           if req.name == "tree-sitter-dockerfile"
       ]
       assert len(matches) == 1, matches
       return matches[0]


   def test_requires_the_first_real_grammar_release() -> None:
       assert str(_dockerfile_requirement().specifier) == ">=0.2"


   @pytest.mark.parametrize(
       ("sys_platform", "platform_machine", "installed"),
       [
           ("darwin", "arm64", True),
           ("linux", "x86_64", True),
           ("linux", "aarch64", False),
           ("darwin", "x86_64", False),
           ("win32", "AMD64", False),
       ],
   )
   def test_marker_matches_the_published_wheels(
       sys_platform: str, platform_machine: str, installed: bool
   ) -> None:
       marker = _dockerfile_requirement().marker
       assert marker is not None
       env: dict[str, str] = {
           **default_environment(),
           "sys_platform": sys_platform,
           "platform_machine": platform_machine,
       }
       assert marker.evaluate(env) is installed
   ```

   (`packaging` is already a core dependency, `packaging>=24.0`.)

2. Run it and see it fail:
   `.venv/bin/python -m pytest -n0 tests/test_pyproject_dependencies.py`
   Expected: 3 failed, 3 passed. `test_requires_the_first_real_grammar_release`
   fails because the specifier is `>=0.0.0a1`; the `darwin-x86_64-False` and
   `win32-AMD64-False` cases fail because the current marker
   `platform_machine != 'aarch64'` evaluates `True` there.

3. Implement. In `pyproject.toml` `[project].dependencies`, replace the line

   ```toml
       "tree-sitter-dockerfile>=0.0.0a1; platform_machine != 'aarch64'",
   ```

   with

   ```toml
       "tree-sitter-dockerfile>=0.2; (sys_platform == 'darwin' and platform_machine == 'arm64') or (sys_platform == 'linux' and platform_machine == 'x86_64')",
   ```

   Leave the `tree_sitter_dockerfile.*` mypy override and everything else as is.

4. Run and pass:
   `.venv/bin/python -m pytest -n0 tests/test_pyproject_dependencies.py`
   Expected: 6 passed.

5. Record the resolution (G1's Verification cell). Run from the worktree root:

   ```sh
   REQ="tree-sitter-dockerfile>=0.2; (sys_platform == 'darwin' and platform_machine == 'arm64') or (sys_platform == 'linux' and platform_machine == 'x86_64')"
   for p in aarch64-apple-darwin x86_64-manylinux_2_17 aarch64-manylinux_2_17 x86_64-apple-darwin x86_64-pc-windows-msvc; do
     echo "== $p"
     uv pip install --dry-run --no-cache --python .venv/bin/python \
       --python-platform "$p" --python-version 3.11 --reinstall "$REQ" 2>&1 | tail -4
   done | tee /tmp/m001-s03-g1-dry-run.txt
   ```

   Expected: `aarch64-apple-darwin` and `x86_64-manylinux_2_17` each show
   `+ tree-sitter-dockerfile==0.2.0`; `aarch64-manylinux_2_17`,
   `x86_64-apple-darwin` and `x86_64-pc-windows-msvc` each show
   `Would make no changes`. Keep `/tmp/m001-s03-g1-dry-run.txt`; Task 4 copies
   it into the evidence file. (`uv pip install --dry-run` stands in for
   `pip install --dry-run`: the venv has no pip.)

6. Check (`format`): `pre-commit run --all-files` passes. `ruff format
   tests/test_pyproject_dependencies.py` first.

7. Commit:

   ```sh
   git add pyproject.toml tests/test_pyproject_dependencies.py
   git commit -F - <<'EOF'
   fix(deps): require tree-sitter-dockerfile 0.2 only where its wheels exist

   The >=0.0.0a1 floor resolved to an empty placeholder package on every
   platform without a 0.2.0 wheel, silently disabling Dockerfile analysis.
   0.2.0 ships only macOS arm64 and manylinux x86_64 wheels and no sdist, so
   the marker now names exactly those; aarch64 Linux stays excluded.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S03
   Rows: G1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

## Task 2 — G3 + T1: reset grammar warnings per run, record each once; rewrite the "Raises…" tests to assert the warning

**Rows:** G3, T1
**Files:** `tests/test_missing_grammar_warning.py` (rewrite),
`src/nfr_review/collectors/ast_common.py` (modify `BaseASTCollector._get_parser`, `BaseASTCollector.collect`),
`src/nfr_review/collectors/dockerfile.py` (modify `DockerfileCollector._get_parser`, `DockerfileCollector.collect`)
**Consumes:** `GoAstCollector` (`name = "go-ast"`, `language = "go"`), `DockerfileCollector`, `Engine(collectors=, rules=, workers=)`, `Registry("collector")`.
**Produces:** `collect()` starts with an empty `grammar_warnings`; `_get_parser()` appends a message only if it is not already present.

Steps:

1. Write the failing tests. Replace the whole of
   `tests/test_missing_grammar_warning.py` with:

   ```python
   """A missing tree-sitter grammar (e.g. no aarch64 wheel for tree-sitter-dockerfile)
   must surface as a visible run warning, not silently produce zero findings.

   Deliberately does not depend on any real grammar being installed — every test
   here mocks the grammar loader, so this exercises the same code path
   regardless of which platform CI (or this environment) runs on.
   """

   from __future__ import annotations

   from pathlib import Path
   from unittest.mock import patch

   import pytest

   from nfr_review.collectors.dockerfile import DockerfileCollector
   from nfr_review.collectors.go_ast import GoAstCollector
   from nfr_review.config import Config
   from nfr_review.engine import Engine
   from nfr_review.registry import Registry

   _GO_WARNING = "tree-sitter grammar for go not installed on this platform — collector disabled"
   _DOCKERFILE_WARNING = (
       "tree-sitter grammar for dockerfile not installed on this platform — collector disabled"
   )


   class TestBaseASTCollectorRecordsWarning:
       """Covers every BaseASTCollector subclass generically (Java, Python, Go,
       Rust, C++, C#, Node, HCL) — GoAstCollector stands in as one concrete
       example of the shared base-class behavior."""

       def test_missing_module_records_warning(self, tmp_path: Path) -> None:
           collector = GoAstCollector()
           with patch(
               "nfr_review.collectors.ast_common.make_parser",
               side_effect=ImportError("no module named tree_sitter_go"),
           ):
               result = collector.collect(tmp_path, config=None)
           assert result == []
           assert collector.grammar_warnings == [_GO_WARNING]

       def test_repeated_collect_records_the_warning_once(self, tmp_path: Path) -> None:
           collector = GoAstCollector()
           with patch(
               "nfr_review.collectors.ast_common.make_parser",
               side_effect=ImportError("no module named tree_sitter_go"),
           ):
               collector.collect(tmp_path, config=None)
               collector.collect(tmp_path, config=None)
           assert collector.grammar_warnings == [_GO_WARNING]

       def test_repeated_get_parser_records_the_warning_once(self) -> None:
           collector = GoAstCollector()
           with patch(
               "nfr_review.collectors.ast_common.make_parser",
               side_effect=ImportError("no module named tree_sitter_go"),
           ):
               assert collector._get_parser() is None
               assert collector._get_parser() is None
           assert collector.grammar_warnings == [_GO_WARNING]


   class TestDockerfileCollectorRecordsWarning:
       """DockerfileCollector doesn't subclass BaseASTCollector (it needs custom
       filename matching, not extension-based globbing), so it duplicates —
       and must independently uphold — the same contract."""

       def test_missing_module_records_warning(self, tmp_path: Path) -> None:
           collector = DockerfileCollector()
           with patch(
               "nfr_review.collectors.dockerfile.make_parser",
               side_effect=ImportError("no module named tree_sitter_dockerfile"),
           ):
               result = collector.collect(tmp_path, config=None)
           assert result == []
           assert collector.grammar_warnings == [_DOCKERFILE_WARNING]

       def test_repeated_collect_records_the_warning_once(self, tmp_path: Path) -> None:
           collector = DockerfileCollector()
           with patch(
               "nfr_review.collectors.dockerfile.make_parser",
               side_effect=ImportError("no module named tree_sitter_dockerfile"),
           ):
               collector.collect(tmp_path, config=None)
               collector.collect(tmp_path, config=None)
           assert collector.grammar_warnings == [_DOCKERFILE_WARNING]


   class TestEngineSurfacesTheWarning:
       """The actual point: does this reach RunResult.warnings, which the CLI
       prints unconditionally (not just under -v)?"""

       def test_missing_grammar_becomes_a_run_warning(self, tmp_path: Path) -> None:
           cregistry: Registry = Registry("collector")
           rregistry: Registry = Registry("rule")
           cregistry.register("dockerfile", DockerfileCollector())

           with patch(
               "nfr_review.collectors.dockerfile.make_parser",
               side_effect=ImportError("no module named tree_sitter_dockerfile"),
           ):
               engine = Engine(collectors=cregistry, rules=rregistry)
               result = engine.run(target=tmp_path, config=Config(tech={}))

           assert result.warnings == [_DOCKERFILE_WARNING]

       def test_run_does_not_abort_despite_the_failure(self, tmp_path: Path) -> None:
           """R012: a collector failure — even a categorical one like a missing
           grammar — must never abort the run."""
           cregistry: Registry = Registry("collector")
           rregistry: Registry = Registry("rule")
           cregistry.register("dockerfile", DockerfileCollector())

           with patch(
               "nfr_review.collectors.dockerfile.make_parser",
               side_effect=ImportError("no module named tree_sitter_dockerfile"),
           ):
               engine = Engine(collectors=cregistry, rules=rregistry)
               result = engine.run(target=tmp_path, config=Config(tech={}))

           assert result.findings == []
           assert result.run_metadata is not None

       @pytest.mark.parametrize("workers", [1, 4])
       def test_repeated_runs_report_the_warning_once_per_run(
           self, tmp_path: Path, workers: int
       ) -> None:
           """The registered collectors are module-level singletons reused by
           every run in the process, so the second run must not repeat the
           first run's warning."""
           cregistry: Registry = Registry("collector")
           rregistry: Registry = Registry("rule")
           cregistry.register("dockerfile", DockerfileCollector())
           cregistry.register("go-ast", GoAstCollector())

           with (
               patch(
                   "nfr_review.collectors.dockerfile.make_parser",
                   side_effect=ImportError("no module named tree_sitter_dockerfile"),
               ),
               patch(
                   "nfr_review.collectors.ast_common.make_parser",
                   side_effect=ImportError("no module named tree_sitter_go"),
               ),
           ):
               engine = Engine(collectors=cregistry, rules=rregistry, workers=workers)
               first = engine.run(target=tmp_path, config=Config(tech={}))
               second = engine.run(target=tmp_path, config=Config(tech={}))

           assert sorted(first.warnings) == sorted([_DOCKERFILE_WARNING, _GO_WARNING])
           assert sorted(second.warnings) == sorted([_DOCKERFILE_WARNING, _GO_WARNING])
   ```

   This renames `TestBaseASTCollectorRaises` / `TestDockerfileCollectorRaises`
   and their `test_raises_with_informative_message` (which only asserted
   `== []`) to `…RecordsWarning` / `test_missing_module_records_warning`, each
   now asserting the exact `grammar_warnings` content (T1), and adds the G3
   repeated-run cases.

2. Run and see it fail:
   `.venv/bin/python -m pytest -n0 tests/test_missing_grammar_warning.py`
   Expected: 5 failed, 4 passed. The failures are
   `test_repeated_collect_records_the_warning_once` (both classes),
   `test_repeated_get_parser_records_the_warning_once`, and both
   `test_repeated_runs_report_the_warning_once_per_run[1]` / `[4]` — each an
   `AssertionError` showing the warning list holding the same message twice
   (or the second run reporting four warnings). The two
   `test_missing_module_records_warning` cases and the two original engine
   cases pass: they lock behaviour that is already correct.

3. Implement.

   a. `src/nfr_review/collectors/ast_common.py`, in `BaseASTCollector._get_parser`,
   replace

   ```python
                   self.grammar_warnings.append(msg)
                   return None
   ```

   with

   ```python
                   if msg not in self.grammar_warnings:
                       self.grammar_warnings.append(msg)
                   return None
   ```

   and in `BaseASTCollector.collect`, replace

   ```python
       def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
           if self._get_parser() is None:
   ```

   with

   ```python
       def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
           # Registered collectors are process-wide singletons: start each run
           # with no warnings so the engine reports only this run's.
           self.grammar_warnings = []
           if self._get_parser() is None:
   ```

   b. `src/nfr_review/collectors/dockerfile.py`, in `DockerfileCollector._get_parser`,
   replace

   ```python
                   self.grammar_warnings.append(msg)
                   return None
   ```

   with

   ```python
                   if msg not in self.grammar_warnings:
                       self.grammar_warnings.append(msg)
                   return None
   ```

   and in `DockerfileCollector.collect`, replace

   ```python
       def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
           if self._get_parser() is None:
   ```

   with

   ```python
       def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
           # Registered at import as a process-wide singleton: start each run
           # with no warnings so the engine reports only this run's.
           self.grammar_warnings = []
           if self._get_parser() is None:
   ```

   `engine.py` is unchanged (it copies the list after `collect()` returns).

4. Run and pass:
   `.venv/bin/python -m pytest -n0 tests/test_missing_grammar_warning.py tests/test_ast_common_collector.py tests/test_dockerfile_collector.py`
   Expected: all pass, none failed.

5. Check (`format`): `ruff format src/nfr_review/collectors/ast_common.py src/nfr_review/collectors/dockerfile.py tests/test_missing_grammar_warning.py`,
   then `pre-commit run --all-files` (`format`) passes.

6. Commit:

   ```sh
   git add src/nfr_review/collectors/ast_common.py src/nfr_review/collectors/dockerfile.py tests/test_missing_grammar_warning.py
   git commit -F - <<'EOF'
   fix(collectors): report each grammar warning once per run

   Registered AST collectors are process-wide singletons and a failed parser
   load is retried on every run, so grammar_warnings grew by one entry per
   run. collect() now starts from an empty list and _get_parser() records a
   message once. The missing-grammar tests named "raises…" asserted only an
   empty result; they now assert the recorded warning for both the
   BaseASTCollector and Dockerfile paths, and the engine is run twice.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S03
   Rows: G3, T1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

## Task 3 — G2 + T1: only a missing grammar module or a failing `getattr(mod, func_name)` counts as "not installed"

**Rows:** G2, T1
**Files:** `tests/test_missing_grammar_warning.py` (extend),
`src/nfr_review/collectors/ast_common.py` (add `GrammarNotInstalledError`, modify `make_parser`, narrow the catch in `BaseASTCollector._get_parser`, extend `__all__`),
`src/nfr_review/collectors/dockerfile.py` (narrow the catch in `DockerfileCollector._get_parser`)
**Consumes:** Task 2's test module and collector code; `tree_sitter_go.language` (core dependency `tree-sitter-go>=0.23`, installed on every platform).
**Produces:** `GrammarNotInstalledError(ImportError)` in `nfr_review.collectors.ast_common`, raised by `make_parser` only when `getattr(mod, func_name)` fails; both `_get_parser` methods catch `ImportError` only.

Steps:

1. Write the failing tests in `tests/test_missing_grammar_warning.py`.

   a. Add to the module docstring, after "…regardless of which platform CI (or
   this environment) runs on.":

   ```text
   The one exception is the Go grammar, a core dependency installed
   everywhere, which the parser-constructor case needs to reach
   ``tree_sitter.Parser``.
   ```

   b. Replace the import block

   ```python
   from pathlib import Path
   from unittest.mock import patch

   import pytest

   from nfr_review.collectors.dockerfile import DockerfileCollector
   ```

   with

   ```python
   import types
   from pathlib import Path
   from unittest.mock import patch

   import pytest
   import tree_sitter
   import tree_sitter_go

   from nfr_review.collectors.dockerfile import DockerfileCollector
   ```

   c. Insert after the `_DOCKERFILE_WARNING = (...)` constant, before
   `class TestBaseASTCollectorRecordsWarning`:

   ```python
   def _placeholder_grammar_module() -> types.ModuleType:
       """A grammar package with no language function, like the 0.0.0a1 placeholder."""
       return types.ModuleType("tree_sitter_placeholder")


   def _raise_attribute_error() -> object:
       raise AttributeError("bug inside the grammar's language()")


   def _buggy_grammar_module() -> types.ModuleType:
       """A grammar package whose language function itself raises AttributeError."""
       mod = types.ModuleType("tree_sitter_buggy")
       mod.language = _raise_attribute_error  # type: ignore[attr-defined]
       return mod


   def _go_backed_grammar_module() -> types.ModuleType:
       """A grammar package that loads fine (backed by the installed Go grammar)."""
       mod = types.ModuleType("tree_sitter_stand_in")
       mod.language = tree_sitter_go.language  # type: ignore[attr-defined]
       return mod


   class TestMakeParser:
       def test_missing_language_function_raises_grammar_not_installed(self) -> None:
           from nfr_review.collectors.ast_common import GrammarNotInstalledError, make_parser

           with patch("importlib.import_module", return_value=_placeholder_grammar_module()):
               with pytest.raises(GrammarNotInstalledError, match="does not provide language"):
                   make_parser("dockerfile")

       def test_grammar_not_installed_is_an_import_error(self) -> None:
           from nfr_review.collectors.ast_common import GrammarNotInstalledError

           assert issubclass(GrammarNotInstalledError, ImportError)

       def test_attribute_error_inside_language_function_propagates(self) -> None:
           from nfr_review.collectors.ast_common import GrammarNotInstalledError, make_parser

           with patch("importlib.import_module", return_value=_buggy_grammar_module()):
               with pytest.raises(AttributeError, match="bug inside") as excinfo:
                   make_parser("dockerfile")
           assert not isinstance(excinfo.value, GrammarNotInstalledError)
   ```

   (`GrammarNotInstalledError` is imported inside each test so the other cases
   in the module still run, and fail on behaviour, before it exists.)

   d. In `class TestBaseASTCollectorRecordsWarning`, insert after
   `test_missing_module_records_warning`:

   ```python
   def test_missing_language_function_records_warning(self, tmp_path: Path) -> None:
       collector = GoAstCollector()
       with patch("importlib.import_module", return_value=_placeholder_grammar_module()):
           result = collector.collect(tmp_path, config=None)
       assert result == []
       assert collector.grammar_warnings == [_GO_WARNING]


   def test_attribute_error_inside_language_function_propagates(self, tmp_path: Path) -> None:
       collector = GoAstCollector()
       with patch("importlib.import_module", return_value=_buggy_grammar_module()):
           with pytest.raises(AttributeError, match="bug inside"):
               collector.collect(tmp_path, config=None)
       assert collector.grammar_warnings == []


   def test_attribute_error_from_parser_constructor_propagates(self, tmp_path: Path) -> None:
       collector = GoAstCollector()
       with patch.object(tree_sitter, "Parser", side_effect=AttributeError("parser ctor bug")):
           with pytest.raises(AttributeError, match="parser ctor bug"):
               collector.collect(tmp_path, config=None)
       assert collector.grammar_warnings == []
   ```

   e. In `class TestDockerfileCollectorRecordsWarning`, insert after
   `test_missing_module_records_warning`:

   ```python
   def test_missing_language_function_records_warning(self, tmp_path: Path) -> None:
       collector = DockerfileCollector()
       with patch("importlib.import_module", return_value=_placeholder_grammar_module()):
           result = collector.collect(tmp_path, config=None)
       assert result == []
       assert collector.grammar_warnings == [_DOCKERFILE_WARNING]


   def test_attribute_error_inside_language_function_propagates(self, tmp_path: Path) -> None:
       collector = DockerfileCollector()
       with patch("importlib.import_module", return_value=_buggy_grammar_module()):
           with pytest.raises(AttributeError, match="bug inside"):
               collector.collect(tmp_path, config=None)
       assert collector.grammar_warnings == []


   def test_attribute_error_from_parser_constructor_propagates(self, tmp_path: Path) -> None:
       collector = DockerfileCollector()
       with (
           patch("importlib.import_module", return_value=_go_backed_grammar_module()),
           patch.object(tree_sitter, "Parser", side_effect=AttributeError("parser ctor bug")),
       ):
           with pytest.raises(AttributeError, match="parser ctor bug"):
               collector.collect(tmp_path, config=None)
       assert collector.grammar_warnings == []
   ```

   (`make_parser` does `import importlib` inside the function and looks up
   `tree_sitter.Parser` at call time, so patching `importlib.import_module` and
   `tree_sitter.Parser` reaches it. The Dockerfile constructor case uses the
   Go-backed stand-in so it does not depend on the Dockerfile grammar being
   installed — after Task 1 it is absent on Intel macOS, Windows and aarch64.)

2. Run and see it fail:
   `.venv/bin/python -m pytest -n0 tests/test_missing_grammar_warning.py`
   Expected: 7 failed, 11 passed. Failures: the three `TestMakeParser` cases
   (each `ImportError: cannot import name 'GrammarNotInstalledError'`), and
   the four collector propagation cases with
   `Failed: DID NOT RAISE <class 'AttributeError'>` because the current catch
   swallows every `AttributeError`. The two
   `test_missing_language_function_records_warning` cases pass now and must
   keep passing (they lock the placeholder path).

3. Implement.

   a. `src/nfr_review/collectors/ast_common.py`: replace the whole
   `make_parser` function

   ```python
   def make_parser(language: str) -> tree_sitter.Parser:
       """Create a tree-sitter Parser for *language* using individual grammar packages."""
       if language not in _GRAMMAR_LOADERS:
           raise ValueError(f"Unsupported tree-sitter language: {language!r}")
       module_name, func_name = _GRAMMAR_LOADERS[language]
       import importlib

       mod = importlib.import_module(module_name)
       lang_ptr = getattr(mod, func_name)()
       lang = tree_sitter.Language(lang_ptr)
       return tree_sitter.Parser(lang)
   ```

   with

   ```python
   class GrammarNotInstalledError(ImportError):
       """The grammar package is installed but does not expose its language function.

       This is what the ``tree-sitter-dockerfile`` 0.0.0a1 placeholder looks like.
       It subclasses ``ImportError`` so one ``except ImportError`` covers both a
       missing package and an empty one, while an ``AttributeError`` raised by a
       real bug in the grammar or in parser construction still propagates.
       """


   def make_parser(language: str) -> tree_sitter.Parser:
       """Create a tree-sitter Parser for *language* using individual grammar packages.

       Raises ``ImportError`` (``ModuleNotFoundError``) when the grammar package is
       absent and ``GrammarNotInstalledError`` when it lacks its language function.
       """
       if language not in _GRAMMAR_LOADERS:
           raise ValueError(f"Unsupported tree-sitter language: {language!r}")
       module_name, func_name = _GRAMMAR_LOADERS[language]
       import importlib

       mod = importlib.import_module(module_name)
       try:
           language_func = getattr(mod, func_name)
       except AttributeError as exc:
           raise GrammarNotInstalledError(
               f"{module_name} does not provide {func_name}()", name=module_name
           ) from exc
       lang = tree_sitter.Language(language_func())
       return tree_sitter.Parser(lang)
   ```

   b. Same file, in `BaseASTCollector._get_parser`, replace

   ```python
               except (ImportError, ModuleNotFoundError, AttributeError):
   ```

   with

   ```python
               except ImportError:  # includes ModuleNotFoundError, GrammarNotInstalledError
   ```

   c. Same file, replace

   ```python
   __all__ = ["BaseASTCollector", "find_nodes", "make_parser", "text"]
   ```

   with

   ```python
   __all__ = ["BaseASTCollector", "GrammarNotInstalledError", "find_nodes", "make_parser", "text"]
   ```

   d. `src/nfr_review/collectors/dockerfile.py`, in `DockerfileCollector._get_parser`,
   replace

   ```python
               except (ImportError, ModuleNotFoundError, AttributeError):
   ```

   with

   ```python
               except ImportError:  # includes ModuleNotFoundError, GrammarNotInstalledError
   ```

   The existing `tests/test_ast_common_collector.py::test_make_parser_grammar_not_installed`
   (patches `importlib.import_module` to raise `ImportError("no module")` and
   expects `ImportError`) keeps passing: the import is not wrapped.

4. Run and pass:
   `.venv/bin/python -m pytest -n0 tests/test_missing_grammar_warning.py tests/test_ast_common_collector.py tests/test_dockerfile_collector.py tests/test_cross_artifact_rules.py`
   Expected: all pass (18 in `test_missing_grammar_warning.py`), none failed.

5. Check (`format`): `ruff format src/nfr_review/collectors/ast_common.py src/nfr_review/collectors/dockerfile.py tests/test_missing_grammar_warning.py`,
   then `pre-commit run --all-files` passes (this includes mypy over `src/`).

6. Commit:

   ```sh
   git add src/nfr_review/collectors/ast_common.py src/nfr_review/collectors/dockerfile.py tests/test_missing_grammar_warning.py
   git commit -F - <<'EOF'
   fix(collectors): treat only a missing grammar as "not installed"

   AttributeError had been added to the grammar-missing catch so the empty
   tree-sitter-dockerfile placeholder would warn instead of crash, but that
   also hid any AttributeError raised inside a grammar's language function or
   parser construction. make_parser now converts only a failing
   getattr(mod, func_name) into GrammarNotInstalledError (an ImportError), and
   the collectors catch ImportError alone.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S03
   Rows: G2, T1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

## Task 4 — Slice gate and evidence

**Rows:** G1, G2, G3, T1 (verification only)
**Files:** `docs/plans/pr255-remediation/evidence/M001-S03.md` (create)
**Consumes:** Tasks 1–3 committed; `/tmp/m001-s03-g1-dry-run.txt` from Task 1.
**Produces:** the evidence file for M001/S03.

Steps:

1. Confirm no stale catch remains:
   `grep -n "AttributeError" src/nfr_review/collectors/ast_common.py src/nfr_review/collectors/dockerfile.py`
   Expected: only the `except AttributeError as exc:` around `getattr` in
   `make_parser` and the `GrammarNotInstalledError` docstring.

2. Run `format`: `pre-commit run --all-files`. Expected: all hooks pass.

3. Run `unit`: `python -m pytest -n auto -m "not regression" tests/`.
   Expected: no failures.

4. Run `gate`:
   `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`.
   Expected: no failures. If only `tests/regression/test_snapshots.py::test_regression_snapshot[httpx]`
   and `[gin]` fail with `dep-freshness` "no release in N months" findings,
   that is the pre-existing drift noted above, not an S03 regression: record
   it and stop for the owner rather than refreshing snapshots here.

5. Write `docs/plans/pr255-remediation/evidence/M001-S03.md` with: one line per
   row naming the test that verifies it — G1 →
   `tests/test_pyproject_dependencies.py` plus the contents of
   `/tmp/m001-s03-g1-dry-run.txt` in a fenced block; G2 → the six
   `*propagates*` / `*raises_grammar_not_installed*` cases in
   `tests/test_missing_grammar_warning.py`; G3 →
   `TestEngineSurfacesTheWarning::test_repeated_runs_report_the_warning_once_per_run`;
   T1 → the `*records_warning` cases — then the pass/fail counts printed by
   `format`, `unit` and `gate` and the date.

6. Commit:

   ```sh
   git add docs/plans/pr255-remediation/evidence/M001-S03.md
   git commit -F - <<'EOF'
   docs(plans): record M001/S03 evidence

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S03
   Rows: G1, G2, G3, T1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```
