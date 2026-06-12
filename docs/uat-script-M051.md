# M051 UAT Script — Monitor Pipeline Test Framework

**Last updated:** 2026-06-12

This script covers acceptance testing for M051: the comprehensive monitor
pipeline test framework including trace factory, test harness, instrumented
test application, E2E scenario suite, and resilience tests.

---

## 0. Prerequisites

```bash
cd /path/to/nfr-review
pip install -e ".[dev]"
python -c "import opentelemetry; print(opentelemetry.__version__)"
# Expected: 1.x.x (OTel SDK installed as dev dependency)
```

---

## 1. Trace Factory (S01)

The trace factory generates deterministic OTLP JSON payloads from topology
specifications without requiring live services.

```bash
pytest tests/monitor/test_trace_factory.py -v
# Expected: 25 tests pass — topology validation, span structure,
# protocol attributes (all 6 types), fingerprint round-trip, NDJSON output
```

**Manual verification:**

```python
from tests.monitor.trace_factory import TraceFactory, TopologySpec, ServiceEdge

factory = TraceFactory(seed=42)
topo = TopologySpec(edges=[
    ServiceEdge("gateway", "orders", "GET /orders", "http"),
    ServiceEdge("orders", "inventory", "gRPC GetStock", "grpc"),
])
doc = factory.generate(topo)
print(f"Services: {len(doc['resourceSpans'])}")
# Expected: 3 resourceSpans (gateway, orders, inventory)
```

| Check | Expected |
|-------|----------|
| Seeded factory produces identical output across runs | `TraceFactory(seed=42)` is deterministic |
| All 6 protocols generate correct attributes | http, grpc, db, messaging, rpc, internal |
| `db` and `messaging` produce only CLIENT/PRODUCER spans (no SERVER) | Databases/brokers aren't instrumented services |

---

## 2. Test Harness (S02)

The harness wraps MonitorEngine lifecycle into a context manager for concise
tests.

```bash
pytest tests/monitor/test_harness.py -v
# Expected: 7 tests pass — lifecycle, healthz, known traffic,
# novel detection, mixed traffic, dedup on/off
```

**Key pattern:** A test using the harness is ~10 lines:

```python
async with MonitorHarness(baseline, tmp_path) as h:
    await h.send_traces(payload)
    await h.wait_for_flush()
    assert h.get_novel_alerts() == []
```

| Check | Expected |
|-------|----------|
| Harness binds to ephemeral port (port > 0) | No port conflicts |
| Healthz endpoint reachable at `h.base_url/healthz` | HTTP 200 |
| Known traffic produces zero novel alerts | Empty list |
| Novel traffic produces alert with correct service name | Alert summary contains callee name |

---

## 3. Instrumented Test Application (S03)

The test app runs 3 services in-process (gateway → orders → inventory) with
real OpenTelemetry SDK instrumentation.

```bash
pytest tests/monitor/test_testapp.py -v
# Expected: 10 tests pass — lifecycle, trace production, OTLP round-trip,
# NDJSON export, span clearing
```

| Check | Expected |
|-------|----------|
| All 3 services start on ephemeral ports | `test_app.ports` has gateway, orders, inventory |
| Gateway request produces ≥5 spans | Cross-service propagation works |
| Spans have correct service.name attributes | {gateway, orders, inventory} |
| OTLP doc parseable by `_parse_resource_spans()` | Round-trips through production parser |
| Fingerprints cover gateway→orders and orders→inventory | Both edges detected |

---

## 4. E2E Scenario Suite (S04)

Parameterized tests proving the full UAT→baseline→monitor→alert lifecycle.

```bash
pytest tests/monitor/test_scenarios.py -v
# Expected: 18 tests pass — all drift patterns covered
```

### Drift Detection Matrix

| Scenario | Test Class | Expected |
|----------|-----------|----------|
| New service appears | `TestNewServiceDetection` | Novel alert with service name |
| New endpoint on existing service | `TestNewEndpointDetection` | Novel alert with operation |
| Protocol change (HTTP→gRPC) | `TestProtocolChangeDetection` | Novel alert with protocol |
| Volume-only increase | `TestVolumeOnlyNoAlert` | Zero alerts |
| Known multi-service traffic | `TestZeroFalsePositives` | Zero alerts |
| Mixed known + novel | `TestMixedTraffic` | Only novel interactions alert |
| Severity by protocol | `TestSeverityByProtocol` | http/grpc/rpc=high, db/messaging=medium, internal=low |
| Real app E2E | `TestRealAppE2E` | App traces → baseline → factory novel → detected |
| Multi-window consistency | `TestMultiWindowConsistency` | Novel detected in correct window |

**Note:** Each cross-service edge produces dual fingerprints (CLIENT span with
protocol attributes, SERVER span with protocol=unknown). Severity assertions
check that the expected severity is _present_ among alerts, not that all
alerts match.

---

## 5. Resilience and Edge Cases (S05)

```bash
pytest tests/monitor/test_resilience_e2e.py -v
# Expected: 12 tests pass
```

| Scenario | Expected |
|----------|----------|
| Invalid JSON body | HTTP 400 |
| Empty resourceSpans | HTTP 200, no alerts |
| Missing scopeSpans.spans key | Handled gracefully |
| Minimal span fields | Accepted |
| Unknown top-level keys | Forward-compatible |
| 1000-fingerprint baseline | Novel still detected |
| Large baseline known traffic | Zero false positives |
| Same novel across 3 windows (dedup on) | Alerts only in first window |
| Different novels each alert once | No duplicates on replay |
| Dedup disabled | Alerts every window |
| Shutdown flushes pending spans | Alert emitted on shutdown |
| Stats endpoint | Reflects ingested span count |

---

## 6. Full Suite Run

```bash
# All monitor tests (fast, ~25s):
pytest tests/monitor/ -v

# Including test app E2E:
pytest tests/monitor/ tests/testapp/ -v

# CI equivalent (excludes regression):
pytest -n auto -m "not regression"
```

| Check | Expected |
|-------|----------|
| `pytest tests/monitor/ -v` | 109 tests pass |
| Wall time < 30s | All tests are fast (no network, no containers) |
| `pytest -n auto -m "not regression"` includes all monitor tests | No monitor tests excluded |

---

## CI Integration

- **PR CI** (`ci.yml`): Runs `pytest -n auto -m "not regression"` — all monitor tests included
- **Nightly** (`nfr-review-nightly.yml`): Runs full suite including regression and load tests
- **Coverage threshold**: 88% (monitor module contributes to overall coverage)
- **No special markers needed**: All monitor tests run in <30s total
