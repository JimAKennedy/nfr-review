<!-- Copyright 2026 nfr-review contributors — Licensed under Apache-2.0 -->

# Dynamic Analysis

nfr-review includes **Band 3 dynamic analysis** rules that evaluate runtime
behaviour captured in OpenTelemetry (OTel) traces. These rules detect latency
hotspots, N+1 query patterns, missing trace correlation, and service coverage
gaps that static analysis cannot find.

Dynamic analysis produces two additional report sections:

- **Runtime Service Topology** — a Mermaid graph showing services and their
  call relationships, derived from parent-child span links across service
  boundaries.
- **Call Sequence Diagrams** — Mermaid sequence diagrams embedded in findings
  that illustrate specific interaction patterns (e.g. N+1 loops).

> **Related:** nfr-review also provides a [Production Interaction Monitor](monitor-deployment.md)
> (EXPERIMENTAL) that continuously compares live production traces against a
> UAT baseline. The monitor builds on the same OTel trace parsing but runs as
> a long-lived HTTP server rather than a one-shot scan.

---

## Table of contents

1. [Quick start](#1-quick-start)
2. [Installation](#2-installation)
3. [Using pre-collected traces](#3-using-pre-collected-traces)
4. [Using the managed collector](#4-using-the-managed-collector)
5. [Collector configuration](#5-collector-configuration)
6. [Trace file format](#6-trace-file-format)
7. [Band 3 rules](#7-band-3-rules)
8. [End-to-end workflow](#8-end-to-end-workflow)
9. [CI integration](#9-ci-integration)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Quick start

The fastest way to try dynamic analysis is with a pre-collected trace file:

```bash
# Scan a repo with a trace file
nfr-review run /path/to/repo --otel-traces traces.ndjson

# Full report with PDF and dynamic diagrams
nfr-review report /path/to/repo --otel-traces traces.ndjson
```

If you have an OTel Collector binary installed, nfr-review can manage it
automatically:

```bash
# Start a collector, capture traces during the scan, and stop it
nfr-review run /path/to/repo --collector
```

---

## 2. Installation

Dynamic analysis is included in the base `nfr-review` package. No extra
dependencies are needed for trace parsing or Band 3 rule evaluation.

```bash
pip install nfr-review
```

Two optional extras are available for OTel-related workflows:

| Extra | What it adds | When to install |
|-------|-------------|-----------------|
| `[otel]` | OpenTelemetry API, SDK, and OTLP exporter bindings | You want to instrument your own tests to emit traces that nfr-review can consume |
| `[monitor]` | aiohttp for the production interaction monitor | You want to run `nfr-review monitor` (see [Production Monitor](monitor-deployment.md)) |

```bash
# Install with the OTel SDK (for trace generation in tests)
pip install "nfr-review[otel]"

# Install with the monitor extra (for production topology monitoring)
pip install "nfr-review[monitor]"

# Install everything
pip install "nfr-review[full]"
```

For managed collector mode (`--collector`), you also need the `otelcol-contrib`
binary on your `$PATH`. See [Using the managed collector](#4-using-the-managed-collector)
for installation instructions.

For full installation details including Docker and GitHub Actions setup,
see the [Install guide](install.md).

---

## 3. Using pre-collected traces

Pass a trace file with `--otel-traces`:

```bash
nfr-review run /path/to/repo --otel-traces /path/to/traces.ndjson
```

The file must be in OTLP JSON format — either a single JSON object with a
top-level `resourceSpans` array, or newline-delimited JSON (NDJSON) where
each line is an OTLP export batch. See [Trace file format](#6-trace-file-format)
for details.

This mode works with both `run` and `report` commands.

### Collecting traces from a running application

Most OpenTelemetry SDKs can export spans to a file. For example, with a
Spring Boot application using Micrometer + OTLP:

```yaml
# application.yaml
management:
  otlp:
    tracing:
      endpoint: http://localhost:4318/v1/traces
```

Run the OTel Collector with a file exporter, exercise the application, then
pass the output file to nfr-review:

```bash
otelcol-contrib --config collector-config.yaml &
# ... exercise the application ...
kill %1
nfr-review run /path/to/repo --otel-traces /tmp/otel-traces.ndjson
```

Or use the managed collector (next section) to automate this.

---

## 4. Using the managed collector

The `--collector` flag tells nfr-review to start an OTel Collector subprocess
before the scan and stop it afterwards. Collected traces are automatically fed
to Band 3 rules.

```bash
nfr-review run /path/to/repo --collector
```

### Prerequisites

An OTel Collector binary must be on your `$PATH`. nfr-review searches for
`otelcol-contrib` first, then `otelcol`.

**macOS / Linux (setup script):**

```bash
# Automatically downloads the correct binary for your platform
scripts/setup-all.sh
```

**Manual download:**

```bash
# Download from GitHub releases (pick your OS/arch):
# https://github.com/open-telemetry/opentelemetry-collector-releases/releases
```

**Linux (apt):**

```bash
# See https://opentelemetry.io/docs/collector/installation/
sudo apt-get install otelcol-contrib
```

**Docker / CI:** Install the binary in your CI image or download it as a
workflow step. See [CI integration](#9-ci-integration) for a GitHub Actions
example.

### How it works

1. nfr-review locates the collector binary on `$PATH`.
2. It checks the target repo for an `otel-collector-config.yaml` file. If
   none exists, it uses the bundled default config.
3. A temp file is created for trace output.
4. The collector starts, listening on `0.0.0.0:4317` (gRPC) and
   `0.0.0.0:4318` (HTTP).
5. The scan runs. Any instrumented application sending traces to
   `localhost:4317` or `localhost:4318` will have its spans captured.
6. After the scan, nfr-review sends SIGTERM to the collector and waits up
   to 10 seconds for graceful shutdown.
7. The captured traces are fed to Band 3 dynamic analysis rules.

If the collector binary is not found, nfr-review logs a warning and
continues without dynamic trace collection — the scan still produces all
static analysis findings.

### Mutually exclusive flags

`--collector` and `--otel-traces` cannot be used together. Use
`--otel-traces` when you already have a trace file; use `--collector` when
you want nfr-review to capture traces during the scan.

---

## 5. Collector configuration

nfr-review ships a bundled default collector config at
`src/nfr_review/data/otel-collector-config.yaml`. This config receives OTLP
traces over both gRPC (port 4317) and HTTP (port 4318), applies a memory
limiter and batching processor, and writes spans to a local NDJSON file.

The bundled default:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 256
  batch:
    timeout: 5s
    send_batch_size: 512

exporters:
  file:
    path: "${NFR_TRACE_OUTPUT_PATH}"
    format: json

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [file]
```

### Custom collector config

Place an `otel-collector-config.yaml` in the target repository root to
override the bundled default. The config must include at minimum:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

exporters:
  file:
    path: "${NFR_TRACE_OUTPUT_PATH}"
    format: json

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [file]
```

The `NFR_TRACE_OUTPUT_PATH` environment variable is set by nfr-review to
point to the temp trace file. Your config **must** use this variable in the
file exporter path — without it, nfr-review will not find the captured
traces.

You can add extra processors (e.g. `filter`, `attributes`), additional
receivers, or change the batch size, but the file exporter with the
`NFR_TRACE_OUTPUT_PATH` variable is required.

---

## 6. Trace file format

nfr-review accepts two OTLP JSON formats:

### Single JSON object

A single JSON object with a `resourceSpans` array:

```json
{
  "resourceSpans": [
    {
      "resource": {
        "attributes": [
          {"key": "service.name", "value": {"stringValue": "order-service"}}
        ]
      },
      "scopeSpans": [
        {
          "spans": [
            {
              "traceId": "abc123...",
              "spanId": "def456...",
              "name": "GET /api/orders",
              "kind": 2,
              "startTimeUnixNano": "1700000000000000000",
              "endTimeUnixNano": "1700000000500000000",
              "attributes": [],
              "status": {"code": 1}
            }
          ]
        }
      ]
    }
  ]
}
```

### Newline-delimited JSON (NDJSON)

Each line is a separate OTLP export batch. This is the format produced by
the OTel Collector file exporter:

```
{"resourceSpans":[...]}
{"resourceSpans":[...]}
```

### Span kind values

| Value | Kind |
|-------|------|
| 0 | Unspecified |
| 1 | Internal |
| 2 | Server |
| 3 | Client |
| 4 | Producer |
| 5 | Consumer |

### Status code values

| Value | Status |
|-------|--------|
| 0 | Unset |
| 1 | OK |
| 2 | Error |

---

## 7. Band 3 rules

Band 3 rules analyse OTel trace data. They require either `--otel-traces`
or `--collector` to activate. Without trace data, these rules are skipped.

| Rule | What it detects |
|------|----------------|
| Latency hotspots | Spans with P95 duration exceeding thresholds |
| N+1 query patterns | Repeated child spans suggesting unbatched database calls |
| Trace correlation gaps | Services missing trace context propagation |
| Service coverage | Services present in code but absent from traces |

Band 3 rules produce findings with the same severity scale as static rules
and appear in all output formats (CSV, JSONL, SARIF, Markdown, PDF).

---

## 8. End-to-end workflow

This section walks through the full dynamic analysis lifecycle: start a
collector, exercise your application, stop the collector, and run nfr-review
against the captured traces.

### With managed collector (simplest)

```bash
# 1. Start your instrumented application in the background
./gradlew bootRun &
APP_PID=$!
sleep 10  # wait for startup

# 2. Run nfr-review with managed collector — it starts the collector,
#    waits for the scan to complete, then stops the collector
nfr-review report /path/to/repo --collector

# 3. Stop your application
kill $APP_PID
```

nfr-review handles the collector lifecycle automatically. The report includes
all static findings plus Band 3 dynamic analysis findings.

### With pre-collected traces (manual control)

When you need more control over the collection process — for example, to run
a specific test suite or replay a load test — collect traces manually and
pass the file to nfr-review:

```bash
# 1. Start the OTel Collector with a file exporter
export NFR_TRACE_OUTPUT_PATH=/tmp/otel-traces.ndjson
otelcol-contrib --config otel-collector-config.yaml &
COLLECTOR_PID=$!

# 2. Start your instrumented application
./gradlew bootRun &
APP_PID=$!
sleep 10

# 3. Exercise the application (run tests, replay traffic, etc.)
./gradlew integrationTest

# 4. Stop the application and collector
kill $APP_PID
kill $COLLECTOR_PID
wait $COLLECTOR_PID

# 5. Run nfr-review with the captured trace file
nfr-review report /path/to/repo --otel-traces /tmp/otel-traces.ndjson
```

### Interpreting results

Band 3 findings appear alongside static analysis findings in all output
formats (CSV, JSONL, SARIF, Markdown, PDF). The report also includes:

- A **Runtime Service Topology** diagram showing observed service-to-service
  call relationships.
- **Call Sequence Diagrams** embedded in findings that detected problematic
  patterns (e.g. N+1 query loops).

Use `-v` (verbose) to see detailed trace parsing and rule evaluation logs.

---

## 9. CI integration

### Pre-collected traces in CI

The simplest CI approach is to collect traces during your test suite and
pass the file to nfr-review. A complete example workflow is available at
[`docs/examples/nfr-review-dynamic.yml`](examples/nfr-review-dynamic.yml).

Copy this file to `.github/workflows/nfr-review-dynamic.yml` in your
repository and adjust the `--otel-traces` path to point to your trace file.

```yaml
# .github/workflows/nfr-review-dynamic.yml
name: NFR Review (dynamic analysis)
on:
  push:
    branches: [main]
  schedule:
    - cron: "0 3 * * *"

permissions:
  contents: read

jobs:
  dynamic-analysis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6

      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install nfr-review
        run: pip install "nfr-review[pdf]"

      - name: Run dynamic analysis with pre-collected traces
        run: |
          nfr-review report . \
            --otel-traces tests/fixtures/traces/sample-traces.ndjson

      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: nfr-dynamic-report
          path: |
            *-nfr-review-report.md
            *-nfr-review-report.pdf
          retention-days: 30
```

### Managed collector in CI

For integration tests that emit traces at runtime, install the collector
binary and use the `--collector` flag:

```yaml
      - name: Install OTel Collector
        run: |
          curl -fsSL https://github.com/open-telemetry/opentelemetry-collector-releases/releases/latest/download/otelcol-contrib_linux_amd64.tar.gz \
            | tar xz -C /usr/local/bin/ otelcol-contrib

      - name: Start application and run dynamic scan
        run: |
          # Start your instrumented app in the background
          ./gradlew bootRun &
          sleep 10  # wait for startup

          # Run nfr-review with managed collector
          nfr-review run . --collector -v

          # Stop the app
          kill %1
```

---

## 10. Troubleshooting

### "OTel Collector binary not found on PATH"

Install `otelcol-contrib` or `otelcol` and ensure it is on your `$PATH`.
See [Using the managed collector](#4-using-the-managed-collector) for
installation instructions.

When the binary is not found, nfr-review continues without dynamic trace
collection. All static analysis rules still run.

### No dynamic diagrams in the report

- Verify your trace file is not empty and contains valid OTLP JSON.
- Check that spans include `service.name` resource attributes — the
  topology graph requires service names to build nodes.
- Use `-v` (verbose) to see trace parsing details in the log output.

### Collector starts but no traces are captured

- Ensure your application is sending traces to `localhost:4317` (gRPC) or
  `localhost:4318` (HTTP) while nfr-review is scanning.
- The collector only runs during the scan. If your application takes time
  to start, consider using `--otel-traces` with a pre-collected file
  instead.

### Band 3 rules produce no findings

Band 3 rules need sufficient trace data to detect patterns. A trace file
with only a few spans may not trigger latency or N+1 detection thresholds.
Exercise your application with realistic workloads to produce meaningful
trace data.
