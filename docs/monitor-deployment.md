# Production Interaction Monitor — Deployment Guide

The interaction monitor compares live production traces against a UAT-derived
baseline to detect novel service interactions that were never exercised during
testing.

## Prerequisites

- Python 3.11+ with `nfr-review[monitor]` installed (`pip install nfr-review[monitor]`)
- A baseline JSON file created from UAT trace data
- (Optional) `otelcol-contrib` for collector-mediated trace forwarding

## Quick Start

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

```bash
nfr-review monitor \
  --baseline baseline.json \
  --port 4318 \
  --window-seconds 60
```

The monitor starts an HTTP server that:

- Accepts OTLP JSON trace exports on `POST /v1/traces`
- Groups spans into configurable time windows
- Compares each window against the baseline
- Emits JSON alerts to stdout for novel interactions

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

## Container Deployment

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

## Configuration Reference

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

## Baseline Management

Baselines should be refreshed after significant UAT changes. A typical workflow:

1. Run UAT suite with OTel tracing → export traces
2. `nfr-review baseline create` → new baseline JSON
3. `nfr-review baseline diff` → verify against recent production traces
4. Deploy updated baseline to the monitor (restart or volume mount update)

Store baselines as versioned artifacts in your CI pipeline for auditability.
