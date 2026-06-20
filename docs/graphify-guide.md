<!-- Copyright 2026 nfr-review contributors — Licensed under Apache-2.0 -->

# Structural Analysis with Graphify

Graphify builds a knowledge graph from your codebase using tree-sitter AST
parsing. nfr-review uses this graph to surface **structural risks** that
static rules alone cannot detect: coupling hotspots, weak module boundaries,
and tightly-coupled component clusters.

This guide walks through installing Graphify, running it against a target
repository, interpreting the structural findings in nfr-review reports, and
using interactive graph queries for deeper analysis.

---

## Table of contents

1. [Prerequisites](#1-prerequisites)
2. [Quick start](#2-quick-start)
3. [How it works](#3-how-it-works)
4. [Running Graphify](#4-running-graphify)
5. [Running nfr-review with structural analysis](#5-running-nfr-review-with-structural-analysis)
6. [Understanding the findings](#6-understanding-the-findings)
7. [Interactive graph queries (MCP)](#7-interactive-graph-queries-mcp)
8. [Configuration](#8-configuration)
9. [CI integration](#9-ci-integration)
10. [Benefits and limitations](#10-benefits-and-limitations)
11. [Worked example](#11-worked-example)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Required by nfr-review |
| nfr-review | latest | `pip install nfr-review` |
| graphifyy | >=0.8 | Included in `[graphify]` extra |
| networkx | >=3.0 | Included in `[graphify]` extra |

Install nfr-review with Graphify support:

```bash
pip install "nfr-review[graphify]"
```

This installs both the `graphify` CLI and the `networkx` library used for
in-process graph queries.

Verify the installation:

```bash
graphify --version
nfr-review --version
```

---

## 2. Quick start

Run a structural analysis on any repository in three commands:

```bash
# 1. Extract the knowledge graph (AST-only, no LLM needed)
cd /path/to/target-repo
graphify update . --no-cluster

# 2. Run nfr-review — it auto-detects graphify-out/graph.json
nfr-review scan .

# 3. View the report
open nfr-report.md
```

The `structure` category appears in the maturity score and findings table
alongside the standard nfr-review categories.

---

## 3. How it works

```
target repo
    │
    ▼
graphify update ──► graphify-out/graph.json
                        │
                        ▼
nfr-review scan ──► GraphifyCollector
                        │
                        ├── computes degree metrics
                        ├── computes community boundary stats
                        │
                        ▼
                    Structural rules
                        │
                        ├── structure-god-node
                        ├── structure-weak-boundary
                        └── structure-coupling-cluster
                                │
                                ▼
                        Findings in report
```

1. **Graphify** parses every source file with tree-sitter and builds a
   directed graph of code entities (functions, classes, modules) and their
   relationships (calls, imports, defines, implements).

2. **GraphifyCollector** reads `graphify-out/graph.json`, computes degree
   metrics (in-degree, out-degree, total degree per node) and community
   boundary statistics (internal vs cross-boundary edges per community).

3. **Structural rules** evaluate the computed metrics against thresholds and
   produce findings in the standard nfr-review format.

4. When LLM analysis is enabled, **structural context** (god nodes, graph
   stats, weak boundaries, critical paths) is injected into the LLM prompt
   so the executive summary can reference graph-backed architectural risks.

---

## 4. Running Graphify

### Basic extraction

```bash
graphify update /path/to/repo --no-cluster
```

This runs AST-only extraction (no LLM API key required). For a 500-file
Python project, extraction typically takes 5-10 seconds.

The output is written to `graphify-out/graph.json` inside the target repo.

### With community clustering

```bash
graphify update /path/to/repo
```

Omitting `--no-cluster` enables Graphify's community detection algorithm,
which groups related nodes into communities. This is recommended for
structural analysis — the weak-boundary and coupling-cluster rules depend
on community assignments.

### Pre-existing graph.json

If `graphify-out/graph.json` already exists when nfr-review runs, the
collector reuses it without re-running extraction. This is useful when:

- You want to control the Graphify version or flags separately
- The extraction was run in a previous CI step
- You are pointing nfr-review at a custom graph path via configuration

### Adding graphify-out/ to .gitignore

The graph output directory should generally be gitignored:

```bash
echo "graphify-out/" >> .gitignore
```

---

## 5. Running nfr-review with structural analysis

Once Graphify has run (or will be run by the collector), scan as usual:

```bash
nfr-review scan /path/to/repo
```

The collector:

1. Checks if `graphify` is on `PATH` — if not, skips with a warning
2. Checks if `graphify-out/graph.json` exists — reuses if present
3. Runs `graphify update <repo> --no-cluster` if no graph exists
4. Parses `graph.json` and computes structural metrics
5. Produces evidence under the `graphify` / `graphify-analysis` key

Structural rules then evaluate this evidence and produce findings under the
`structure` category.

### Graceful degradation

If Graphify is not installed, all structural rules are skipped — they
report `skipped: no graphify-analysis evidence available`. The rest of the
nfr-review scan proceeds normally.

---

## 6. Understanding the findings

### structure-god-node (severity: medium)

**What it detects:** Nodes (functions, classes, modules) whose total degree
(in-degree + out-degree) exceeds 2x the median degree across all nodes.

**Why it matters:** High-degree nodes are coupling hotspots. A change to a
god node ripples to many dependents, making refactoring risky and increasing
the blast radius of bugs.

**Example finding:**

> `'Engine' has total degree 142 (threshold 34) — coupling hotspot.`

**Recommended action:** Consider breaking the entity into smaller units or
introducing a facade/interface to reduce direct coupling. Use the
[blast radius query](#blast-radius) to understand the downstream impact.

### structure-weak-boundary (severity: medium)

**What it detects:** Communities (auto-detected module clusters) where more
than 40% of edges cross the community boundary.

**Why it matters:** A high cross-boundary ratio means the module's
"boundary" is porous — components inside it depend heavily on components
outside it. This signals either a poorly-scoped module or a missing
abstraction layer.

**Example finding:**

> `'output' has 52.3% cross-boundary edges (87/166) — weak module boundary.`

**Recommended action:** Review the cross-boundary dependencies and consider
extracting a clearer interface, merging tightly-coupled clusters, or
re-drawing module boundaries. Communities with fewer than 5 total edges are
excluded as noise.

### structure-coupling-cluster (severity: low)

**What it detects:** Pairs of communities connected by 10 or more coupling
edges (calls, imports, uses).

**Why it matters:** Disproportionate coupling between two modules suggests
they are doing work that belongs together, or that an abstraction boundary
is missing between them.

**Example finding:**

> `'collectors' ↔ 'rules' have 47 coupling edges (dominant: imports_from).`

**Recommended action:** Consider introducing an interface or shared
abstraction between the two modules. If the coupling is intentional and
well-understood, the low severity means it can be triaged as accepted risk.

### Green findings

When no structural issues are detected, each rule produces a green finding:

> `No god nodes detected — all entities are within the coupling threshold.`

---

## 7. Interactive graph queries (MCP)

For deeper analysis during LLM-assisted reviews, nfr-review can query the
knowledge graph interactively via the Graphify MCP server or the in-process
`GraphQueryClient`.

### Available queries

#### Shortest path

Find the shortest dependency path between two components:

```python
from nfr_review.graph_query import GraphQueryClient

client = GraphQueryClient(payload)
result = client.shortest_path("Engine", "Config")
# PathResult(source='Engine', target='Config', path=['Engine', 'Registry', 'Config'],
#            hop_count=2, edge_relations=['imports_from', 'imports_from'])
```

#### Blast radius

Count how many nodes are reachable within N hops from a starting node:

```python
result = client.blast_radius("Engine", max_hops=3)
# BlastRadiusResult(origin='Engine', max_hops=3, reachable_count=89,
#                   by_hop={1: 34, 2: 38, 3: 17}, reachable_files=[...])
```

#### Neighbors

Get direct neighbors with edge relationship details:

```python
neighbors = client.get_neighbors("Engine", relation_filter="calls")
# [NeighborEntry(node_id='...', label='Registry.load', relation='calls',
#                direction='outgoing', source_file='src/engine.py'), ...]
```

#### Community members

List all nodes in a specific community:

```python
detail = client.community_members(community_id=3)
# CommunityDetail(community_id=3, community_name='output',
#                 members=['render', 'markdown', ...], member_labels=[...])
```

#### Cross-community coupling

Measure coupling between two communities:

```python
coupling = client.coupling_between(comm_a=1, comm_b=3)
# CouplingResult(community_a=1, community_b=3, edge_count=47,
#                relations={'imports_from': 32, 'calls': 15})
```

#### Graph statistics

Get overall graph summary:

```python
stats = client.stats()
# GraphStats(node_count=17621, edge_count=52208, community_count=658,
#            density=0.000168, avg_degree=5.93)
```

#### God nodes

Get the top-N most connected nodes:

```python
gods = client.god_nodes(top_n=5)
# [{'node_id': '...', 'label': 'Engine', 'source_file': 'src/engine.py',
#   'total_degree': 142, 'community': 0}, ...]
```

### MCP server mode

When `graphify.mcp_enabled` is set in `nfr-review.yaml`, nfr-review starts
a `graphify serve` subprocess and queries it via MCP JSON-RPC. This is
useful when an LLM agent needs to ask ad-hoc structural questions during a
review session.

The MCP client falls back to the in-process `GraphQueryClient` if the
server cannot be started.

```yaml
# nfr-review.yaml
graphify:
  mcp_enabled: true
  graph_path: graphify-out/graph.json
```

---

## 8. Configuration

Add a `graphify` section to your `nfr-review.yaml`:

```yaml
graphify:
  query_enabled: true        # enable in-process graph queries (default: true)
  mcp_enabled: false          # use MCP server instead of in-process (default: false)
  graph_path: null            # custom path to graph.json (default: auto-detect)
```

### Category weight

The `structure` category has a default weight of `1.0` in the maturity
score. Override it in your config if you want to emphasize or de-emphasize
structural findings:

```yaml
category_weights:
  structure: 1.5   # increase weight for structural analysis
```

---

## 9. CI integration

### GitHub Actions

Add Graphify to your nfr-review workflow:

```yaml
name: NFR Review
on:
  pull_request:
    branches: [main]

jobs:
  nfr-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install nfr-review with Graphify
        run: pip install "nfr-review[graphify]"

      - name: Extract knowledge graph
        run: graphify update . --no-cluster

      - name: Run nfr-review
        run: nfr-review scan . --format markdown --output nfr-report.md
```

### Nightly regression

For nightly CI, run with full clustering for richer community analysis:

```yaml
- name: Extract knowledge graph (full)
  run: graphify update .

- name: Run nfr-review
  run: nfr-review scan . --format markdown --output nfr-report.md
```

---

## 10. Benefits and limitations

### Benefits

- **No LLM needed:** Structural analysis is entirely AST-based. No API keys
  or network access required for the base workflow.

- **Fast extraction:** ~5-10 seconds for a 500-file project. Suitable for
  PR CI pipelines.

- **Actionable findings:** God nodes, weak boundaries, and coupling clusters
  map directly to architectural refactoring opportunities.

- **LLM enrichment:** When LLM analysis is enabled, structural context is
  injected into the prompt, producing graph-backed observations in the
  executive summary (structural risks, coupling hotspots).

- **Graceful degradation:** If Graphify is not installed, structural rules
  are skipped and the rest of the scan proceeds normally.

### Limitations

- **Language coverage:** Graphify uses tree-sitter and supports the same
  languages tree-sitter grammars are available for. Coverage varies by
  language ecosystem.

- **Graph size:** For very large codebases (10K+ files), `graph.json` can
  be tens of megabytes. The collector loads it fully into memory.

- **Community detection quality:** Auto-detected communities may not always
  match human-perceived module boundaries. The weak-boundary rule uses a
  40% threshold to reduce false positives, but some noise is expected.

- **Relationship fidelity:** AST-based extraction captures syntactic
  relationships (imports, calls, defines). It does not capture runtime
  dependencies, dynamic dispatch, or dependency injection patterns.

- **No incremental extraction:** `graphify update` re-extracts the entire
  codebase. There is no diff-mode for partial re-extraction.

---

## 11. Worked example

### Scenario: reviewing a Python CLI tool

```bash
# Clone the target repository
git clone https://github.com/example/my-cli-tool.git
cd my-cli-tool

# Install nfr-review with Graphify
pip install "nfr-review[graphify]"

# Extract the knowledge graph
graphify update . --no-cluster

# Run the structural review
nfr-review scan . --format markdown --output structural-review.md
```

### Expected report output

The report includes a **Structure** section under the maturity score:

```
Category Scores:
  ...
  structure: 0.65
  ...

Findings:
  [AMBER] structure-god-node: 'AppController' has total degree 87
          (threshold 22) — coupling hotspot.
  [AMBER] structure-weak-boundary: 'handlers' has 48.2% cross-boundary
          edges (53/110) — weak module boundary.
  [AMBER] structure-coupling-cluster: 'models' ↔ 'handlers' have 31
          coupling edges (dominant: imports_from).
  [GREEN] structure-god-node: No additional god nodes above threshold.
```

### Deeper investigation with graph queries

```python
from nfr_review.collectors.payloads.graphify import GraphifyPayload
from nfr_review.graph_query import GraphQueryClient
import json

# Load the graph
with open("graphify-out/graph.json") as f:
    data = json.load(f)

payload = GraphifyPayload(**data)
client = GraphQueryClient(payload)

# How far does a change to AppController ripple?
radius = client.blast_radius("AppController", max_hops=2)
print(f"Reachable in 2 hops: {radius.reachable_count} nodes")
print(f"Files affected: {len(radius.reachable_files)}")

# What's the shortest path from AppController to the database layer?
path = client.shortest_path("AppController", "DatabasePool")
if path:
    print(f"Path ({path.hop_count} hops): {' → '.join(path.path)}")
    print(f"Relations: {path.edge_relations}")
```

---

## 12. Troubleshooting

### "graphify: command not found"

Graphify is not installed or not on PATH. Install with:

```bash
pip install "nfr-review[graphify]"
```

Verify: `which graphify` should return a path.

### "no graphify-analysis evidence available"

The Graphify collector was skipped. Check:

1. Is `graphify` installed? (`graphify --version`)
2. Does `graphify-out/graph.json` exist in the target repo?
3. Did `graphify update` succeed? Run it manually and check stderr.

### Large graph.json causes slow scans

For codebases producing graph files over 50 MB:

- Use `--no-cluster` to skip community detection (faster extraction,
  but disables weak-boundary and coupling-cluster rules)
- Consider scoping Graphify to specific subdirectories if supported

### MCP server won't start

If `graphify.mcp_enabled: true` but the MCP server fails:

1. Verify `graphify serve` works manually:
   `graphify serve graphify-out/graph.json`
2. Check that the MCP extras are installed:
   `pip install "graphifyy[mcp]"`
3. nfr-review automatically falls back to in-process queries, so findings
   are still produced even if MCP fails.

---

## See also

- [Installation guide](install.md) — installing nfr-review with optional extras
- [External dependencies](dependencies.md) — full dependency reference
- [Custom rules](custom-rules.md) — writing your own nfr-review rules
