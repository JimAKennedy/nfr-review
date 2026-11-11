# M001/S07 implementation plan — Scan scope

**Slice:** M001/S07 — Scan scope
**Ledger:** docs/plans/pr255-remediation/ledger.md
**Branch:** pr255-fixes
**Rows:** C1, C2


> **Evidence rule (ledger standard):** evidence is appended per task as it lands and never names a commit SHA; the commits are found with `git log --grep="Slice: M001/S07"`. Earlier wording in this plan that asked for SHAs was removed on 2026-11-11 before execution.

## Task status

- [x] Task 1 — C1: thread `exclude_test_paths` into config-integration discovery
- [x] Task 2 — C2: prune excluded directories during detection
- [ ] Task 3 — Slice gate and evidence

## Definition of Done

Copied verbatim from the ledger slice:

- [ ] Config-integration discovery honours the configured test-path exclusion
- [ ] Detection does not descend into `node_modules`, `target` or other excluded directories

## Validation

Tokens from `.jk/validations.yml`, expanded. Run every command from the
worktree root with the project venv active (`source .venv/bin/activate`), so
`python` is `.venv/bin/python`.

1. `format` → `pre-commit run --all-files`
2. `unit` → `python -m pytest -n auto -m "not regression" tests/`
3. `regression` → `python -m pytest -n auto -m regression --timeout=600 tests/regression`
4. `gate` →
   `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`

After writing or modifying any `.py` file, run `.venv/bin/ruff format <file>`
on it before committing (CLAUDE.md "Auto-Mode Code Quality").

## Code facts this plan relies on

Verified against `pr255-fixes` at `2a3300b`. I applied every code block
below to a scratch copy of the tree and ran it there. Each new test failed on
the unmodified tree with the failure quoted in its task and passed with the
change. ruff check and ruff format were clean.

- **No config reaches `arch_integrations.py`.** This contradicts the design
  premise "pass it from the config it has access to".
  - `discover_integrations(repo_path, components, repo_name)` runs every
    entry of `_STRATEGIES` (typed
    `StrategyFn = Callable[[Path, list[Component], str], list[IntegrationPoint]]`)
    with three positional arguments.
  - `discover_integrations_multi_repo` calls it once per repo.
  - Its only callers are `arch_orchestrator._discover_arch_artifacts`, which
    `run_arch_review` calls. That function takes no config and no exclusion
    flag.
  - `run_arch_review` has two callers in `cli.py`: `arch_cmd`, which has no
    `--exclude-tests` option and loads no config, and `_execute_all_pipelines`
    for `nfr-review all`. The latter has `exclude_tests: bool` from its
    `--exclude-tests/--include-tests` option (default exclude) but only
    passes it to `run_report_pipeline`.

  So the plan threads a keyword-only `exclude_test_paths: bool = True` from
  `run_arch_review` down to `discover_config_integrations`, and wires `all`'s
  existing flag into it. `arch_cmd` keeps the default, which is current
  behaviour. Giving `arch` its own `--include-tests` flag would be a CLI
  interface change and is not in this slice.
- `discover_config_integrations(..., *, exclude_test_paths: bool = True)`
  already exists in `arch_integ_config.py` (from `e9fdfc6`). It applies
  `should_exclude_path(rel_path, exclude_test_paths=exclude_test_paths)`.
  `src/test/resources/application.yml` is a test path, because
  `_TEST_PATH_PATTERNS` matches `(^|/)tests?/`.
- `_STRATEGIES` holds the imported function object
  `discover_config_integrations`, so an identity check selects it.
  `tests/test_arch_integ_manifest.py` reads only the strategy names.
- `detect._safe_rglob(base, pattern)` runs `list(base.rglob(pattern))` and
  only then filters with `should_exclude_path(rel)`. That filter uses the
  default `exclude_test_paths=True` and `_ALWAYS_SKIP_DIRS`, which are `.git
  .hg .svn .gsd .venv venv __pycache__ .mypy_cache .pytest_cache .ruff_cache
  .tox node_modules .regression-repos`. `target` is not in that set, so
  detection today both walks and **counts** files under `target/`.
