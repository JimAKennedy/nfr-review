# M001/S04 plan — Graphify opt-in and out of tree

**Slice:** M001/S04 — Graphify opt-in and out of tree
**Ledger:** `docs/plans/pr255-remediation/ledger.md` (row GR1)
**Design:** [M001-S04-design.md](M001-S04-design.md) (approved 2026-11-10)
**Branch:** `pr255-fixes`

## Task status

- [ ] Task 1 — `graphify.enabled` opt-in; graphify output in a temp dir; `graph_path` read
- [ ] Task 2 — `RunResult.failed_collectors` and `nfr-review run --strict-collectors`
- [ ] Task 3 — Container E2E runs with `--strict-collectors` (CI, `ci-complete`, `.jk/validations.yml`)
- [ ] Task 4 — Regression snapshots refreshed without graphify findings; full gate

## Definition of Done

- [ ] A scan with default config never invokes the `graphify` executable
- [ ] With graphify enabled, its output is written to a temp dir and nothing is written into the scanned repo
- [ ] A stale `graph.json` in the scanned repo is not reused
- [ ] The Container E2E job fails when any collector crashes, and passes on the `:ro` fixture mount

## Validation

Tokens owed: `format`, `unit`, `regression`, `container-e2e`, `gate`. Run them
from the worktree root with the project venv first on `PATH`
(`source .venv/bin/activate`), so `python`, `pre-commit` and `nfr-review`
resolve to `.venv/bin/`.

- `format` → `pre-commit run --all-files`
- `unit` → `python -m pytest -n auto -m "not regression" tests/`
- `regression` → `python -m pytest -n auto -m regression --timeout=600 tests/regression`
- `container-e2e` (as edited by Task 3) →
  `podman build --platform linux/amd64 -t nfr-review:e2e-test . && podman run --rm --platform linux/amd64 --entrypoint sh -v "$PWD/tests/fixtures/cpp-integration-repo:/repo:ro" -w /repo nfr-review:e2e-test -c 'nfr-review run --strict-collectors --score --csv /tmp/out.csv --jsonl /tmp/out.jsonl .'`
- `gate` → `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`

Note: the `unit` command as written in `.jk/validations.yml` does not pass
`-m "not regression"`, so it also collects `tests/regression`. That is the
token as defined; this slice does not change it.

## Code facts this plan relies on

- `src/nfr_review/collectors/graphify.py::_run_graphify(repo_path)` returns
  `repo_path/graphify-out/graph.json` whenever that file exists (stale reuse),
  otherwise runs `graphify update <repo> --no-cluster` and
  `graphify cluster-only <repo> --no-viz --no-label` with no `env`/`cwd`, so
  graphify writes into `<repo>/graphify-out/`. `GraphifyCollector.collect`
  ignores `config` entirely.
- graphify 0.9.97 (`.venv/lib/python3.11/site-packages/graphify/paths.py`)
  reads `GRAPHIFY_OUT` once at import; an absolute value is honoured
  (`cache.cache_dir`: `base = _out if _out.is_absolute() else root / _out`;
  `Path(repo) / "/abs/graphify-out"` is the absolute path).
  `cluster-only --graph P` writes its outputs beside `P` when `P.parent.name`
  equals `Path(GRAPHIFY_OUT).name`, so the out dir must be named
  `graphify-out`. Verified by hand: with
  `GRAPHIFY_OUT=<tmp>/graphify-out`, `update` and `cluster-only --graph` on a
  `chmod -R a-w` repo both exit 0 in about 1 s and every file lands under
  `<tmp>/graphify-out/`.
- `Engine._run_one_collector` (`src/nfr_review/engine.py`) turns any exception
  from `collect` into the string `collector <name> failed: <exc>`, appended to
  `warnings`; the collector's name is then absent from the `succeeded` set
  returned by `_run_collection_phase`. Grammar warnings are appended to
  `warnings` from successful collectors and never affect `succeeded`.
- `RunResult` is a plain `@dataclass` (not Pydantic). Nothing serialises it
  wholesale: JSONL/CSV/SARIF writers read `findings`, `rule_results`,
  `run_metadata`; `warnings` is only printed by `_print_collector_warnings`.
  A new field therefore has no JSONL or snapshot impact.
- `cli._with_findings` rebuilds `RunResult(...)` field by field; any new field
  is silently dropped by `_apply_suppressions`, `_apply_baseline_filter` and
  `_apply_optional_filters` unless `_with_findings` is changed.
- No other module reads `<repo>/graphify-out`: `mcp_client`, `graph_query`,
  `output/summarize.py`, `output/markdown.py`, `scoring.py` consume the
  `graphify-analysis` evidence or a caller-supplied `graph_path`;
  `create_graph_client` has no caller in `src/`.
- `tests/regression/test_graphify_selfscan.py` calls
  `GraphifyCollector().collect(REPO_ROOT, None)` and depends on reuse of
  `REPO_ROOT/graphify-out/graph.json`; with the default now disabled it would
  get `[]` and fail, so Task 1 rewrites its fixture.
- The 14 JSONL snapshots in `tests/regression/snapshots/` hold 304
  `structure-*` findings (66 `structure-coupling-cluster`, 131
  `structure-god-node`, 107 `structure-weak-boundary`). Those three rules are
  in `_UPSTREAM_DRIFT_RULES` in `tests/regression/test_snapshots.py`, so the
  regression test passes whether they appear or not; the snapshots are still
  refreshed (Task 4) so the baselines describe default output. No `.dsl`
  snapshot mentions graphify.
- Gitignored `graphify-out/` directories left by earlier scans exist at the
  worktree root and in seven `tests/fixtures/*/` repos, including
  `tests/fixtures/cpp-integration-repo/` (the Container E2E mount). They are
  removed in Task 1 so the local E2E and the suite cannot lean on them.
- `ci-complete` lists `container-e2e` in `needs` but its failure check does not
  test `needs.container-e2e.result`, so a failing E2E job does not fail CI.
  Task 3 adds it.
- Config reference: `site/src/content/docs/reference/config.mdx` (YAML example
  and `graphify` table) and `docs/graphify-guide.md` describe the collector.
  No JSON schema is generated from `Config`. CLI reference:
  `site/src/content/docs/reference/cli.mdx`.

Decisions the design leaves open, taken here:

