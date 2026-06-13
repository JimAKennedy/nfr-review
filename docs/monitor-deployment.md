# Production Interaction Monitor — Deployment Guide

> **EXPERIMENTAL** — The production interaction monitor is an experimental
> feature. Its CLI interface, alert format, and baseline schema may change in
> future releases without following semantic versioning guarantees. Feedback
> and bug reports are welcome.

---

The interaction monitor compares live production traces against a UAT-derived
baseline to detect **novel service interactions** that were never exercised
during testing. It runs as a long-lived HTTP server that accepts OTLP trace
exports, fingerprints the service-to-service interactions within configurable
time windows, and emits JSON alerts to stdout when it observes an interaction
pattern that does not appear in the baseline.

This is useful for catching unexpected topology changes in production, such
as a new microservice dependency introduced by a deployment that was not
covered by UAT.

> **Related:** For one-shot dynamic analysis during development or CI (trace
> file scanning, topology diagrams, N+1 detection), see the
> [Dynamic Analysis guide](dynamic-analysis.md).

---

## Table of contents

1. [Prerequisites](#prerequisites)
2. [Architecture overview](#architecture-overview)
3. [Quick start](#quick-start)
4. [Creating a baseline](#1-create-a-baseline-from-uat-traces)
5. [One-shot diff](#2-one-shot-diff-optional-verification)
6. [Starting the monitor](#3-start-the-live-monitor)
7. [Endpoints](#endpoints)
8. [Backpressure](#backpressure)
9. [Alert output](#alert-output)
10. [Interpreting alerts](#interpreting-alerts)
11. [Container deployment](#container-deployment)
12. [Configuration reference](#configuration-reference)
13. [Baseline management](#baseline-management)

---

## Prerequisites

- Python 3.11+ with `nfr-review[monitor]` installed (`pip install "nfr-review[monitor]"`)
- A baseline JSON file created from UAT trace data
- (Optional) `otelcol-contrib` for collector-mediated trace forwarding

For general installation instructions, see the [Install guide](install.md).

---

## Architecture overview

```
                         +-------------------+
  Applications           |  OTel Collector   |
  (instrumented) ------> |  (sidecar/agent)  |
                         +--------+----------+
                                  |
                          OTLP HTTP POST
                          /v1/traces
                                  |
                                  v
                         +-------------------+
                         |  nfr-review       |
                         |  monitor          |
                         |                   |
                         |  +-------------+  |
                         |  | OTLP        |  |
                         |  | Receiver    |  |    stdout
                         |  +------+------+  |  ---------> JSON alerts
                         |         |         |             (one per line)
                         |  +------v------+  |
                         |  | Window      |  |
                         |  | Manager     |  |
                         |  +------+------+  |
                         |         |         |
                         |  +------v------+  |
                         |  | Fingerprint |  |
                         |  | + Baseline  |  |
                         |  | Diff        |  |
                         |  +-------------+  |
                         +-------------------+
```

The monitor consists of three internal components:

1. **OTLP Receiver** (`receiver.py`) — an aiohttp HTTP server that accepts
   `POST /v1/traces` with OTLP JSON payloads and parses them into span
   objects. Also serves health, readiness, and stats endpoints.

2. **Window Manager** (`window.py`) — accumulates spans into time windows
   (default 60 seconds). When a window closes, it extracts interaction
   fingerprints from the buffered spans and compares them against the
   baseline.

3. **Fingerprint + Baseline Diff** (`fingerprint.py`, `baseline.py`,
   `diff.py`) — extracts deterministic fingerprints from spans by hashing
   the caller service, callee service, operation name, span kind, and
   protocol. Novel fingerprints (present in the window but absent from the
   baseline) produce alert findings.

Fingerprints are **deterministic**: the same set of spans always produces the
same fingerprints. A fingerprint captures the interaction type (e.g.
`order-svc -> payments-svc [POST /charge] (http, kind=3)`), not individual
request instances.

## Quick start

### 1. Create a baseline from UAT traces

Run your UAT suite with OpenTelemetry tracing enabled, then export the traces
to an OTLP JSON or NDJSON file:

```bash
nfr-review baseline create \
  --otel-traces uat-traces.ndjson \
  -o baseline.json
```

The command prints summary statistics to stderr and the output path to stdout:

```
Baseline created: 42 fingerprints from 8 traces across 5 services
baseline.json
```

### 2. One-shot diff (optional verification)

Before deploying the live monitor, verify the baseline against a production
trace sample:

```bash
nfr-review baseline diff \
  --baseline baseline.json \
  --otel-traces prod-sample.ndjson
```

Formats: `--format md` (default, human-readable) or `--format json` (JSONL
findings for pipeline consumption). Use `-o <file>` to write to a file.

### 3. Start the live monitor

> **EXPERIMENTAL:** The `monitor` command is experimental. Its interface may
> change in future releases.

```bash
nfr-review monitor \
  --baseline baseline.json \
  --port 4318 \
  --window-seconds 60
```

The monitor starts a long-lived HTTP server that:

- Accepts OTLP JSON trace exports on `POST /v1/traces`
- Groups spans into configurable time windows (default: 60 seconds)
- Extracts interaction fingerprints from each window
- Compares fingerprints against the baseline
- Emits JSON alerts to stdout for novel interactions not seen in UAT
- Deduplicates alerts by default (the same novel interaction is reported
  only once, not on every window)

The monitor runs until it receives SIGTERM or SIGINT (Ctrl+C). On shutdown,
it flushes any remaining spans in the current window and logs final
statistics.

## Endpoints

| Path | Method | Purpose |
|------|--------|---------|
| `/v1/traces` | POST | OTLP JSON trace ingestion |
| `/healthz` | GET | Liveness probe — always returns 200 |
| `/readyz` | GET | Readiness probe — 200 when accepting traffic, 503 during startup/shutdown |
| `/statsz` | GET | JSON counters: `spans_received`, `requests_total`, `backpressure_count`, `alerts_emitted`, `queue_depth`, `total_flushes` |

## Backpressure

When the internal span queue reaches capacity (default 50,000 spans), the
monitor returns HTTP 429 with `Retry-After: 5`. Upstream collectors should
respect this and retry with backoff.

## Alert Output

Each alert is a single JSON line on stdout:

```json
{
  "timestamp": "2026-06-11T14:30:00Z",
  "window_span_count": 1200,
  "window_fingerprint_count": 15,
  "finding_rule_id": "mon-novel-interaction",
  "finding_severity": "high",
  "finding_summary": "Novel interaction not seen in UAT: order-svc → payments-svc [POST /charge] (http, kind=3)",
  "finding_evidence": "fingerprint:a1b2c3d4e5f6"
}
```

Pipe stdout to a log aggregator, webhook forwarder, or alerting system.

## Interpreting alerts

Each alert represents a service-to-service interaction pattern that was
observed in production but was **not present in the UAT baseline**. This
means the interaction was never exercised during your UAT test suite.

### Alert fields

| Field | Meaning |
|-------|---------|
| `timestamp` | When the alert was emitted (UTC) |
| `window_span_count` | Total spans in the time window that triggered the alert |
| `window_fingerprint_count` | Total unique interaction fingerprints in the window |
| `finding_rule_id` | Always `mon-novel-interaction` for novel interaction alerts |
| `finding_severity` | `high` for HTTP/gRPC/RPC interactions, `medium` for database/messaging, `low` for unknown protocols |
| `finding_summary` | Human-readable description: `caller -> callee [operation] (protocol, kind=N)` |
| `finding_evidence` | Fingerprint hash for deduplication and tracking |

### What to do when you get an alert

1. **Is this a known new feature?** If a recent deployment added a new
   service dependency, this alert is expected. Re-run UAT with the updated
   code and regenerate the baseline (see [Baseline management](#baseline-management)).

2. **Is this unexpected?** An unexpected novel interaction could indicate:
   - A misconfigured service routing to the wrong downstream
   - A feature flag enabling a code path that was not tested
   - A dependency injection error wiring the wrong client

3. **Is this a false positive?** If your UAT suite does not exercise all
   code paths, some legitimate interactions may appear as novel. Expand your
   UAT coverage and regenerate the baseline.

### Severity assignment

The monitor assigns severity based on the interaction protocol:

| Protocol | Severity | Rationale |
|----------|----------|-----------|
| `http`, `grpc`, `rpc` | `high` | Synchronous service-to-service calls have the highest blast radius |
| `db`, `messaging` | `medium` | Infrastructure interactions are typically more contained |
| `unknown`, `internal` | `low` | Unclassified interactions need manual review |

### Deduplication

By default, the monitor deduplicates alerts: once a novel interaction has
been reported, it will not be reported again in subsequent windows. This
prevents alert storms when a new deployment introduces a persistent novel
interaction.

The deduplication set is stored in memory (default capacity: 100,000
fingerprint hashes). When the set reaches capacity, it is evicted entirely
and deduplication restarts. To disable deduplication, set `deduplicate=False`
in the `MonitorConfig` (not exposed as a CLI flag).

---

## Container deployment

### With OTel Collector sidecar

Use `otelcol-contrib` as a sidecar to receive traces from your applications
and forward them to the nfr-review monitor:

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

exporters:
  otlphttp:
    endpoint: http://nfr-monitor:4318

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlphttp]
```

### Docker Compose example

```yaml
services:
  nfr-monitor:
    image: ghcr.io/jimakennedy/nfr-review:latest
    command: >-
      nfr-review monitor
        --baseline /data/baseline.json
        --port 4318
        --window-seconds 60
    ports:
      - "4318:4318"
    volumes:
      - ./baseline.json:/data/baseline.json:ro
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4318/healthz"]
      interval: 10s
      timeout: 3s
      retries: 3

  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    command: ["--config=/etc/otel/config.yaml"]
    volumes:
      - ./otel-collector-config.yaml:/etc/otel/config.yaml:ro
    ports:
      - "4317:4317"
    depends_on:
      nfr-monitor:
        condition: service_healthy
```

### Kubernetes liveness/readiness probes

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 4318
  initialDelaySeconds: 5
  periodSeconds: 10
readinessProbe:
  httpGet:
    path: /readyz
    port: 4318
  initialDelaySeconds: 3
  periodSeconds: 5
```

## Configuration reference

| CLI Flag | Default | Description |
|----------|---------|-------------|
| `--baseline` | (required) | Path to baseline JSON file |
| `--port` | 4318 | OTLP HTTP receiver port |
| `--host` | 0.0.0.0 | Bind address |
| `--window-seconds` | 60 | Time window for grouping spans before comparison |

Engine defaults (not exposed as CLI flags, configurable via API):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_body_bytes` | 16 MB | Maximum OTLP request body size |
| `max_queue_spans` | 50,000 | Span queue capacity before 429 backpressure |
| `max_seen_hashes` | 100,000 | Deduplication set capacity (evicts on overflow) |
| `deduplicate` | true | Suppress repeated alerts for the same novel interaction |

## Baseline management

Baselines should be refreshed after significant UAT changes. A typical workflow:

1. Run UAT suite with OTel tracing enabled, export traces to an NDJSON file.
2. Create a new baseline:
   ```bash
   nfr-review baseline create --otel-traces uat-traces.ndjson -o baseline.json
   ```
3. Verify the baseline against recent production traces:
   ```bash
   nfr-review baseline diff --baseline baseline.json --otel-traces prod-sample.ndjson
   ```
4. Deploy the updated baseline to the monitor (restart the process or
   update the volume mount).

### Baseline file format

The baseline is a JSON file containing a versioned snapshot of interaction
fingerprints. Each fingerprint captures a unique service-to-service
interaction pattern (caller, callee, operation, span kind, protocol) as a
deterministic SHA-256 hash.

```json
{
  "version": 1,
  "created_at": "2026-06-12T10:00:00+00:00",
  "source": "uat-traces.ndjson",
  "trace_count": 42,
  "span_count": 1200,
  "fingerprints": [
    {
      "caller_service": "order-svc",
      "callee_service": "payments-svc",
      "operation": "POST /charge",
      "span_kind": 3,
      "protocol": "http",
      "fingerprint_hash": "a1b2c3d4e5f67890"
    }
  ]
}
```

### Tips

- Store baselines as versioned artifacts in your CI pipeline for
  auditability.
- Use `baseline diff` in CI to detect topology changes before deploying
  the live monitor.
- If the monitor reports many novel interactions after a large UAT update,
  regenerate the baseline from the updated UAT traces rather than
  suppressing alerts.