- Every `_safe_rglob` caller passes a single-component name pattern:
  - `pom.xml`, `build.gradle`, `build.gradle.kts`, `*.java`;
  - `application.yml`/`.yaml`/`.properties`, `kustomization.yaml`, `*.xml`;
  - `*.Dockerfile`, `Dockerfile`, `dockerfile`;
  - `*.proto`, `go.mod`, `Cargo.toml`;
  - `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements.txt`, `*.py`;
  - `package.json`, `*.csproj`, `*.sln`, `*.yaml`;
  - `*otel*collector*config*`, `*otelcol*`, `Chart.yaml`, `*.tf`, `skaffold.yaml`;
  - `*.vcxproj`, `conanfile.txt`, `conanfile.py`, `vcpkg.json`, `*.cpp`, `*.cc`, `*.cxx`.

  Callers use the result as a bool, iterate it, or read `path.parent` /
  `path.suffix`. Python 3.11 `rglob` matches files **and** directories by
  name, case-sensitively on POSIX, does not descend into symlinked
  directories, and does match dot-files. `os.walk` (default
  `followlinks=False`) with `fnmatch.fnmatch` on each name (case-sensitive on
  POSIX, case-insensitive on Windows, like pathlib) reproduces this. The new
  walk matches both `dirnames` (after pruning) and `filenames`.
- `collectors/ast_common._HIDDEN_DIRS` is `.git .svn .hg .idea .vscode
  node_modules __pycache__ .mypy_cache`. Every entry either starts with `.`
  or is in `path_filter.ALWAYS_SKIP_DIRS`. Pruning every dot-directory plus
  `ALWAYS_SKIP_DIRS | {"target"}` therefore covers it. `detect.py` does not
  need to import `ast_common`, which would pull `tree_sitter` into the CLI's
  import path.
- **Behaviour change (intended): detection now prunes every dot-directory and
  `target/`.** A repo whose only `*.py` is in `.github/scripts/`, or whose
  only `Dockerfile` is in `.devcontainer/`, no longer detects python or
  dockerfile. This matches the AST collectors, which already skip
  dot-directories. `_detect_ci` is unaffected because it checks
  `.github/workflows` with `_safe_is_dir`/`_safe_glob`, not `_safe_rglob`.
  `_safe_glob(d, "**/*.yaml")` in `_detect_kubernetes` (only under
  `k8s/`, `kubernetes/`, `deploy/`, … prefixes) is not changed by this slice.
- Error handling: today any `OSError` from `rglob` returns `[]`, and Python
  3.11's `rglob` already ignores `PermissionError` on unreadable
  subdirectories. `os.walk` with `onerror=None` likewise skips unreadable
  directories. The new `_safe_rglob` keeps `try/except OSError: return []`
  around the walk.
- The full unit suite plus the regression snapshots ran with the new
  `_safe_rglob` in place. Only `test_regression_snapshot[gin]` and
  `test_regression_snapshot[httpx]` failed, and they fail identically on
  the unmodified tree: `+2` / `+1` `dep-freshness` findings, a time-based
  drift that this slice did not cause. No other snapshot, including the
  `.dsl` arch snapshots, changed. C1's default is unchanged, so arch output
  is identical.

---

## Task 1 — C1: thread `exclude_test_paths` into config-integration discovery

**Rows:** C1
**Files:**
- Modify `src/nfr_review/arch_integrations.py`
- Modify `src/nfr_review/arch_orchestrator.py`
- Modify `src/nfr_review/cli.py`
- Modify `tests/test_arch_integrations.py`
- Modify `tests/test_arch_orchestrator.py`

**Consumes:** `discover_config_integrations(..., exclude_test_paths=)`, `_STRATEGIES`,
`_discover_arch_artifacts`, `run_arch_review`, `_execute_all_pipelines`.
**Produces:**
- keyword-only `exclude_test_paths: bool = True` on `discover_integrations`,
  `discover_integrations_multi_repo` and `_discover_arch_artifacts`;
- keyword `exclude_test_paths: bool = True` on `run_arch_review`;
- `nfr-review all --include-tests` reaches config-integration discovery.

### Steps