- A relative `graphify.graph_path` resolves against the scanned repository
  (`repo_path / graph_path`); an absolute one is used as is.
- The `shutil.which("graphify")` check applies only when graphify must be run
  (enabled, no `graph_path`); reading a configured `graph_path` needs no
  executable.
- `--strict-collectors` exits `1` (the documented "recoverable failure" code),
  checked after outputs are written and before the baseline (`1`) and
  severity-threshold (`2`) checks.
- `_run_graphify` passes the resolved repo path and runs graphify with
  `cwd` set to the temp dir, so a relative target such as `.` is not
  re-interpreted and no stray relative write can land in the caller's CWD.

---

## Task 1 — `graphify.enabled` opt-in; graphify output in a temp dir; `graph_path` read

**Files**

- Modify `src/nfr_review/config.py` (`GraphifyConfig`)
- Modify `src/nfr_review/collectors/graphify.py`
- Modify `tests/test_graphify_collector.py`
- Modify `tests/test_config.py`
- Modify `tests/regression/test_graphify_selfscan.py`
- Modify `site/src/content/docs/reference/config.mdx`
- Modify `docs/graphify-guide.md`

**Consumes:** `GraphifyConfig(query_enabled, mcp_enabled, graph_path)`;
`GraphifyCollector.collect(repo_path, config)`; `_compute_metrics`.
**Produces:** `GraphifyConfig.enabled: bool = False`;
`_graphify_config(config: Any) -> GraphifyConfig`;
`_run_graphify(repo_path: Path, out_dir: Path) -> Path | None`;
`GraphifyCollector._evidence_from_graph(graph_json_path: Path) -> list[Evidence]`.

### Steps

1. Remove the stale, gitignored graphify output left by earlier scans:

   ```bash
   rm -rf graphify-out tests/fixtures/*/graphify-out
   git status --short --ignored | grep graphify-out   # expect no output
   ```

2. Add the failing config tests to the end of `tests/test_config.py`:

   ```python
   def test_graphify_is_disabled_by_default() -> None:
       cfg = Config()
       assert cfg.graphify.enabled is False
       assert cfg.graphify.graph_path is None


   def test_graphify_enabled_and_graph_path_load_from_yaml(tmp_path: Path) -> None:
       cfg_file = tmp_path / "nfr-review.yaml"
       cfg_file.write_text(
           "graphify:\n  enabled: true\n  graph_path: build/graph.json\n",
           encoding="utf-8",
       )
       cfg = load_config(cfg_file)
       assert cfg.graphify.enabled is True
       assert cfg.graphify.graph_path == "build/graph.json"
   ```

