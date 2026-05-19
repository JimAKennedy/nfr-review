# Patching Telemetry Standard

**Purpose:** Define the minimum observability contract a service must satisfy to be patched under the ringed model. This standard exists because a ring is only safe if its signal is trustworthy. Telemetry parity across rings is the foundation; without it, ring promotion decisions are guesswork.

**Audience:** Service owners, platform telemetry team, SDLC platform team.

**Companion to:** Patching Readiness Guardrails, Ring Promotion Runbook.

---

## 1. Principles

1. **Parity over richness.** It is more important that every ring emits the same signals in the same shape than that any one ring is exquisitely instrumented.
2. **Signal must reflect user-visible health.** A green dashboard while users are failing is worse than no dashboard at all.
3. **Labels are part of the contract.** A signal without consistent labels (service, ring, side, version) cannot be compared and is operationally useless for patch decisions.
4. **The service owns the signal; the platform owns the pipeline.** The platform provides ingestion, storage, and dashboards. The service is responsible for emitting correctly and for the meaning of what it emits.

## 2. Required signals

Every service onboarded to the patching pipeline emits the following. These are the minimum; services with stricter operational requirements emit more.

### 2.1 Golden signals

| Signal | Definition | Cardinality |
|---|---|---|
| `request_rate` | Inbound requests per second to the service's public surface | Per endpoint or endpoint class |
| `error_rate` | Requests resulting in 5xx, unhandled exception, or business-error-equivalent | Per endpoint or endpoint class |
| `latency` | Wall-clock latency of inbound requests, with p50, p95, p99 percentiles | Per endpoint or endpoint class |
| `saturation` | Resource pressure — at minimum CPU, heap, connection pool utilisation | Per instance |

For asynchronous or message-driven services, the analogues are: message consumption rate, processing error rate, end-to-end latency from publish to commit, queue depth and consumer lag.

### 2.2 Dependency signals

| Signal | Definition |
|---|---|
| `downstream_call_rate` | Outbound calls to each declared downstream, per dependency |
| `downstream_error_rate` | Failures from each downstream, per dependency |
| `downstream_latency` | Latency to each downstream, p95 and p99 |
| `circuit_breaker_state` | Open/half-open/closed state for each protected dependency, where applicable |

### 2.3 Lifecycle signals

| Signal | Definition |
|---|---|
| `instance_start` | Event emitted on application startup, with version label |
| `instance_ready` | Event emitted when readiness probe first passes |
| `instance_drain` | Event emitted when drain begins |
| `restart_count` | Cumulative restart count per instance, per pod |

These are essential during patching because they reveal restart storms, slow startups, and instances that report ready before they actually are.

### 2.4 Business signal (per service)

Every service declares at least one **business KPI** that reflects whether its users are being served. Examples: orders placed, payments authorised, drum patterns generated, models served. The KPI is emitted with the same labels as the golden signals so it can be compared across rings.

A service that cannot articulate a business KPI cannot tell whether a patch broke anything that matters; this is itself a readiness gap.

### 2.5 Synthetic transaction signal

Every service runs at least one synthetic business transaction continuously, exercising its critical user journey end-to-end. The synthetic emits:

| Signal | Definition |
|---|---|
| `synthetic_success` | Boolean per execution |
| `synthetic_latency` | End-to-end latency of the synthetic |
| `synthetic_step_failure` | Where in the journey a failure occurred, if any |

Synthetics run in every ring, including production. A synthetic that only runs in non-production is decorative.

## 3. Mandatory labels

Every metric, log, and trace span carries the following labels with consistent names and casing:

| Label | Values | Purpose |
|---|---|---|
| `service` | Service registry identifier | Identity |
| `version` | Build SHA or semver of the running artefact | Tells you which version is reporting |
| `ring` | `r0`, `r1`, `r2`, `r3` | Locates the signal in the ring topology |
| `side` | `active`, `passive`, or `n/a` for non-hot-hot | Locates the signal in the DR topology |
| `region` | Cloud region identifier | Geographic locator |
| `environment` | `prod`, `nonprod` | Coarse partition |
| `patch_wave` | Wave identifier, when set | Correlates signal to a specific patch wave |