1. Append to `tests/test_arch_integrations.py`:

   ```python
   # ---------------------------------------------------------------------------
   # Test-path exclusion for config-integration discovery
   # ---------------------------------------------------------------------------


   def _write_test_path_config(repo: Path) -> None:
       """A Redis URL that only appears in a test resource file."""
       cfg_dir = repo / "src" / "test" / "resources"
       cfg_dir.mkdir(parents=True)
       (cfg_dir / "application.yml").write_text(
           "spring:\n  redis:\n    url: redis://test-cache:6379\n"
       )


   class TestConfigIntegrationTestPathExclusion:
       def test_test_path_config_skipped_by_default(self, tmp_repo: Path) -> None:
           _write_test_path_config(tmp_repo)
           components = [_make_component("myapp", boundary_path=".")]

           integrations = discover_integrations(tmp_repo, components)

           assert [i for i in integrations if i.protocol == "redis"] == []

       def test_test_path_config_discovered_when_exclusion_off(self, tmp_repo: Path) -> None:
           _write_test_path_config(tmp_repo)
           components = [_make_component("myapp", boundary_path=".")]

           integrations = discover_integrations(tmp_repo, components, exclude_test_paths=False)

           assert len([i for i in integrations if i.protocol == "redis"]) == 1

       def test_multi_repo_passes_exclusion_through(self, tmp_path: Path) -> None:
           repo_a = tmp_path / "repo-a"
           repo_b = tmp_path / "repo-b"
           for repo in (repo_a, repo_b):
               (repo / ".git").mkdir(parents=True)
           _write_test_path_config(repo_a)
           components = [
               _make_component("svc-a", repo="repo-a", boundary_path="."),
               _make_component("svc-b", repo="repo-b", boundary_path="."),
           ]

           default = discover_integrations_multi_repo(
               [repo_a, repo_b], components, ["repo-a", "repo-b"]
           )
           included = discover_integrations_multi_repo(
               [repo_a, repo_b], components, ["repo-a", "repo-b"], exclude_test_paths=False
           )

           assert [i for i in default if i.protocol == "redis"] == []
           assert len([i for i in included if i.protocol == "redis"]) == 1
   ```

2. In `tests/test_arch_orchestrator.py`, add
   `from unittest.mock import MagicMock, patch` after `from pathlib import Path`,
   and append:

   ```python
   class TestArchTestPathExclusion:
       """``exclude_test_paths`` reaches config-integration discovery."""

       @staticmethod
       def _repo_with_test_config(root: Path) -> Path:
           cfg_dir = root / "src" / "test" / "resources"
           cfg_dir.mkdir(parents=True)
           (cfg_dir / "application.yml").write_text(
               "spring:\n  redis:\n    url: redis://test-cache:6379\n"
           )
           (root / "pyproject.toml").write_text('[project]\nname = "s"\nversion = "0.1.0"\n')
           return root

       def test_default_excludes_test_path_config(self, tmp_path: Path) -> None:
           repo = self._repo_with_test_config(tmp_path)
           report = run_arch_review([repo], skip_llm=True)
           assert [i for i in report.integration_points if i.protocol == "redis"] == []

       def test_exclusion_off_discovers_test_path_config(self, tmp_path: Path) -> None:
           repo = self._repo_with_test_config(tmp_path)
           report = run_arch_review([repo], skip_llm=True, exclude_test_paths=False)
           assert len([i for i in report.integration_points if i.protocol == "redis"]) == 1

       def test_all_command_include_tests_reaches_arch_review(self, tmp_path: Path) -> None:
           from nfr_review.cli import _execute_all_pipelines

           with (
               patch("nfr_review.arch_orchestrator.run_arch_review") as arch,
               patch("nfr_review.arch_report_render.render_arch_report", return_value={}),
               patch("nfr_review.cli.run_report_pipeline", return_value=MagicMock()),
           ):
               _execute_all_pipelines(
                   target_list=[tmp_path],
                   repo_names=["repo"],
                   timestamp="20260101-000000",
                   output_dir=tmp_path / "out",
                   config_path=None,
                   no_arch=False,
                   no_tests=True,
                   no_deps=True,
                   no_diagrams=True,
                   no_pdf=True,
                   no_summary=True,
                   test_timeout=1,
                   no_score=True,
                   max_resolve_rounds=None,
                   no_llm=True,
                   diagram_mode="hierarchical",
                   exclude_tests=False,
                   workers=1,
                   quiet=True,
               )

           assert arch.call_args.kwargs["exclude_test_paths"] is False
   ```

   (`_run_arch` imports `run_arch_review` and `render_arch_report` inside the
   function, so patching them at their source modules takes effect.)