3. In `tests/test_graphify_collector.py`, replace the import block (lines
   `import json` … `from nfr_review.collectors.payloads.graphify import GraphEdge, GraphNode`)
   with:

   ```python
   import json
   import shutil
   import subprocess
   import sys
   from pathlib import Path
   from typing import Any
   from unittest.mock import patch

   import pytest

   from nfr_review.collectors.graphify import GraphifyCollector, _compute_metrics
   from nfr_review.collectors.payloads.graphify import GraphEdge, GraphNode
   from nfr_review.config import Config, GraphifyConfig
   ```

   Keep `_make_graph_json`, `_simple_nodes`, `_simple_edges` and
   `TestComputeMetrics` unchanged. Replace the whole
   `class TestGraphifyCollector` with:

   ```python
   _WHICH = "nfr_review.collectors.graphify.shutil.which"
   _RUN = "nfr_review.collectors.graphify.subprocess.run"

   _STALE_NODES = [
       {"id": "stale-1", "label": "Stale1", "file_type": "code", "source_file": "s1.py"},
       {"id": "stale-2", "label": "Stale2", "file_type": "code", "source_file": "s2.py"},
   ]


   def _write_graph(
       path: Path, nodes: list[dict] | None = None, edges: list[dict] | None = None
   ) -> Path:
       path.parent.mkdir(parents=True, exist_ok=True)
       data = _make_graph_json(
           _simple_nodes() if nodes is None else nodes,
           _simple_edges() if edges is None else edges,
       )
       path.write_text(json.dumps(data), encoding="utf-8")
       return path


   def _seed_stale_graph(repo: Path) -> None:
       """Leave a two-node graph.json where the old collector used to reuse it."""
       _write_graph(repo / "graphify-out" / "graph.json", nodes=_STALE_NODES, edges=[])


   def _enabled(graph_path: str | None = None) -> Config:
       return Config(graphify=GraphifyConfig(enabled=True, graph_path=graph_path))


   def _tree(root: Path) -> list[str]:
       return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


   def _fake_graphify(calls: list[dict[str, Any]]) -> Any:
       """Stand-in for subprocess.run: ``update`` writes a graph into GRAPHIFY_OUT."""

       def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
           calls.append({"args": list(args), **kwargs})
           if args[1] == "update":
               _write_graph(Path(kwargs["env"]["GRAPHIFY_OUT"]) / "graph.json")
           return subprocess.CompletedProcess(args, 0, "", "")

       return run


   class TestGraphifyCollector:
       @pytest.mark.parametrize("config", [None, Config()], ids=["no-config", "default"])
       def test_default_config_never_invokes_graphify(
           self, tmp_path: Path, config: Config | None
       ) -> None:
           _seed_stale_graph(tmp_path)
           with patch(_WHICH, return_value="/usr/bin/graphify"), patch(_RUN) as run:
               result = GraphifyCollector().collect(tmp_path, config)
           assert result == []
           run.assert_not_called()

       def test_enabled_writes_output_to_temp_dir_and_ignores_stale_repo_graph(
           self, tmp_path: Path
       ) -> None:
           repo = tmp_path / "repo"
           repo.mkdir()
           _seed_stale_graph(repo)
           before = _tree(repo)
           calls: list[dict[str, Any]] = []

           with (
               patch(_WHICH, return_value="/usr/bin/graphify"),
               patch(_RUN, side_effect=_fake_graphify(calls)),
           ):
               result = GraphifyCollector().collect(repo, _enabled())

           assert [c["args"][1] for c in calls] == ["update", "cluster-only"]
           out_dirs = {Path(c["env"]["GRAPHIFY_OUT"]) for c in calls}
           assert len(out_dirs) == 1
           out_dir = out_dirs.pop()
           assert out_dir.is_absolute()
           assert out_dir.name == "graphify-out"
           assert not out_dir.is_relative_to(repo.resolve())
           cluster_args = calls[1]["args"]
           assert cluster_args[cluster_args.index("--graph") + 1] == str(out_dir / "graph.json")
           assert not out_dir.parent.exists(), "temp dir must be deleted after the read"
           assert _tree(repo) == before, "nothing may be written into the scanned repo"
           assert len(result) == 1
           assert result[0].payload.node_count == 5
           assert "stale-1" not in {n.id for n in result[0].payload.nodes}

       def test_enabled_skips_when_not_installed(self, tmp_path: Path) -> None:
           with patch(_WHICH, return_value=None), patch(_RUN) as run:
               result = GraphifyCollector().collect(tmp_path, _enabled())
           assert result == []
           run.assert_not_called()

       def test_update_failure_returns_empty_and_removes_temp_dir(self, tmp_path: Path) -> None:
           calls: list[dict[str, Any]] = []

           def failing_run(args: list[str], **kwargs: Any) -> None:
               calls.append({"args": list(args), **kwargs})
               raise subprocess.CalledProcessError(1, args, stderr="boom")

           with (
               patch(_WHICH, return_value="/usr/bin/graphify"),
               patch(_RUN, side_effect=failing_run),
           ):
               result = GraphifyCollector().collect(tmp_path, _enabled())

           assert result == []
           assert len(calls) == 1
           assert not Path(calls[0]["env"]["GRAPHIFY_OUT"]).parent.exists()

       def test_graph_path_is_read_without_running_graphify(self, tmp_path: Path) -> None:
           graph = _write_graph(tmp_path / "elsewhere" / "graph.json")
           repo = tmp_path / "repo"
           repo.mkdir()
           with patch(_WHICH, return_value=None), patch(_RUN) as run:
               result = GraphifyCollector().collect(repo, _enabled(str(graph)))
           run.assert_not_called()
           assert len(result) == 1
           ev = result[0]
           assert ev.collector_name == "graphify"
           assert ev.kind == "graphify-analysis"
           assert ev.payload.node_count == 5
           assert ev.payload.edge_count == 9
           assert len(ev.payload.god_nodes) >= 1

       def test_relative_graph_path_resolves_against_repo(self, tmp_path: Path) -> None:
           _write_graph(tmp_path / "custom" / "graph.json")
           with patch(_RUN) as run:
               result = GraphifyCollector().collect(tmp_path, _enabled("custom/graph.json"))
           run.assert_not_called()
           assert result[0].payload.node_count == 5

       def test_missing_graph_path_returns_empty(self, tmp_path: Path) -> None:
           with patch(_RUN) as run:
               result = GraphifyCollector().collect(
                   tmp_path, _enabled(str(tmp_path / "missing.json"))
               )
           assert result == []
           run.assert_not_called()

       def test_returns_empty_on_bad_json(self, tmp_path: Path) -> None:
           bad = tmp_path / "graph.json"
           bad.write_text("not json at all", encoding="utf-8")
           assert GraphifyCollector().collect(tmp_path, _enabled(str(bad))) == []

       def test_handles_graph_without_communities(self, tmp_path: Path) -> None:
           nodes = [
               {"id": "x", "label": "X", "file_type": "code", "source_file": "x.py"},
               {"id": "y", "label": "Y", "file_type": "code", "source_file": "y.py"},
           ]
           edges = [
               {"source": "x", "target": "y", "relation": "calls", "source_file": "x.py"},
           ]
           graph = _write_graph(tmp_path / "graph.json", nodes=nodes, edges=edges)
           result = GraphifyCollector().collect(tmp_path, _enabled(str(graph)))
           assert len(result) == 1
           assert result[0].payload.community_count == 0
           assert result[0].payload.cross_community_ratio == 0.0


   @pytest.mark.skipif(shutil.which("graphify") is None, reason="graphify CLI not installed")
   @pytest.mark.skipif(sys.platform == "win32", reason="POSIX read-only permissions")
   def test_real_graphify_on_read_only_repo_writes_nothing(tmp_path: Path) -> None:
       """The real CLI, on a read-only repo holding a stale graph, as in the :ro E2E mount."""
       repo = tmp_path / "repo"
       pkg = repo / "pkg"
       pkg.mkdir(parents=True)
       (pkg / "a.py").write_text("from pkg.b import g\n\n\ndef f():\n    return g()\n")
       (pkg / "b.py").write_text("def g():\n    return 1\n\n\ndef h():\n    return g()\n")
       _seed_stale_graph(repo)
       before = _tree(repo)
       read_only_dirs = [repo, pkg, repo / "graphify-out"]
       for d in read_only_dirs:
           d.chmod(0o555)
       try:
           result = GraphifyCollector().collect(repo, _enabled())
       finally:
           for d in read_only_dirs:
               d.chmod(0o755)

       assert _tree(repo) == before
       assert len(result) == 1
       node_ids = {n.id for n in result[0].payload.nodes}
       assert node_ids
       assert not node_ids & {"stale-1", "stale-2"}
   ```

4. Run the new tests and see them fail:

   ```bash
   .venv/bin/python -m pytest -p no:xdist tests/test_graphify_collector.py tests/test_config.py -q
   ```

   Expected failures: `GraphifyConfig(enabled=True)` raises a
   `ValidationError` (`extra="forbid"`), `Config().graphify.enabled` raises
   `AttributeError`, and `test_default_config_never_invokes_graphify` fails
   on `result == []` because the old collector reuses the seeded stale
   `graph.json` and returns evidence.

5. Implement the config key. In `src/nfr_review/config.py` replace
   `GraphifyConfig` with:

   ```python
   class GraphifyConfig(BaseModel):
       """Configuration for Graphify structural analysis integration.

       ``enabled`` is off by default: the ``graphify`` collector does nothing
       unless it is turned on. With ``graph_path`` set, that ``graph.json`` is
       read (relative paths resolve against the scanned repository) and
       Graphify is not run; otherwise Graphify runs with its output in a
       temporary directory outside the scanned repository.
       """

       model_config = ConfigDict(extra="forbid")

       enabled: bool = False
       query_enabled: bool = True
       mcp_enabled: bool = False
       graph_path: str | None = None
   ```