Labels with inconsistent casing or naming across services break dashboards. The platform team publishes the canonical label schema and validates emission via the telemetry pipeline.

## 4. Probes

### 4.1 Liveness probe

Returns success only while the process is in a state that warrants continued running. Returns failure when the process is wedged in a way only a restart will fix. **Liveness does not check downstream dependencies** — a downstream outage should not trigger a restart loop.

### 4.2 Readiness probe

Returns success only when the instance can serve real traffic. **Readiness does check critical local dependencies**: database connection pool initialised, required caches warm, configuration loaded, license/secret material present. An instance that returns ready while its connection pool is empty fails this standard.

### 4.3 Startup probe (where applicable)

For services with non-trivial startup time, a startup probe protects against premature liveness checks during boot. The startup-probe duration is documented; an undocumented startup time prevents the platform from sizing surge correctly during patching.

## 5. Dashboards

Every service has a **ring comparison dashboard** that the platform team can open during a patch wave. The dashboard:

- Shows the golden signals and the business KPI for each ring side-by-side.
- Defaults to the last soak window of the active wave when one is in progress.
- Highlights divergence between the patched ring and the comparator (unpatched ring or pre-patch baseline).
- Links to the service's runbook, on-call rotation, and rollback procedure.

The platform team provides a templated dashboard. Services may customise but must not remove the required panels.

## 6. Alerting during patch waves

In addition to standard alerting, services in an active patch wave have **wave-scoped alerts**:

| Alert | Trigger |
|---|---|
| Patched-ring error budget burn | Burn rate >2× baseline over a 30-minute window |
| Latency divergence | p95 in patched ring exceeds unpatched ring by the acceptance band in the promotion runbook |
| Synthetic failure | Two consecutive synthetic failures in the patched ring |
| Restart storm | Restart count in patched ring exceeds 3× unpatched ring over a 15-minute window |
| Failover regression (hot-hot only) | Failover or failback duration exceeds the documented bound |

Wave-scoped alerts route to the wave coordinator and the service on-call. They are silenced automatically when the wave closes.

## 7. Validation

Onboarding to the patching pipeline includes a telemetry conformance check:

1. The platform team verifies the service emits all required signals with required labels.
2. The platform team verifies the ring comparison dashboard renders and is populated.
3. The platform team verifies the synthetic transaction runs successfully in every target ring.
4. The platform team verifies wave-scoped alerts fire when synthesised against historical incident data.

Conformance is re-checked annually and on material architecture change.

## 8. Anti-patterns

The following are explicit failures of this standard:

- **Ring-inconsistent labels.** Service emits `ring=R1` in one place and `ring=ring1` elsewhere. Dashboards then lie.
- **Synthetic in non-prod only.** The production canary is unmonitored.
- **Liveness that checks downstreams.** A downstream blip triggers restart loops that masquerade as a bad patch.
- **Readiness that returns 200 unconditionally.** The pod is "ready" while the database isn't reachable.
- **Business KPI that lags by hours.** The patch wave is over before the KPI moves; the signal is useless for decision-making.
- **Dashboard with no comparator.** A single ring shown in isolation provides no basis for promotion.
- **Telemetry that requires manual aggregation across rings.** The promotion call cannot start because someone is still pivoting a spreadsheet.

## 9. Evolution

This standard is owned by the platform telemetry team in consultation with the SDLC platform team. Amendments follow the standard change process. Material additions (new required signals or labels) are introduced with a transition window of at least one quarter for already-onboarded services.

---

*The signal is the contract. If the signal isn't there, the patch isn't ringed — it's just rolled out slowly.*