3. Run and see it fail:
   `.venv/bin/python -m pytest tests/test_arch_integrations.py::TestConfigIntegrationTestPathExclusion tests/test_arch_orchestrator.py::TestArchTestPathExclusion -q`
   → 4 failed, 2 passed:
   - `TypeError: discover_integrations() got an unexpected keyword argument 'exclude_test_paths'`
   - `TypeError: discover_integrations_multi_repo() got an unexpected keyword argument 'exclude_test_paths'`
   - `TypeError: run_arch_review() got an unexpected keyword argument 'exclude_test_paths'`
   - `KeyError: 'exclude_test_paths'` (the `all` wiring test)

   The two default-exclusion tests pass before and after. They lock the
   default.

4. In `src/nfr_review/arch_integrations.py`:
   - add `import functools` above `import logging`;
   - `discover_integrations`: add `*, exclude_test_paths: bool = True,` after
     `repo_name: str | None = None,`. Add a docstring entry after `repo_name:`:

     ```
         exclude_test_paths:
             Skip config files under test paths when scanning for connection
             strings (``--exclude-tests``, the default).
     ```

     Replace the strategy loop body with:

     ```python
     for strategy_name, strategy_fn in _STRATEGIES:
         fn: StrategyFn = strategy_fn
         if strategy_fn is discover_config_integrations:
             fn = functools.partial(
                 discover_config_integrations, exclude_test_paths=exclude_test_paths
             )
         try:
             all_integrations.extend(fn(repo_path, components, effective_name))
         except Exception:  # noqa: BLE001
             logger.warning("Strategy %s failed for %s", strategy_name, repo_path, exc_info=True)
     ```

   - `discover_integrations_multi_repo`: add `*, exclude_test_paths: bool = True,`
     after `repo_names: list[str] | None = None,`. Add a docstring entry
     `exclude_test_paths:` / `Passed through to :func:`discover_integrations` for each repository.`
     Change the per-repo call to:

     ```python
             intgs = discover_integrations(
                 repo_path, all_components, repo_name=name, exclude_test_paths=exclude_test_paths
             )
     ```

5. In `src/nfr_review/arch_orchestrator.py`:
   - `_discover_arch_artifacts`: add `*, exclude_test_paths: bool = True,`
     after `cb: ProgressCallback,`. Change the two integration calls to:

     ```python
         if multi:
             integrations = discover_integrations_multi_repo(
                 targets, components, repo_names, exclude_test_paths=exclude_test_paths
             )
         else:
             integrations = discover_integrations(
                 targets[0],
                 components,
                 repo_name=repo_names[0],
                 exclude_test_paths=exclude_test_paths,
             )
     ```

   - `run_arch_review`: add `exclude_test_paths: bool = True,` after
     `progress: ProgressCallback | None = None,` (the signature is already
     keyword-only after `targets`). Add a docstring entry after `progress:`:

     ```
         exclude_test_paths:
             Skip config files under test paths during integration discovery
             (the ``--exclude-tests`` default).
     ```

     Change the discovery call to:

     ```python
         components, integrations = _discover_arch_artifacts(
             targets, repo_names, multi, cb, exclude_test_paths=exclude_test_paths
         )
     ```

6. In `src/nfr_review/cli.py`, inside `_execute_all_pipelines._run_arch`, add
   `exclude_test_paths=exclude_tests,` as the last argument of the
   `run_arch_review(...)` call. That call is the one with
   `progress=lambda msg: _ts_echo(msg, quiet=quiet),` and no `evidence=`.
   Leave the `arch_cmd` call unchanged.

7. Run and see it pass:
   `.venv/bin/python -m pytest -n auto tests/test_arch_integrations.py tests/test_arch_orchestrator.py tests/test_arch_integ_manifest.py tests/test_arch_drum_validation.py -q`
   → 0 failed.

