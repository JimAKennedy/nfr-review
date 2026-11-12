# M001/S04 design — Graphify opt-in, out of tree; E2E fails on collector crash

Status: approved (2026-11-10)

Slice: M001/S04 in `docs/plans/pr255-remediation/ledger.md` (row GR1).

## Problem

`collectors/graphify.py` runs on every scan whenever the `graphify` executable
is on PATH, and graphify is now a core dependency, so that is every scan. It
runs `graphify update` then `graphify cluster-only` (each up to 300 s), writes
`graphify-out/` into the scanned repository, and reuses any `graph.json` it
finds there, however stale. On a read-only mount (Container E2E), the write
fails, the engine records a collector error and carries on, and the job
passes.

## Decisions (see M001-decisions.md)

- `graphifyy` stays a core dependency. Graphify becomes opt-in through config
  only.
- Container E2E detects collector crashes through a new CLI flag,
  `--strict-collectors`.

## Design

### Config

`GraphifyConfig` gains `enabled: bool = False`. Behaviour of the collector:

| `enabled` | `graph_path` | Behaviour |
|---|---|---|
| false | any | Return `[]` with an info log. No subprocess is spawned. |
| true | set | Read that `graph.json` (the user owns its freshness). No subprocess. |
| true | unset | Run graphify with its output in a fresh temp dir; read it; delete the dir. |

The existing `query_enabled` and `mcp_enabled` keys are unchanged. They consume
a graph; they do not produce one.

### Out-of-tree output

graphify honours the `GRAPHIFY_OUT` environment variable as an absolute output
directory (`graphify/__main__.py`: "override with GRAPHIFY_OUT env var").
`_run_graphify(repo_path, out_dir)` passes `GRAPHIFY_OUT=<tmp>/graphify-out` in
the subprocess env for both `update` and `cluster-only`, and passes `--graph`
to `cluster-only`. A `graphify-out/` already present in the scanned repository
is never read. The collector's `tempfile.TemporaryDirectory` wraps the
subprocess calls and the read of `graph.json`.

### `--strict-collectors`

`nfr-review run --strict-collectors` exits with a non-zero status after writing
its normal outputs if any collector failed. "Failed" means the engine's
collector-error path: `collector <name> failed: …`. Grammar-not-installed
warnings are not failures. Without the flag, behaviour is unchanged.

The Container E2E fixture scan passes `--strict-collectors`.

### Tests

- Collector, default config: `subprocess.run` is never called.
- Collector, `enabled: true`: the `GRAPHIFY_OUT` env passed to both subprocess
  calls is outside `repo_path`; a pre-seeded `repo_path/graphify-out/graph.json`
  is ignored.
- Collector, `graph_path` set: it is read and no subprocess runs.
- CLI: a collector that raises makes `run --strict-collectors` exit non-zero,
  and `run` without the flag exit zero.

## Out of scope

Changing the engine's never-abort contract (R012); graphify's own CLI;
`mcp_client` / `graph_query` behaviour.