6. Implement the collector. In `src/nfr_review/collectors/graphify.py`:

   a. Replace the module docstring with:

   ```python
   """Graphify collector — builds or reads a Graphify knowledge graph and
   computes structural metrics (god nodes, community boundary stats).

   Opt-in through ``graphify.enabled``. Graphify output always goes to a
   temporary directory (``GRAPHIFY_OUT``); a ``graphify-out/`` inside the
   scanned repository is never read or written.
   """
   ```

   b. Replace the import block with:

   ```python
   import json
   import logging
   import os
   import shutil
   import statistics
   import subprocess  # nosec B404 — args are hardcoded, not user input
   import tempfile
   from collections import Counter, defaultdict
   from pathlib import Path
   from typing import Any

   from nfr_review.collectors.payloads.graphify import (
       CommunityStats,
       GodNodeEntry,
       GraphEdge,
       GraphifyPayload,
       GraphNode,
   )
   from nfr_review.config import GraphifyConfig
   from nfr_review.models import Evidence
   from nfr_review.registry import collector_registry
   ```

   c. Below `_GOD_NODE_MULTIPLIER = 2` add `_GRAPHIFY_TIMEOUT_S = 300`, then
   replace the whole `_run_graphify` function with:

   ```python
   def _graphify_config(config: Any) -> GraphifyConfig:
       """Return the ``graphify`` section of *config*, or defaults when absent."""
       section = getattr(config, "graphify", None)
       return section if isinstance(section, GraphifyConfig) else GraphifyConfig()


   def _run_graphify(repo_path: Path, out_dir: Path) -> Path | None:
       """Run ``graphify update`` + ``cluster-only`` writing only under *out_dir*.

       *out_dir* (named ``graphify-out``) is passed to graphify as an absolute
       ``GRAPHIFY_OUT`` and the subprocesses run with their CWD beside it, so
       nothing is written into *repo_path* and any ``graphify-out/`` already
       there is never read. Returns ``out_dir / "graph.json"`` or ``None``.
       """
       repo = repo_path.resolve()
       out_dir = out_dir.resolve()
       out_dir.mkdir(parents=True, exist_ok=True)
       graph_json = out_dir / "graph.json"
       env = {**os.environ, "GRAPHIFY_OUT": str(out_dir)}
       cwd = str(out_dir.parent)

       try:
           subprocess.run(  # nosec B603 B607
               ["graphify", "update", str(repo), "--no-cluster"],
               capture_output=True,
               text=True,
               timeout=_GRAPHIFY_TIMEOUT_S,
               check=True,
               env=env,
               cwd=cwd,
           )
       except subprocess.CalledProcessError as exc:
           logger.warning(
               "graphify update failed (exit %d): %s", exc.returncode, exc.stderr[:500]
           )
           return None
       except subprocess.SubprocessError as exc:
           logger.warning("graphify update error: %s", exc)
           return None

       try:
           subprocess.run(  # nosec B603 B607
               [
                   "graphify",
                   "cluster-only",
                   str(repo),
                   "--no-viz",
                   "--no-label",
                   "--graph",
                   str(graph_json),
               ],
               capture_output=True,
               text=True,
               timeout=_GRAPHIFY_TIMEOUT_S,
               check=True,
               env=env,
               cwd=cwd,
           )
       except subprocess.CalledProcessError as exc:
           logger.warning(
               "graphify cluster-only failed (exit %d): %s", exc.returncode, exc.stderr[:500]
           )
       except subprocess.SubprocessError as exc:
           logger.warning("graphify cluster-only error: %s", exc)

       if not graph_json.is_file():
           logger.warning("graphify ran but graph.json not found at %s", graph_json)
           return None

       return graph_json
   ```

   d. In `class GraphifyCollector`, replace the docstring with
   `"""Builds or reads a Graphify graph and emits structural evidence."""`
   and replace `collect` with `collect` + `_evidence_from_graph`:

   ```python
   def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
       settings = _graphify_config(config)
       if not settings.enabled:
           logger.info("graphify.enabled is false — skipping structural analysis")
           return []

       if settings.graph_path:
           graph_json = Path(settings.graph_path)
           if not graph_json.is_absolute():
               graph_json = repo_path / graph_json
           return self._evidence_from_graph(graph_json)

       if not shutil.which("graphify"):
           logger.info("graphify not installed — skipping structural analysis")
           return []

       with tempfile.TemporaryDirectory(prefix="nfr-review-graphify-") as tmp:
           graph_json_path = _run_graphify(repo_path, Path(tmp) / "graphify-out")
           if graph_json_path is None:
               return []
           return self._evidence_from_graph(graph_json_path)


   def _evidence_from_graph(self, graph_json_path: Path) -> list[Evidence]:
       try:
           raw = json.loads(graph_json_path.read_text(encoding="utf-8"))
       except (json.JSONDecodeError, OSError) as exc:
           logger.warning("Failed to read graph.json: %s", exc)
           return []
   ```

   followed by the existing body of the old `collect` from
   `raw_nodes = raw.get("nodes", [])` through the final `return [Evidence(...)]`,
   moved unchanged into `_evidence_from_graph`.

7. Rewrite the self-scan regression fixture. In
   `tests/regression/test_graphify_selfscan.py` add `import os` to the imports
   and replace the `selfscan_evidence` fixture with:

   ```python
   @pytest.fixture(scope="module")
   def selfscan_evidence(
       graphify_available: bool, tmp_path_factory: pytest.TempPathFactory
   ) -> list:
       if not graphify_available:
           pytest.skip("graphify not installed")

       from nfr_review.collectors.graphify import GraphifyCollector, _run_graphify
       from nfr_review.config import Config, GraphifyConfig

       # Build the graph once per session, outside the repo, and share it across
       # xdist workers (basetemp's parent is per-session only under xdist). The
       # collector then reads it through graphify.graph_path.
       shared_root = tmp_path_factory.getbasetemp()
       if os.environ.get("PYTEST_XDIST_WORKER"):
           shared_root = shared_root.parent
       out_dir = shared_root / "graphify-selfscan" / "graphify-out"
       graph_json = out_dir / "graph.json"
       with FileLock(shared_root / "graphify-selfscan.lock", timeout=900):
           if not graph_json.is_file():
               assert _run_graphify(REPO_ROOT, out_dir) is not None, (
                   "graphify failed to build the self-scan graph"
               )

       config = Config(graphify=GraphifyConfig(enabled=True, graph_path=str(graph_json)))
       return GraphifyCollector().collect(REPO_ROOT, config)
   ```

