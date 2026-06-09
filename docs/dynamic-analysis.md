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

---

## Table of contents

1. [Quick start](#1-quick-start)
2. [Using pre-collected traces](#2-using-pre-collected-traces)
3. [Using the managed collector](#3-using-the-managed-collector)
4. [Trace file format](#4-trace-file-format)
5. [Band 3 rules](#5-band-3-rules)
6. [CI integration](#6-ci-integration)
7. [Troubleshooting](#7-troubleshooting)

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

## 2. Using pre-collected traces

Pass a trace file with `--otel-traces`:

```bash
nfr-review run /path/to/repo --otel-traces /path/to/traces.ndjson
```

The file must be in OTLP JSON format — either a single JSON object with a
top-level `resourceSpans` array, or newline-delimited JSON (NDJSON) where
each line is an OTLP export batch. See [Trace file format](#4-trace-file-format)
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

## 3. Using the managed collector

The `--collector` flag tells nfr-review to start an OTel Collector subprocess
before the scan and stop it afterwards. Collected traces are automatically fed
to Band 3 rules.

```bash
nfr-review run /path/to/repo --collector
```

### Prerequisites

An OTel Collector binary must be on your `$PATH`. nfr-review searches for
`otelcol-contrib` first, then `otelcol`.

**macOS (Homebrew):**

```bash
brew install open-telemetry/opentelemetry-collector/opentelemetry-collector-contrib
```

**Linux (apt):**

```bash
# See https://opentelemetry.io/docs/collector/installation/
sudo apt-get install otelcol-contrib
```

**Docker / CI:** Install the binary in your CI image or download it as a
workflow step. See [CI integration](#6-ci-integration) for a GitHub Actions
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
point to the temp trace file. Your config must use this variable in the
file exporter path.

### Mutually exclusive flags

`--collector` and `--otel-traces` cannot be used together. Use
`--otel-traces` when you already have a trace file; use `--collector` when
you want nfr-review to capture traces during the scan.

---

## 4. Trace file format

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

## 5. Band 3 rules

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

## 6. CI integration

### Pre-collected traces in CI

The simplest CI approach is to collect traces during your test suite and
pass the file to nfr-review:

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

      - uses: actions/setup-python@v5
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
        uses: actions/upload-artifact@v4
        with:
          name: nfr-dynamic-report
          path: "*-nfr-review-report.*"
```

### Managed collector in CI

For integration tests that emit traces at runtime:

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

## 7. Troubleshooting

### "OTel Collector binary not found on PATH"

Install `otelcol-contrib` or `otelcol` and ensure it is on your `$PATH`.
See [Prerequisites](#prerequisites) for installation instructions.

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
