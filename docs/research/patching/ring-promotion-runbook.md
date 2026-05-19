# Ring Promotion Runbook

**Purpose:** Define the operational procedure for promoting a patch from one ring to the next. This runbook is invoked once per ring boundary during a patch wave and produces an auditable promotion decision.

**Audience:** Patch wave coordinator (SDLC platform team), service on-call (for services in the ring being promoted), change approver.

**Companion to:** Patching Readiness Guardrails.

---

## 1. Roles for a promotion event

| Role | Responsibility |
|---|---|
| Patch wave coordinator | Owns the wave end-to-end; calls go/no-go |
| Service on-call (per service) | Confirms service-level health signal; authorised to veto promotion for their service |
| Platform SRE | Confirms shared-infrastructure health (AKS nodes, Postgres, APIM) |
| Change approver | Signs off the promotion as a change record |
| Security representative | Required for accelerated-cadence security patches; optional otherwise |

A promotion decision is taken **collectively**. The coordinator does not promote unilaterally.

## 2. Pre-promotion checks

Before opening a promotion decision, the coordinator confirms:

- The patched ring has completed its minimum soak (per the guardrails table, or the accelerated-cadence schedule for the patch class).
- All services in the patched ring have reported a green health attestation for the soak window.
- No active P1/P2 incidents are open against any service in the patched ring.
- No active P1/P2 incidents are open against shared infrastructure consumed by the next ring.
- The change window for the next ring is open and approved.
- Rollback artefacts for the next ring are staged and accessible.

If any item is not satisfied, the promotion is **deferred**, not overridden. Deferral reasons are logged.

## 3. Health evidence — what counts

A clean soak alone is not evidence. The coordinator requires positive signal across four dimensions for the patched ring, compared against the equivalent unpatched ring or the pre-patch baseline.

### 3.1 Golden signals (per service)

| Signal | Acceptance |
|---|---|
| Error rate (5xx, exceptions) | Within ±10% of baseline, no sustained spike |
| Latency p95 | Within +15% of baseline |
| Latency p99 | Within +25% of baseline |
| Traffic (RPS / messages/sec) | Within expected envelope for the time-of-day |
| Saturation (CPU, heap, connection pool, queue depth) | No new sustained saturation event |

Acceptance bands are defaults. Services with stricter SLOs declare tighter bands in their telemetry standard registration.

### 3.2 Business signal

- At least one synthetic business transaction has executed successfully throughout the soak window for the service's critical user journey.
- Real business KPIs (transaction volume, conversion, etc., where instrumented) do not show divergence between patched and unpatched rings.

### 3.3 Infrastructure signal

- AKS node restart count, pod restart count, and OOMKill count are not elevated.
- Postgres connection pool, replication lag, and slow-query rate are within baseline.
- APIM and service-mesh error rates are within baseline.

### 3.4 Failover signal (hot-hot services only)

- The patched side has carried representative live traffic for the defined validation window.
- A failback from patched to unpatched, and forward again to patched, has succeeded.
- If failover is automated, the automation has fired at least once successfully during the soak. If it has not (because nothing forced it), a manual failover test is run.

## 4. Promotion decision

The coordinator convenes a brief promotion call (15 min target) with the roles in §1. The decision is one of:

- **Promote** — all signals green, all services attest, change approved. Proceed.
- **Hold** — at least one signal amber. Extend soak by a defined increment (default 24h). Re-convene.
- **Roll back** — at least one signal red, or a service on-call vetoes. Invoke rollback per the service's rehearsed procedure.
- **Defer** — a pre-promotion check failed. No decision on the patch itself.

Decisions are recorded in the wave's promotion log with: timestamp, signals reviewed, dissenting voices, and a one-line rationale.

## 5. Service on-call veto

Any service on-call may veto promotion for their service. A veto:

- Holds promotion *for that service* without blocking the wave for others, unless cross-service dependencies require coupling.
- Requires a written reason within 24h.
- Triggers a follow-up review to either (a) resolve the concern and re-attempt promotion, or (b) roll the service back from the patched ring.

A veto is not a failure. It is the mechanism that makes the guardrails real.

## 6. Accelerated cadence for security patches

For patches classed as **Critical security** (CVSS ≥ 9 or KEV-listed with active exploitation):

- Soak windows compress to the minimum the telemetry signal supports — typically 4–8h per ring.
- The signal requirements in §3 do **not** relax. If signal coverage is insufficient at compressed soak, the compression is rejected and the patch follows standard cadence with risk acceptance documented.
- A security representative joins the promotion call.
- The wave is communicated to leadership at the start, not at the end.

Speed is bought with attention, not by removing checks.

## 7. Promotion artefacts

For each promotion decision, the wave's promotion log captures:

- Wave ID, patch identifier, ring transition (e.g. R1 → R2).
- Timestamp and attendees.
- Snapshot or link to the dashboards reviewed.
- Decision and rationale.
- Any vetoes or dissents.
- Next checkpoint timestamp.

The log is retained for the lifecycle of the patched components plus audit retention.

## 8. Failure scenarios and responses

| Scenario | Response |
|---|---|
| Telemetry pipeline degraded — signals unreliable | Hold all promotions until telemetry is restored. A patch wave does not proceed blind |
| Single service amber, others green | Hold that service only; consider promoting the rest if no cross-service coupling |
| Shared-infrastructure signal amber | Hold the entire wave; investigate before any further promotion |
| Service rolled back at one ring | Re-evaluate that service's readiness attestation before re-attempting in the next wave |
| Conflicting signals (e.g. latency up, error rate down) | Default to hold; investigate before promoting |
| Failover test fails during soak | Roll back the patched side; do not promote |

## 9. After the wave

Within 5 working days of the wave completing (or being abandoned):

- The coordinator produces a wave retrospective covering: what shipped, what held, what rolled back, what surprised us, what to change in the next wave.
- Guardrail amendments or telemetry-standard amendments arising from the wave are proposed via the standard change process.
- Service readiness attestations are updated where the wave revealed gaps.

---

*The aim of this runbook is to make promotion decisions evidence-based and auditable. If a promotion is happening without reference to this document, the guardrails are not in force.*