8. Update the config reference, `site/src/content/docs/reference/config.mdx`:

   - In the full YAML example, replace the `graphify:` block with:

     ```yaml
     # Graphify structural analysis integration (off by default)
     graphify:
       enabled: false
       query_enabled: true
       mcp_enabled: false
       graph_path: null
     ```

     (the existing `# Graphify structural analysis integration` comment line
     is the one replaced).

   - In `### \`graphify\``, replace the table with:

     ```markdown
     | Field | Type | Default | Description |
     |-------|------|---------|-------------|
     | `enabled` | bool | `false` | Run structural analysis. When `false` the `graphify` collector does nothing and the `structure-*` rules are skipped |
     | `query_enabled` | bool | `true` | Enable structural graph queries |
     | `mcp_enabled` | bool | `false` | Enable MCP server integration for graph queries |
     | `graph_path` | string \| null | `null` | Pre-built `graph.json` to read instead of running Graphify (relative paths resolve against the scanned repository). When unset, Graphify runs with its output in a temporary directory; nothing is written into the scanned repository |
     ```

9. Update `docs/graphify-guide.md` so it no longer describes auto-detection or
   reuse of `graphify-out/graph.json`:

   - `## 2. Quick start`: replace the fenced bash block with

     ```bash
     # 1. Turn structural analysis on (it is off by default) in the
     #    nfr-review.yaml you run nfr-review with
     cat >> nfr-review.yaml <<'EOF'
     graphify:
       enabled: true
     EOF

     # 2. Run nfr-review — it runs Graphify with its output in a temp dir
     nfr-review run /path/to/target-repo

     # 3. View the findings (CSV + JSONL output by default)
     ls *-nfr-review.csv *-nfr-review.jsonl
     ```

     and change the sentence above it to "Run a structural analysis on any
     repository:".
   - `## 3. How it works`: replace the diagram line
     `graphify update ──► graphify-out/graph.json` with
     `graphify update ──► <temp dir>/graphify-out/graph.json  (or graphify.graph_path)`.
   - `### Pre-existing graph.json`: rename to `### Using a pre-built graph.json`
     and replace its body with: "nfr-review never reads a `graphify-out/` it
     finds in the scanned repository. To use a graph you built yourself (for
     example with full clustering in an earlier CI step), set
     `graphify.graph_path` to it — a relative path resolves against the
     scanned repository. nfr-review then reads that file and does not run
     Graphify; keeping it current is up to you."
   - `## 5.` collector list: replace items 1–5 with
     1. If `graphify.enabled` is `false` (the default), does nothing.
     2. If `graphify.graph_path` is set, reads that `graph.json` and does not run Graphify.
     3. Otherwise checks that `graphify` is on `PATH` — if not, skips.
     4. Runs `graphify update <repo> --no-cluster` and `graphify cluster-only`
        with `GRAPHIFY_OUT` pointing at a new temporary directory, so nothing
        is written into the scanned repository; the directory is deleted once
        the graph is read.
     5. Parses `graph.json` and computes structural metrics.
     6. Produces evidence under the `graphify` / `graphify-analysis` key.
   - `### Graceful degradation`: change "If Graphify is not installed" to
     "If structural analysis is disabled or Graphify is not installed".
   - `## 8. Configuration`: replace the YAML block with

     ```yaml
     graphify:
       enabled: false             # run structural analysis (default: false)
       query_enabled: true        # enable in-process graph queries (default: true)
       mcp_enabled: false         # use MCP server instead of in-process (default: false)
       graph_path: null           # pre-built graph.json, relative to the scanned repo
                                  # (default: run Graphify into a temp dir)
     ```

   - `### GitHub Actions` (section 9): delete the `Extract knowledge graph`
     step and add, above the example, "Set `graphify.enabled: true` in the
     repository's `nfr-review.yaml`; nfr-review runs Graphify itself."
   - `### Nightly regression`: replace its YAML with

     ```yaml
     - name: Extract knowledge graph (full)
       run: graphify update .

     - name: Run nfr-review
       run: nfr-review run . --sarif findings.sarif
     ```

     preceded by "Build the graph with full clustering yourself and point
     nfr-review at it with `graphify.enabled: true` and
     `graphify.graph_path: graphify-out/graph.json`:".
   - `## 11. Worked example`: replace the two lines
     `# Extract the knowledge graph` / `graphify update . --no-cluster` with
     `# Turn structural analysis on` /
     `printf 'graphify:\n  enabled: true\n' > "$HOME/nfr-graphify.yaml"`,
     and `nfr-review run .` with
     `nfr-review run . --config "$HOME/nfr-graphify.yaml"`.
   - `### "no graphify-analysis evidence available"`: replace the checklist
     with 1. Is `graphify.enabled: true` set? 2. Is `graphify` installed
     (`graphify --version`), or is `graphify.graph_path` set to an existing
     file? 3. Did `graphify update` succeed? Run it manually and check stderr.

10. Format and lint, then run the tests until they pass:

    ```bash
    .venv/bin/ruff format src/nfr_review/config.py src/nfr_review/collectors/graphify.py tests/test_graphify_collector.py tests/test_config.py tests/regression/test_graphify_selfscan.py
    .venv/bin/ruff check src/ tests/
    .venv/bin/python -m pytest -p no:xdist tests/test_graphify_collector.py tests/test_config.py -q
    .venv/bin/python scripts/lint_docs.py
    ```

    Expected: all pass (the real-graphify test runs, since `graphifyy` is a
    core dependency and `.venv/bin/graphify` exists).

11. Check (`unit`): run the token and confirm no graphify output appeared
    anywhere in the worktree:

    ```bash
    source .venv/bin/activate
    python -m pytest -n auto -m "not regression" tests/
    git status --short --ignored | grep graphify-out   # expect no output
    ```

