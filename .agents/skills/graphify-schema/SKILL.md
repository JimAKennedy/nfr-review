---
name: graphify-schema
description: Graphify graph.json schema reference — node/edge fields, relation types, confidence levels, community data, and Pydantic model guidance. Use when building collectors, payload models, rules, or queries that consume Graphify output.
---

# Graphify graph.json Schema

Graphify extracts a codebase knowledge graph via tree-sitter AST parsing + Leiden community detection. The output is a single `graph.json` file. This skill documents its schema so agents building collectors, payload models, and rules get the field names and types right on the first pass.

Source: https://github.com/safishamsi/graphify

## Top-level structure

```json
{
  "directed": false,
  "multigraph": false,
  "graph": {},
  "nodes": [ ... ],
  "links": [ ... ],
  "built_at_commit": "abc123",
  "hyperedges": [ ... ]
}
```

- `nodes` — array of node objects (required)
- `links` — array of edge objects (required); some versions use `edges` as the key name — accept both
- `built_at_commit` — optional git SHA at extraction time
- `hyperedges` — optional grouped relationships

## Node schema

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Unique, normalized, URL-safe |
| `label` | string | yes | Human-readable name (e.g. `"god_nodes()"`) |
| `file_type` | string | yes | One of: `code`, `document`, `concept`, `paper`, `image`, `rationale` |
| `source_file` | string | yes | Repo-relative path |
| `source_location` | string | no | Line reference, e.g. `"L42"`, `"§3.1"` |
| `community` | int \| null | no | Leiden cluster ID (0-indexed); present only after clustering |
| `community_name` | string \| null | no | Human label (default `"Community N"`, richer after LLM labelling) |
| `norm_label` | string \| null | no | Lowercased label used for fuzzy matching (added by clustering) |
| `type` | string \| null | no | Node kind — only set for `package` nodes; absent for most |
| `ecosystem` | string \| null | no | Package ecosystem (e.g. `"python"`) — only on package nodes |
| `version` | string \| null | no | Package version — only on package nodes |
| `metadata` | dict \| null | no | Extra info (e.g. `{"language": "bash", "kind": "file"}`) — rare |
| `_origin` | string | no | Always `"ast"` for code extraction |

No per-node metrics (degree, centrality, PageRank) are stored — compute on demand from edges.

## Edge schema

| Field | Type | Required | Notes |
|---|---|---|---|
| `source` | string | yes | Source node ID |
| `target` | string | yes | Target node ID |
| `relation` | string | yes | Edge type (see below) |
| `confidence` | string | yes | `EXTRACTED`, `INFERRED`, or `AMBIGUOUS` |
| `confidence_score` | float | yes | Numeric score (1.0 for EXTRACTED, ~0.5 for INFERRED) |
| `context` | string | no | Semantic context (e.g. `"dependency"`, `"direct_call"`) |
| `source_file` | string | yes | File where edge was found |
| `source_location` | string | no | Line reference in source_file |
| `weight` | float | no | Defaults to 1.0 for extracted |

### Relation types

| Relation | Meaning | Typical count |
|---|---|---|
| `calls` | Function/method invocation | dominant (~30%) |
| `uses` | Generic usage/reference | ~25% |
| `contains` | Structural containment (file→function, class→method) | ~12% |
| `method` | Method definition on a class | ~11% |
| `references` | Generic reference link | ~10% |
| `imports_from` | Import/require dependency (specific symbol) | ~5% |
| `rationale_for` | Rationale node → code node | ~4% |
| `imports` | Module-level import | ~2% |
| `inherits` | Class inheritance | <1% |
| `depends_on` | Package dependency | <1% |
| `defines` | Definition relationship | rare |
| `implements` | Interface implementation | rare |
| `embeds` | Embedding relationship | rare |

LLM-based semantic extraction may add additional relation types beyond this set.

### Confidence → weight mapping

| Confidence | Numeric weight | Meaning |
|---|---|---|
| `EXTRACTED` | 1.0 | Directly observed in AST |
| `INFERRED` | 0.5 | Deduced from patterns |
| `AMBIGUOUS` | 0.2 | Low-confidence heuristic |

## Community data

After clustering, every node gets `community` (int) and `community_name` (string) fields. Without LLM labelling, names default to `"Community N"`. Human-readable labels (e.g. "Auth Layer") are stored in `.graphify_labels.json` alongside graph.json when LLM naming is used.

- Group nodes by `community` to get clusters
- Without clustering (`--no-cluster`), `community` is absent — handle with `.get("community")`
- Community IDs are sequential from 0 but may have gaps after pruning
- On a ~500-file Python project: ~650 communities, 23% cross-community edges

## Pydantic model guidance

When building payload models for nfr-review:

1. Accept both `links` and `edges` as the edge array key (use a validator or alias)
2. Use `Literal` types for `file_type`, `relation`, and `confidence` enums
3. Make `source_location`, `community`, `weight` optional with sensible defaults
4. Ignore `_src`/`_tgt` internal fields (exclude or skip)
5. Compute metrics (degree, in-degree, out-degree, community membership counts) in the collector, not the model
6. Use `frozen=True` on the graph model — it's read-only input

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class GraphNode(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    label: str
    file_type: Literal["code", "document", "concept", "paper", "image", "rationale"]
    source_file: str
    source_location: str | None = None
    community: int | None = None
    community_name: str | None = None

class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    source: str
    target: str
    relation: str
    confidence: Literal["EXTRACTED", "INFERRED", "AMBIGUOUS"]
    confidence_score: float = 1.0
    context: str | None = None
    source_file: str
    source_location: str | None = None
    weight: float = 1.0
```

## Querying patterns

**God nodes:** nodes with in-degree + out-degree above a threshold (e.g. > 2× median).

**Weak boundaries:** cross-community edges as a fraction of total edges within each community. High ratio = leaky abstraction.

**Blast radius:** BFS/shortest-path from a changed node; count reachable nodes within N hops.

**Coupling clusters:** communities with many outgoing `calls`/`imports_from` edges to other communities.

## Operational data (validated 2026-06-20 on nfr-review)

| Metric | Value | Notes |
|---|---|---|
| Extraction time | ~5s (782 files, 18 workers) | AST-only, `graphify update . --no-cluster` |
| Clustering time | ~3s | `graphify cluster-only . --no-viz --no-label` |
| graph.json size | 24 MB (17,621 nodes, 52,208 edges) | ~500 Python files + fixtures |
| Communities | 658 | Leiden algorithm, no LLM labelling |
| Cross-community ratio | 23.1% | Edges crossing community boundaries |
| Top god nodes | Engine (352), models.py (348), RunResult (323), Registry (316), Config (315) | By total degree |

**CLI commands for the collector:**
- AST-only (no API key): `graphify update <path> --no-cluster`
- With clustering (no API key): `graphify cluster-only <path> --no-viz --no-label`
- Full extraction (needs LLM): `graphify extract <path> --backend <backend>`
- Path query: `graphify path "NodeA" "NodeB" --graph <path>/graphify-out/graph.json`

**Output files:** `graphify-out/graph.json`, `graphify-out/manifest.json`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/.graphify_labels.json`, `graphify-out/cache/`

## MCP server

Graphify ships an MCP server (`pip install "graphifyy[mcp]"`). It exposes query tools over a built graph. For S02, the key tools to look for are `query_graph`, `find_path`, `get_community`, and `get_node`. The MCP server reads graph.json from disk — no separate database.
