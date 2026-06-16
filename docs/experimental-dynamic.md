# Dynamic Analysis and Production Monitor (Experimental)

nfr-review supports runtime analysis through OpenTelemetry trace ingestion. This extends the static analysis with latency hotspot detection, N+1 query patterns, service topology mapping, and interaction baseline comparison.

Dynamic analysis is experimental — the trace analysis rules and monitor protocol are evolving.

## Dynamic analysis (runtime traces)

nfr-review can analyse OpenTelemetry traces captured from a running application to detect latency hotspots, N+1 query patterns, missing trace correlation, and service coverage gaps.

### Option A — Pre-collected traces

```bash
# Run your app's integration tests (or exercise it manually) while an OTel Collector
# exports traces to an NDJSON file, then point nfr-review at the file:
nfr-review report /path/to/repo --otel-traces /path/to/traces.ndjson
```

### Option B — Managed collector

nfr-review starts/stops `otelcol-contrib` for you:

```bash
# 1. Start your instrumented application (it must export OTLP to localhost:4317 or :4318)
#    e.g. ./gradlew bootRun, docker compose up, python manage.py runserver, etc.

# 2. nfr-review starts the collector, captures traces during the scan, then stops it
nfr-review report /path/to/repo --collector -v
```

The `--collector` flag requires `otelcol-contrib` on your `$PATH`:

```bash
# Installs otelcol-contrib along with other optional tools
scripts/setup-all.sh

# Or download the binary directly from GitHub releases:
# https://github.com/open-telemetry/opentelemetry-collector-releases/releases
```

### Flags

| Flag | Description |
|------|-------------|
| `--otel-traces PATH` | Path to a pre-collected OTLP JSON / NDJSON trace file |
| `--collector` | Start a managed OTel Collector during the scan (mutually exclusive with `--otel-traces`) |

Dynamic analysis produces **Runtime Service Topology** graphs and **Call Sequence Diagrams** in reports. Without trace data, Band 3 rules are skipped and all static analysis still runs normally.

See [dynamic-analysis.md](dynamic-analysis.md) for the full reference (trace format, CI integration, custom collector config, troubleshooting).

## Interaction baselines

Create and compare interaction baselines for production monitoring:

```bash
# Create a baseline from OTel trace data
nfr-review baseline create --otel-traces traces.ndjson -o baseline.json

# Diff production traces against a baseline
nfr-review baseline diff --baseline baseline.json --otel-traces prod-traces.ndjson
```

## Production monitor

Start a long-lived OTLP HTTP receiver that compares incoming production traces against a UAT baseline and emits JSON alerts for novel interactions:

```bash
nfr-review monitor --baseline baseline.json --port 4318
```

Requires the `[monitor]` extra (`pip install nfr-review[monitor]`).

See [monitor-deployment.md](monitor-deployment.md) for deployment configuration and alerting setup.