12. Commit:

    ```bash
    git add src/nfr_review/config.py src/nfr_review/collectors/graphify.py \
      tests/test_graphify_collector.py tests/test_config.py \
      tests/regression/test_graphify_selfscan.py \
      site/src/content/docs/reference/config.mdx docs/graphify-guide.md
    git commit -m "fix(graphify): make graphify opt-in and keep its output out of the scanned repo

    graphify.enabled defaults to false. When enabled, graphify runs with
    GRAPHIFY_OUT in a temp dir and a repo-local graphify-out/ is never read;
    graphify.graph_path reads a pre-built graph instead.

    Plan: docs/plans/pr255-remediation/ledger.md
    Slice: M001/S04
    Rows: GR1
    Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    ```

---

## Task 2 — `RunResult.failed_collectors` and `nfr-review run --strict-collectors`

**Files**

- Modify `src/nfr_review/engine.py` (`RunResult`, `Engine.run`)
- Modify `src/nfr_review/cli.py` (`_with_findings`, `run` options, `run_cmd`, module docstring)
- Modify `tests/test_engine.py`
- Modify `tests/test_cli.py`
- Modify `site/src/content/docs/reference/cli.mdx`

**Consumes:** `Engine._run_collection_phase` → `succeeded: set[str]`;
`active_collectors` in `Engine.run`; `_with_findings`; `_write_run_outputs`.
**Produces:** `RunResult.failed_collectors: list[str]` (names of collectors
whose `collect` raised, in run order); `run --strict-collectors` (exit `1`
after outputs when `failed_collectors` is non-empty).

### Steps

1. Add the failing engine tests to the end of `tests/test_engine.py`:

   ```python
   class _GrammarWarningCollector:
       name = "grammar-warns"
       version = "0.0.1"
       grammar_warnings = ["tree-sitter grammar for x not installed"]

       def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
           return []


   @pytest.mark.parametrize("workers", [1, 4])
   def test_failed_collectors_names_only_collectors_that_raised(
       tmp_path: Path, workers: int
   ) -> None:
       cregistry: Registry = Registry("collector")
       cregistry.register("raises", _RaisingCollector())
       cregistry.register("good", _StaticCollector("good", []))
       cregistry.register("grammar-warns", _GrammarWarningCollector())
       engine = Engine(collectors=cregistry, rules=Registry("rule"), workers=workers)

       result = engine.run(tmp_path, Config())

       assert result.failed_collectors == ["raises"]


   def test_failed_collectors_empty_when_all_collectors_succeed(tmp_path: Path) -> None:
       engine, cregistry, _ = _make_engine()
       cregistry.register("good", _StaticCollector("good", []))
       assert engine.run(tmp_path, Config()).failed_collectors == []
   ```

2. Add the failing CLI tests to the end of `tests/test_cli.py` (add
   `from typing import Any` to its imports):

   ```python
   class _CrashingCollector:
       name = "crashing"
       version = "0.0.1"

       def collect(self, repo_path: Path, config: Any) -> list:
           raise RuntimeError("injected collector crash")


   def _install_collectors(monkeypatch: pytest.MonkeyPatch, *collectors: Any) -> None:
       from nfr_review.registry import Registry

       registry: Registry = Registry("collector")
       for c in collectors:
           registry.register(c.name, c)
       monkeypatch.setattr("nfr_review.engine._default_collector_registry", registry)
       monkeypatch.setattr("nfr_review.engine._default_rule_registry", Registry("rule"))


   def _run_args(tmp_path: Path, *extra: str) -> list[str]:
       target = tmp_path / "repo"
       target.mkdir()
       (target / "README.md").write_text("# sample\n")
       return [
           "run",
           str(target),
           "--csv",
           str(tmp_path / "out.csv"),
           "--jsonl",
           str(tmp_path / "out.jsonl"),
           *extra,
       ]


   def test_run_strict_collectors_exits_1_when_a_collector_crashes(
       tmp_path: Path, monkeypatch: pytest.MonkeyPatch
   ) -> None:
       _install_collectors(monkeypatch, _CrashingCollector())
       result = _runner().invoke(cli, _run_args(tmp_path, "--strict-collectors"))
       assert result.exit_code == 1, result.output
       assert "collector(s) failed: crashing" in result.stderr
       assert (tmp_path / "out.jsonl").exists(), "outputs are written before exiting"


   def test_run_without_strict_collectors_exits_0_when_a_collector_crashes(
       tmp_path: Path, monkeypatch: pytest.MonkeyPatch
   ) -> None:
       _install_collectors(monkeypatch, _CrashingCollector())
       result = _runner().invoke(cli, _run_args(tmp_path))
       assert result.exit_code == 0, result.output


   def test_run_strict_collectors_exits_0_when_no_collector_fails(
       tmp_path: Path, monkeypatch: pytest.MonkeyPatch
   ) -> None:
       _install_collectors(monkeypatch)
       result = _runner().invoke(cli, _run_args(tmp_path, "--strict-collectors"))
       assert result.exit_code == 0, result.output


   def test_with_findings_preserves_failed_collectors() -> None:
       from nfr_review.cli import _with_findings
       from nfr_review.engine import RunResult

       original = RunResult(warnings=["collector boom failed: x"], failed_collectors=["boom"])
       copied = _with_findings(original, [])
       assert copied.failed_collectors == ["boom"]
       assert copied.warnings == ["collector boom failed: x"]
   ```

3. Run them and see them fail:

   ```bash
   .venv/bin/python -m pytest -p no:xdist tests/test_engine.py tests/test_cli.py -q -k "failed_collectors or strict_collectors"
   ```

   Expected: `AttributeError: 'RunResult' object has no attribute
   'failed_collectors'`, `TypeError` on the `failed_collectors=` keyword, and
   Click exit code `2` ("No such option: --strict-collectors").

4. Implement in `src/nfr_review/engine.py`:

   - Add to `RunResult`, after `evidence`:

     ```python
         # Names of collectors whose collect() raised — the
         # "collector <name> failed: …" path. Grammar warnings are not failures.
         failed_collectors: list[str] = field(default_factory=list)
     ```

   - In `Engine.run`, after the `_run_collection_phase(...)` call add

     ```python
             failed_collectors = [c.name for c in active_collectors if c.name not in succeeded]
     ```

     and pass `failed_collectors=failed_collectors,` to the returned
     `RunResult(...)`. Leave the `# region:engine-run` markers in place.

