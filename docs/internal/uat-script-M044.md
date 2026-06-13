# M044 UAT Script — Dynamic Analysis Diagrams and OTel Collector

**Version:** 0.1.3
**Last updated:** 2026-06-09

This script covers end-to-end acceptance testing for M044: dynamic analysis
diagram rendering, OTel trace ingestion, and Band 3 rule evaluation.

Run against `agentic-java-demo` as the reference target.

---

## 0. Prerequisites

```bash
cd /path/to/nfr-review
pip install -e ".[dev,pdf]"
nfr-review version
# Expected: 0.1.3
```

| Check | Expected |
|-------|----------|
| `nfr-review --help` shows `--otel-traces` and `--collector` flags | Both present in `run` and `report` commands |
| `tests/fixtures/otel-traces/traces-multi-service-topology.json` exists | 4 services, 9 spans |

---

## 1. Trace-Based E2E (No Collector Binary Required)

Run a full report against agentic-java-demo using pre-recorded traces:

```bash
nfr-review report \
  --config tests/fixtures/configs/agentic-java-demo.yaml \
  --otel-traces tests/fixtures/otel-traces/traces-multi-service-topology.json \
  --no-tests --no-deps --no-summary \
  --output-dir /tmp/nfr-e2e-m044 \
  ../agentic-java-demo
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| `findings=` count | >= 160 (includes Band 3 dynamic findings) |
| `Added N dynamic diagram(s)` in output | >= 4 diagrams (topology + sequences) |
| PDF file created | Non-zero `.pdf` in output dir |
| Image directory created | `*-images/` with `runtime-service-topology.png` and `call-sequence-*.png` |

### 1.1 Verify Diagrams in Markdown

```bash
grep -c '```mermaid' /tmp/nfr-e2e-m044/*.md
# Expected: >= 6 (severity pie + tech overview + topology + 3 sequences)
```

```bash
grep '### Runtime Service Topology' /tmp/nfr-e2e-m044/*.md
grep '### Call Sequence' /tmp/nfr-e2e-m044/*.md
# Expected: topology section + at least 2 call sequence sections
```

### 1.2 Verify Band 3 Dynamic Rule Findings

```bash
grep 'dyn-' /tmp/nfr-e2e-m044/*.md
```

| Rule | Expected Finding |
|------|-----------------|
| `dyn-call-sequence` | 3 sequence diagrams with Mermaid blocks |
| `dyn-latency-p95` | p95 measurements for multiple routes |
| `dyn-n-plus-1` | "No N+1 query patterns detected" |
| `dyn-adr-drift` | Observed 4 services with edges |
| `dyn-correlation-propagation` | Correlation-ID status reported |
| `dyn-method-coverage` | Method coverage status reported |

### 1.3 Verify Topology Diagram Content

The Runtime Service Topology should show:
- 4 nodes: `api-gateway`, `order-service`, `payment-service`, `notification-service`
- Directed edges from `api-gateway` to downstream services

### 1.4 Verify Sequence Diagram Content

Call Sequence 1 should show `GET /api/orders` flow:
- Client → api-gateway → order-service → SELECT orders

Call Sequence 2 should show `POST /api/payments` flow:
- Client → api-gateway → payment-service → INSERT payment

---

## 2. Collector-Based E2E (Requires otelcol-contrib + Java 21)

This section requires:
- `otelcol-contrib` on PATH (install via `scripts/setup-all.sh` or download from [GitHub releases](https://github.com/open-telemetry/opentelemetry-collector-releases/releases))
- Java 21 + Gradle (for running agentic-java-demo)

### 2.1 Start agentic-java-demo

```bash
cd ../agentic-java-demo
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
OTEL_SERVICE_NAME=agentic-java-demo \
./gradlew bootRun
```

### 2.2 Run nfr-review with managed collector

```bash
cd /path/to/nfr-review
nfr-review report \
  --config tests/fixtures/configs/agentic-java-demo.yaml \
  --collector \
  --no-tests --no-deps --no-summary \
  --output-dir /tmp/nfr-e2e-m044-live \
  ../agentic-java-demo
```

| Check | Expected |
|-------|----------|
| "OTel Collector started: pid=..." in output | Collector subprocess launched |
| Collector stops after scan completes | No orphaned otelcol process |
| Findings include Band 3 dynamic rules | Same as Section 1.2 (with live trace data) |
| PDF contains topology and sequence diagrams | Visual verification |

---

## 3. Edge Cases

### 3.1 Missing Collector Binary

```bash
PATH=/usr/bin nfr-review report --collector --no-tests --no-deps --no-summary \
  --output-dir /tmp/nfr-e2e-nocol ../agentic-java-demo
```

| Check | Expected |
|-------|----------|
| Warning message | "OTel Collector binary not found on PATH" |
| Report still completes | Exit code 0, static analysis findings present |

### 3.2 Mutual Exclusion

```bash
nfr-review report --collector --otel-traces foo.json ../agentic-java-demo
```

| Check | Expected |
|-------|----------|
| Error | "--collector and --otel-traces are mutually exclusive" |

### 3.3 Empty Trace File

```bash
nfr-review report \
  --otel-traces tests/fixtures/otel-traces/traces-empty.json \
  --no-tests --no-deps --no-summary \
  --output-dir /tmp/nfr-e2e-empty ../agentic-java-demo
```

| Check | Expected |
|-------|----------|
| Report completes | Exit code 0 |
| Dynamic rules skipped | "no otel-trace evidence available" in maturity table |
| No dynamic diagrams | Only severity + tech overview diagrams |

---

## 4. Nightly CI Validation

The `.github/workflows/nfr-review-nightly.yml` includes a `dynamic-analysis` job.

| Check | Expected |
|-------|----------|
| Job runs `nfr-review report --otel-traces` | Uses `traces-multi-service-topology.json` fixture |
| Job verifies Mermaid blocks exist | `grep -c` check in step |
| Report artifact uploaded | 30-day retention |
