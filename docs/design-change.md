<!-- Copyright 2026 nfr-review contributors — Licensed under Apache-2.0 -->

# Design-Change Detection

Detects structural drift between review runs by comparing a saved baseline
snapshot against the current scan. Changes that exceed configurable thresholds
surface as findings so teams catch architectural shifts early.

---

## Quick Start

```bash
# First run — creates the baseline snapshot
nfr-review run ./my-repo --design-baseline-dir ./baselines

# ... make changes to the codebase ...

# Second run — diffs against the baseline, reports changes
nfr-review run ./my-repo --design-baseline-dir ./baselines
```

The first run saves a `<repo>-structural-baseline.json` file and prints:

```
No previous structural baseline found, saving initial: ./baselines/my-repo-structural-baseline.json
```

Subsequent runs diff the current scan against the saved baseline. If nothing
changed:

```
No structural changes since last baseline.
```

If changes exceed thresholds, a summary prints to stderr and findings appear in
the normal output (CSV, JSONL, SARIF).

---

## How It Works

1. **Snapshot** — Each scan extracts numeric and set metrics from evidence
   (class counts, dependency lists, API endpoints, etc.) into a
   `StructuralBaseline`.
2. **Diff** — The engine compares the new snapshot against the previous baseline
   per metric, producing `NumericDelta` (value changed) and `SetDelta`
   (items added/removed) records.
3. **Threshold filter** — Deltas below configured thresholds are suppressed.
   Numeric thresholds are minimum absolute percent change. Set thresholds are
   minimum total items added + removed.
4. **Findings** — Surviving deltas become `design-change-trigger` findings with
   severity scaled by magnitude.
5. **Save** — The new snapshot always overwrites the baseline file so the next
   run diffs against the latest state.

---

## Detected Signals

### Numeric metrics

| Category | Metric | What it detects | Example trigger |
|---|---|---|---|
| `structure` | `class_count` | Total classes/structs across all languages | 10 new classes added |
| `structure` | `dormant_class_count` | Classes with no inheritance or nesting links | Orphan utility classes accumulating |
| `jdepend` | `jdepend_instability` | Max instability (I) across Java packages | Package coupling shift |
| `dependencies` | `dependency_count` | Direct dependency count | New library added to pom.xml |
| `coverage` | `test_coverage` | Line coverage percentage (JaCoCo) | Coverage dropped 8% |
| `adrs` | `adr_count` | Number of ADR documents | New ADR recorded |
| `api_surface` | `api_endpoint_count` | Proto RPCs + OpenAPI endpoints | New gRPC method added |
| `bounded_context` | `bounded_context_count` | Distinct bounded contexts from package names | New domain module appeared |
| `integration_style` | `integration_point_count` | HTTP calls, gRPC methods, mesh routes, messaging deps | Added Kafka integration |
| `deployment_topology` | `deployment_service_count` | Helm charts, K8s resource kinds, Terraform modules | New Helm chart deployed |
| `schema_migration` | `schema_migration_count` | Migration tools + migration files detected | Flyway migration added |

### Set metrics

| Category | Metric | What it tracks |
|---|---|---|
| `jdepend` | `jdepend_cycles` | Package names involved in dependency cycles |
| `dependencies` | `dependency_names` | Direct dependency names |
| `adrs` | `adr_titles` | ADR document titles |
| `adrs` | `superseded_adrs` | ADRs marked superseded/deprecated/replaced |
| `api_surface` | `api_endpoints` | `Service.Method` (proto) and `METHOD /path` (OpenAPI) |
| `bounded_context` | `bounded_contexts` | Bounded context names extracted from packages |
| `integration_style` | `integration_styles` | Labels like `http:direct`, `grpc`, `messaging:kafka` |
| `deployment_topology` | `deployment_services` | Labels like `helm:myapp`, `k8s:Deployment`, `terraform:vpc` |
| `schema_migration` | `schema_migrations` | `tool:flyway`, `file:db/migration/V2__add_column.sql` |

---

## Threshold Configuration

Default thresholds (built-in):

```yaml
# nfr-review.yaml
design_change:
  thresholds:
    class_count: 20.0           # % change
    jdepend_instability: 15.0   # % change
    dormant_class_count: 25.0   # % change
    dependency_count: 30.0      # % change
    test_coverage: 5.0          # % change
    adr_count: 1.0              # item count for sets, % for numeric
    api_endpoint_count: 1.0
    bounded_context_count: 1.0
    integration_point_count: 1.0
    deployment_service_count: 1.0
    schema_migration_count: 1.0
```

Override any threshold by setting it in your project `nfr-review.yaml`:

```yaml
design_change:
  thresholds:
    class_count: 10.0        # tighter: flag at 10% change
    dependency_count: 50.0   # looser: flag only at 50% change
```

**Note:** the `thresholds` dict is replaced entirely when you override it.
Include every threshold you want active -- omitted keys pass through unfiltered
(any change surfaces as a finding).

To ignore project overrides and use the built-in defaults:

```bash
nfr-review run ./my-repo \
  --design-baseline-dir ./baselines \
  --force-standard-config
```

---

## Output

Changes that survive threshold filtering appear as findings with:

- **rule_id:** `design-change-trigger`
- **pattern_tag:** `design_change:<metric_name>` (e.g. `design_change:class_count`)
- **rag:** `amber`
- **severity:** scaled by magnitude:
  - Numeric: `high` (>=50% change), `medium` (>=20%), `low` (<20%)
  - Set: `high` (>=5 items changed), `medium` (>=3), `low` (<3)

Example finding summary:

```
structure/class_count changed: 42 -> 55 (delta +13) (+31.0%)
```

Example set finding summary:

```
dependencies/dependency_names: added spring-boot-starter-kafka, micrometer-core
```

A diff summary also prints to stderr:

```
Design Change Summary
=====================

[structure]
  class_count: 42 -> 55 (+13) (+31.0%)

[dependencies]
  dependency_names added: spring-boot-starter-kafka, micrometer-core
```

---

## Baseline Storage

Baselines are stored in the directory passed to `--design-baseline-dir`.

**File naming:** `<repo>-structural-baseline.json`

The repo name is derived from the scan target path. Example:

```
baselines/my-service-structural-baseline.json
```

The file is a JSON document containing versioned metric snapshots:

```json
{
  "version": 1,
  "created_at": "2026-06-18T12:00:00Z",
  "source_repo": "my-service",
  "metrics": {
    "structure": {
      "category": "structure",
      "numeric_metrics": { "class_count": { "name": "class_count", "value": 42.0, "unit": "" } },
      "set_metrics": {}
    }
  }
}
```

The baseline is overwritten on every run so it always reflects the most recent
scan. To keep history, commit baseline files to version control or archive them
in CI artifacts.