5. Implement in `src/nfr_review/cli.py`:

   - Replace the body of `_with_findings` with
     `return dataclasses.replace(result, findings=findings)` (the module
     already imports `dataclasses`), so every other field — including
     `failed_collectors` — survives suppression, baseline and filter steps.
   - Add, directly after the `--origin` option of `run`:

     ```python
     @click.option(
         "--strict-collectors",
         is_flag=True,
         default=False,
         help="Exit 1 after writing outputs if any collector failed (crashed).",
     )
     ```

     and the parameter `strict_collectors: bool = False,` after
     `origin: str | None = None,` in `run_cmd`.
   - In `run_cmd`, immediately after the `_write_run_outputs(...)` call and
     before the `baseline_path` check, add:

     ```python
         if strict_collectors and result.failed_collectors:
             click.echo(
                 "error: --strict-collectors: collector(s) failed: "
                 + ", ".join(result.failed_collectors),
                 err=True,
             )
             raise click.exceptions.Exit(1)
     ```

   - In the module docstring's exit-code matrix, change the `1` entry to:
     ``* ``1`` — recoverable failure (bad target, ConfigError, EngineError, OutputError,
     unknown rule for ``explain``, a collector failure under ``run --strict-collectors``)``.

6. Update `site/src/content/docs/reference/cli.mdx`:

   - Exit Codes table, row `1`: "Recoverable failure — bad target path,
     config error, engine error, unknown rule, or a collector failure under
     `run --strict-collectors`".
   - `nfr-review run` options table, add after the `--origin NAME` row:
     `| \`--strict-collectors\` | Flag | off | Exit 1 after writing outputs if any collector failed (crashed); for CI gates |`

7. Format, lint, re-run the targeted tests until they pass:

   ```bash
   .venv/bin/ruff format src/nfr_review/engine.py src/nfr_review/cli.py tests/test_engine.py tests/test_cli.py
   .venv/bin/ruff check src/ tests/
   .venv/bin/python -m pytest -p no:xdist tests/test_engine.py tests/test_cli.py -q
   .venv/bin/python scripts/lint_docs.py
   ```

8. Check (`unit`):

   ```bash
   source .venv/bin/activate
   python -m pytest -n auto -m "not regression" tests/
   ```

9. Commit:

   ```bash
   git add src/nfr_review/engine.py src/nfr_review/cli.py tests/test_engine.py \
     tests/test_cli.py site/src/content/docs/reference/cli.mdx
   git commit -m "feat(cli): add run --strict-collectors to fail on collector crashes

   RunResult gains failed_collectors, the names of collectors whose collect()
   raised. run --strict-collectors exits 1 after writing outputs when it is
   non-empty; without the flag behaviour is unchanged.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S04
   Rows: GR1
   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```

---

## Task 3 — Container E2E runs with `--strict-collectors`

**Files**

- Modify `.github/workflows/ci.yml` (`container-e2e`, `ci-complete`)
- Modify `.jk/validations.yml` (`container-e2e` token)

**Consumes:** `run --strict-collectors` (Task 2); the `container-e2e` job
and the `nfr-review:e2e-test` image.
**Produces:** a fixture scan that fails on any collector crash; a CI step that
proves it does, by injecting a crashing collector; `ci-complete` failing when
`container-e2e` fails.

### Steps

1. Edit `.github/workflows/ci.yml`, job `container-e2e`:

   - In `E2E — fixture scan`, change the `-c` argument to
     `-c 'nfr-review run --strict-collectors --score --csv /tmp/out.csv --jsonl /tmp/out.jsonl .'`.
   - Add a step directly after it:

     ```yaml
           - name: E2E — strict-collectors fails on an injected collector crash
             if: steps.filter.outputs.docker == 'true'
             env:
               INJECT: |
                 from nfr_review.cli import cli
                 from nfr_review.registry import collector_registry


                 class Boom:
                     name = "boom"
                     version = "0"

                     def collect(self, repo_path, config):
                         raise RuntimeError("injected collector crash")


                 collector_registry.register("boom", Boom())
                 cli.main(["run", "--strict-collectors", "--csv", "/tmp/out.csv",
                           "--jsonl", "/tmp/out.jsonl", "."])
             run: |
               set +e
               docker run --rm --entrypoint python \
                 -v "${{ github.workspace }}/tests/fixtures/cpp-integration-repo:/repo:ro" \
                 -w /repo \
                 nfr-review:e2e-test \
                 -c "$INJECT" 2> inject-stderr.txt
               code=$?
               set -e
               cat inject-stderr.txt
               test "$code" -eq 1
               grep -q "collector(s) failed: boom" inject-stderr.txt
     ```

2. Edit `ci-complete` → `Check results`: add a
   `needs.container-e2e.result` test to the `if` chain, before the final
   `needs.doc-lint.result` line, so the block becomes

   ```bash
             if [ "${{ needs.lint.result }}" == "failure" ] || \
                [ "${{ needs.typecheck.result }}" == "failure" ] || \
                [ "${{ needs.security.result }}" == "failure" ] || \
                [ "${{ needs.test-core.result }}" == "failure" ] || \
                [ "${{ needs.test-llm.result }}" == "failure" ] || \
                [ "${{ needs.license-check.result }}" == "failure" ] || \
                [ "${{ needs.container-e2e.result }}" == "failure" ] || \
                [ "${{ needs.doc-lint.result }}" == "failure" ]; then
   ```

   (`container-e2e` is skipped, not failed, on pushes, so this does not affect
   non-PR runs.)

3. Edit `.jk/validations.yml`, token `container-e2e`: change the last line to
   `-c 'nfr-review run --strict-collectors --score --csv /tmp/out.csv --jsonl /tmp/out.jsonl .'`
   and add a comment line above the token: `# --strict-collectors makes any
   collector crash fail the run (M001/S04).`

4. Validate the YAML parses:

   ```bash
   .venv/bin/python -c "import yaml,sys; [yaml.safe_load(open(p)) for p in ('.github/workflows/ci.yml','.jk/validations.yml')]; print('ok')"
   ```

5. Check (`container-e2e`, passing case): make sure the Podman machine is up
   (`podman machine start` if `podman info` fails), confirm the fixture has no
   stale graph (`ls -a tests/fixtures/cpp-integration-repo` shows no
   `graphify-out`), then run the token exactly as expanded under
   **Validation**. Expected: build succeeds, scan exits `0`, no
   `--strict-collectors: collector(s) failed` line. If it exits `1` naming a
   collector, that collector really crashes on the `:ro` mount: stop and
   report it — do not drop the flag.