8. `.venv/bin/ruff format src/nfr_review/arch_integrations.py src/nfr_review/arch_orchestrator.py src/nfr_review/cli.py tests/test_arch_integrations.py tests/test_arch_orchestrator.py`, then commit:

   ```
   git add src/nfr_review/arch_integrations.py src/nfr_review/arch_orchestrator.py \
     src/nfr_review/cli.py tests/test_arch_integrations.py tests/test_arch_orchestrator.py
   git commit -F - <<'EOF'
   fix(arch): honour test-path exclusion in config-integration discovery

   discover_config_integrations gained exclude_test_paths but nothing
   passed it, and no config reached the arch pipeline at all. Thread a
   keyword exclude_test_paths (default True, the existing behaviour) from
   run_arch_review through _discover_arch_artifacts and
   discover_integrations[_multi_repo] to the config strategy, and pass
   `nfr-review all`'s --exclude-tests/--include-tests value into it.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S07
   Rows: C1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

9. Check (`unit`, scoped): `.venv/bin/python -m pytest -n auto tests/ -k "arch" -q` → 0 failed.

---

## Task 2 — C2: prune excluded directories during detection

**Rows:** C2
**Files:**
- Modify `src/nfr_review/detect.py`
- Modify `tests/test_detect.py`

**Consumes:** `path_filter.ALWAYS_SKIP_DIRS`, `should_exclude_path`, and every
`_detect_*` caller of `_safe_rglob`.
**Produces:** `_PRUNED_DIR_NAMES`, `_is_pruned_dir(name, rel_dir) -> bool`,
and an `os.walk`-based `_safe_rglob(base, pattern) -> list[Path]` with the
same signature.

### Steps

1. Append to `tests/test_detect.py`, which already imports `os`, `Path`,
   `pytest` and `detect_technologies`:

   ```python
   class TestDetectionPruning:
       """Detection never lists excluded directories, it does not just filter them."""

       def test_excluded_directories_are_never_listed(
           self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           (tmp_path / "src").mkdir()
           (tmp_path / "src" / "main.py").write_text("x = 1\n")
           excluded = ("node_modules", "target", ".git", ".venv", "tests")
           for top in excluded:
               nested = tmp_path / top / "pkg" / "deep"
               nested.mkdir(parents=True)
               (nested / "Cargo.toml").write_text("[package]\nname = 'decoy'\n")

           listed: list[str] = []
           real_scandir = os.scandir

           def recording_scandir(path: str | os.PathLike[str] = ".") -> object:
               listed.append(Path(os.path.relpath(path, tmp_path)).as_posix())
               return real_scandir(path)

           monkeypatch.setattr(os, "scandir", recording_scandir)
           result = detect_technologies(tmp_path)
           monkeypatch.undo()

           entered = {p for p in listed if p.split("/")[0] in excluded}
           assert entered == set()
           assert "src" in listed
           assert result["python"] is True
           assert result["rust"] is False

       def test_glob_patterns_still_match_names(self, tmp_path: Path) -> None:
           (tmp_path / "svc" / "docker").mkdir(parents=True)
           (tmp_path / "svc" / "docker" / "api.Dockerfile").write_text("FROM scratch\n")
           (tmp_path / "crates" / "core").mkdir(parents=True)
           (tmp_path / "crates" / "core" / "Cargo.toml").write_text("[package]\n")

           result = detect_technologies(tmp_path)

           assert result["dockerfile"] is True
           assert result["rust"] is True
   ```

   Both Python 3.11's `pathlib` `rglob` and `os.walk` list directories
   through `os.scandir`, looked up as a module attribute at call time. So the
   spy records every directory either implementation opens, deterministically
   and without depending on permissions. `result["rust"] is False` also locks
   that a `Cargo.toml` under `target/` no longer counts. Today it does.

2. Run and see it fail:
   `.venv/bin/python -m pytest tests/test_detect.py -k TestDetectionPruning -q`
   → 1 failed, 1 passed. The failure is
   `AssertionError: assert {'.git', '.git/pkg', ..., 'node_modules/pkg/deep', 'tests', ...} == set()`.
   The glob-semantics test is a guard and passes before and after.

3. In `src/nfr_review/detect.py`:
   - change the imports to:

     ```python
     import fnmatch
     import logging
     import os
     from collections.abc import Callable
     from pathlib import Path

     from nfr_review.arch_utils import safe_read_text as _safe_read_text
     from nfr_review.path_filter import ALWAYS_SKIP_DIRS, should_exclude_path
     ```

   - replace the whole `def _safe_rglob(...)` function with:

     ```python
     # Directories detection never descends into: the always-skipped set (VCS
     # metadata, virtualenvs, caches, node_modules) plus build output.  Any
     # directory whose name starts with "." is pruned as well, matching the AST
     # collectors' hidden-directory rule.
     _PRUNED_DIR_NAMES: frozenset[str] = ALWAYS_SKIP_DIRS | {"target"}


     def _is_pruned_dir(name: str, rel_dir: str) -> bool:
         """Return True if the directory *name* at *rel_dir* must not be walked."""
         return (
             name.startswith(".") or name in _PRUNED_DIR_NAMES or should_exclude_path(f"{rel_dir}/")
         )


     def _safe_rglob(base: Path, pattern: str) -> list[Path]:
         """Return paths under *base* whose name matches the glob *pattern*.

         Matches what ``base.rglob(pattern)`` returns for a single-component
         pattern, minus excluded paths, but prunes hidden, always-skipped,
         ``target`` and test directories during the walk so they are never listed.
         Unreadable directories are skipped; any other ``OSError`` yields ``[]``.
         """
         matches: list[Path] = []
         try:
             for dirpath, dirnames, filenames in os.walk(base):
                 current = Path(dirpath)
                 rel = current.relative_to(base).as_posix()
                 prefix = "" if rel == "." else f"{rel}/"
                 dirnames[:] = sorted(d for d in dirnames if not _is_pruned_dir(d, f"{prefix}{d}"))
                 for name in (*dirnames, *sorted(filenames)):
                     if fnmatch.fnmatch(name, pattern) and not should_exclude_path(
                         f"{prefix}{name}"
                     ):
                         matches.append(current / name)
         except OSError:
             return []
         return matches
     ```

   `should_exclude_path(f"{rel_dir}/")` prunes test directories (`tests/`,
   `test/`, `__tests__/`, `spec/`) whole. The per-name
   `should_exclude_path` call still drops test *files* such as
   `test_x.py`, `FooTest.java` and `*.spec.ts`, as the old post-filter did.

4. Run and see it pass:
   `.venv/bin/python -m pytest -n auto tests/test_detect.py -q` → 0 failed
   (82 existing + 2 new in the scratch run).

5. Run the detection-dependent suites:
   `.venv/bin/python -m pytest -n auto -m "not regression" tests/ -q` → 0 failed.
   Then run `regression`:
   `python -m pytest -n auto -m regression --timeout=600 tests/regression`.
   - If a snapshot other than the pre-existing `gin`/`httpx` `dep-freshness`
     drift changes, it is caused by this task's pruning (hidden dirs or
     `target/`). Inspect the diff to confirm it is that, then refresh only that
     repo:
     `python -m pytest -n auto -m regression --timeout=600 tests/regression --update-snapshots -k "<repo-name>"`.
     `git add` the refreshed `tests/regression/snapshots/` files and include
     them in this task's commit.
   - Do not refresh `gin`/`httpx` for the `dep-freshness` drift. It predates
     this slice (see Task 3).

6. `.venv/bin/ruff format src/nfr_review/detect.py tests/test_detect.py`, then commit:

   ```
   git add src/nfr_review/detect.py tests/test_detect.py
   git commit -F - <<'EOF'
   perf(detect): prune excluded directories instead of filtering after rglob

   _safe_rglob listed every directory, node_modules and target included,
   and only then dropped excluded paths. It now walks with os.walk and
   prunes dot-directories, the always-skipped set, target/ and test
   directories in place, keeping rglob's single-name glob semantics and
   the per-file exclusion. A Cargo.toml or pom.xml under target/ no
   longer counts towards detection.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S07
   Rows: C2

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

   If step 5 refreshed snapshots, add them to the same `git add` and add a
   line to the body naming the refreshed repos.

7. Check (`unit` + `regression`): step 5's two commands. The first has 0
   failed. The second introduces no mismatch beyond the pre-existing
   `gin`/`httpx` drift.

---

## Task 3 — Slice gate and evidence

**Rows:** C1, C2
**Files:** create `docs/plans/pr255-remediation/evidence/M001-S07.md`
**Consumes:** the Task 1–2 commits.
**Produces:** the slice's evidence record.

### Steps

1. `format`: `pre-commit run --all-files`. Expect every hook, mypy included,
   to pass. If a hook rewrites a file, re-stage it and amend it into the
   commit that last touched the file, then re-run until clean.
2. `unit`: `python -m pytest -n auto -m "not regression" tests/` → 0 failed.
3. `regression`: `python -m pytest -n auto -m regression --timeout=600 tests/regression`.
   Expect no mismatch other than the pre-existing `gin` (+2) and `httpx` (+1)
   `dep-freshness` drift, which fails identically on `2a3300b`. Do not
   refresh that drift here. Record it and report it to the caller as a gate
   blocker outside this slice.
4. `gate`: `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`.
   It goes green only once the pre-existing drift is resolved. Record the
   result either way.
5. Write `docs/plans/pr255-remediation/evidence/M001-S07.md` in the layout of
   `evidence/M001-S01.md`:
   - heading `# Evidence — M001/S07`, section `## M001/S07 — Scan scope`;
   - the locking tests: `TestConfigIntegrationTestPathExclusion`,
     `TestArchTestPathExclusion` and `TestDetectionPruning`;
   - the observed `format` / `unit` / `regression` / `gate` results, with
     counts copied from the output;
   - a note that `nfr-review arch` has no `--include-tests` flag and keeps the
     default exclusion, and that detection now also prunes dot-directories and
     `target/`;
   - the date.

   Record only identifiers that appear in command output.
6. Commit:

   ```
   git add docs/plans/pr255-remediation/evidence/M001-S07.md
   git commit -F - <<'EOF'
   docs(plans): record M001/S07 evidence

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S07
   Rows: C1, C2

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

7. Check (`gate`): the step 4 run on the head commit, with its outcome recorded.

---

## Self-review

- **DoD coverage:**
  - DoD 1 (config-integration discovery honours the configured test-path
    exclusion) → Task 1. `TestConfigIntegrationTestPathExclusion` covers the
    single-repo off/default cases and multi-repo pass-through.
    `TestArchTestPathExclusion` covers `run_arch_review` and the
    `nfr-review all --include-tests` wiring.
  - DoD 2 (detection never descends into `node_modules`, `target` or other
    excluded directories) → Task 2
    `test_excluded_directories_are_never_listed`, which covers
    `node_modules`, `target`, `.git`, `.venv` and `tests`. Glob semantics are
    guarded by `test_glob_patterns_still_match_names` and the existing 82
    `test_detect.py` cases.
- **Row coverage:**
  - C1 "Case in `tests/test_arch_integrations.py` with exclusion off,
    asserting a test-path integration is discovered" → Task 1 step 1,
    `test_test_path_config_discovered_when_exclusion_off`.
  - C2 "Case in `tests/test_detect.py` asserting excluded directories are
    never listed" → Task 2 step 1, `test_excluded_directories_are_never_listed`.
  - Evidence for both → Task 3.
- **Placeholder scan:** no TBD/TODO. `<SHA>` appears only in Task 3 as an
  instruction to copy from `git log` output. `<repo-name>` in Task 2 step 5
  is the manifest name of whichever snapshot the executor observes changing,
  and is used only if one does.
- **Name consistency:** defined by this plan: the `exclude_test_paths`
  keyword on `discover_integrations`, `discover_integrations_multi_repo`,
  `_discover_arch_artifacts` and `run_arch_review`; `_PRUNED_DIR_NAMES`;
  `_is_pruned_dir`; `_write_test_path_config`; the three test classes.
  Already exist: `discover_config_integrations`, `StrategyFn`,
  `_STRATEGIES`, `ALWAYS_SKIP_DIRS`, `should_exclude_path`,
  `_execute_all_pipelines`, `run_report_pipeline`, `render_arch_report`,
  `_make_component`, the `tmp_repo` fixture, `detect_technologies`.