6. Check (`container-e2e`, failing case — the ledger's "exits non-zero on an
   injected collector crash"), using the image just built:

   ```bash
   podman run --rm --platform linux/amd64 --entrypoint python \
     -v "$PWD/tests/fixtures/cpp-integration-repo:/repo:ro" -w /repo nfr-review:e2e-test \
     -c 'from nfr_review.cli import cli
   from nfr_review.registry import collector_registry
   class Boom:
       name = "boom"
       version = "0"
       def collect(self, repo_path, config):
           raise RuntimeError("injected collector crash")
   collector_registry.register("boom", Boom())
   cli.main(["run", "--strict-collectors", "--csv", "/tmp/out.csv", "--jsonl", "/tmp/out.jsonl", "."])'
   echo "exit=$?"
   ```

   Expected: stderr contains
   `error: --strict-collectors: collector(s) failed: boom` and `exit=1`. Keep
   the output of steps 5 and 6 for the slice evidence.

7. Commit:

   ```bash
   git add .github/workflows/ci.yml .jk/validations.yml
   git commit -m "ci(e2e): fail Container E2E on any collector crash

   The fixture scan runs with --strict-collectors, a new step proves an
   injected crashing collector fails the run, and ci-complete now fails when
   container-e2e fails. The container-e2e validation token matches.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S04
   Rows: GR1
   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```

---

## Task 4 — Regression snapshots refreshed without graphify findings; full gate

**Files**

- Modify `tests/regression/snapshots/*.jsonl` (the 14 that hold `structure-*` findings)
- Modify `tests/regression/snapshots/snapshot-metadata.json` (rewritten by `--update-snapshots`)

**Consumes:** Tasks 1–3.
**Produces:** baselines that match default output (no `structure-*`
findings); a green `gate`.

### Steps

1. Refresh the snapshots (the `regression` token plus `--update-snapshots`,
   as `.jk/validations.yml` prescribes):

   ```bash
   source .venv/bin/activate
   python -m pytest -n auto -m regression --timeout=600 tests/regression --update-snapshots
   ```

2. Verify the refresh removed only graphify findings:

   ```bash
   git diff --stat -- tests/regression/snapshots
   # lines changed in .jsonl/.dsl that are NOT structure-* findings — expect 0
   git diff -U0 -- 'tests/regression/snapshots/*.jsonl' 'tests/regression/snapshots/*.dsl' \
     | grep -E '^[+-][^+-]' | grep -vc '"rule_id": "structure-'
   # structure-* lines removed — expect 304; added — expect 0
   git diff -U0 -- 'tests/regression/snapshots/*.jsonl' | grep -c '^-{.*"rule_id": "structure-'
   git diff -U0 -- 'tests/regression/snapshots/*.jsonl' | grep -c '^+{'
   ```

   If the first count is not 0, the refresh picked up drift unrelated to
   this slice: restore the snapshots
   (`git checkout -- tests/regression/snapshots`), and remove only the
   `structure-*` lines instead, leaving metadata untouched:

   ```bash
   .venv/bin/python - <<'EOF'
   from pathlib import Path

   for p in sorted(Path("tests/regression/snapshots").glob("*.jsonl")):
       lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
       kept = [line for line in lines if '"rule_id": "structure-' not in line]
       if kept != lines:
           p.write_text("".join(kept), encoding="utf-8")
   EOF
   ```

   then re-run the three counts (expect 0 / 304 / 0) and note the unrelated
   drift in the slice evidence.

3. Check (`regression`), against the refreshed baselines, and confirm no
   graphify output was written into any scanned or fixture repo:

   ```bash
   python -m pytest -n auto -m regression --timeout=600 tests/regression
   git status --short --ignored | grep graphify-out   # expect no output
   ```

   Expected: all pass, including `tests/regression/test_graphify_selfscan.py`.

4. Commit the snapshots with the change they reflect:

   ```bash
   git add tests/regression/snapshots
   git commit -m "test(regression): refresh snapshots now graphify is opt-in

   Default scans no longer run graphify, so the structure-* findings drop out
   of every baseline.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S04
   Rows: GR1
   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```

5. Check (`format`, then `gate`) on the slice head:

   ```bash
   pre-commit run --all-files
   pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression
   git status --short   # expect a clean tree apart from untracked plan files
   ```

   If `pre-commit` rewrites files, commit them in a fixup commit on top with
   the same three trailers, then re-run `gate`.

---

## Self-review

- **DoD coverage.**
  1. Default config never invokes graphify → Task 1
     `test_default_config_never_invokes_graphify` (`None` and `Config()`),
     plus the `git status --ignored` checks after `unit` and `regression`.
  2. Enabled output in a temp dir, nothing written into the repo → Task 1
     `test_enabled_writes_output_to_temp_dir_and_ignores_stale_repo_graph`
     (mocked) and `test_real_graphify_on_read_only_repo_writes_nothing`
     (real CLI on a read-only repo).
  3. Stale repo `graph.json` not reused → the same two tests seed a two-node
     stale graph and assert its nodes are absent.
  4. E2E fails on any collector crash and passes on `:ro` → Task 2 CLI tests,
     Task 3 CI step + `ci-complete`, Task 3 step 5 (passing token) and step 6
     (injected crash exits 1).
- **Row coverage.** GR1 "Lands in" `collectors/graphify.py`, `config.py`
  (`GraphifyConfig`) → Task 1; `.github/workflows/ci.yml` → Task 3. GR1
  verification: "no subprocess call by default and temp-dir output when
  enabled" → Task 1 tests; "`container-e2e` exits non-zero on an injected
  collector crash" → Task 3 step 6 and the CI step.
- **Placeholder scan.** No TBD/TODO; every command and test body is written
  out; no commit SHAs or line numbers are cited.
- **Name consistency.** `GraphifyConfig.enabled`, `_graphify_config`,
  `_run_graphify(repo_path, out_dir)`, `GraphifyCollector._evidence_from_graph`,
  `RunResult.failed_collectors`, `--strict-collectors` / `strict_collectors`,
  and the error text `collector(s) failed:` are spelled the same in the
  implementation steps, tests, CI step, docs and validations token.
  `_default_collector_registry` / `_default_rule_registry` are the existing
  names in `nfr_review.engine`.
