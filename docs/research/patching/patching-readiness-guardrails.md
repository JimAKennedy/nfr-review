# Patching Readiness Guardrails

**Purpose:** Assess whether an application or service is ready to be patched using a multi-ringed, DR-first (or canary-on-passive) approach. This document is a gate, not a checklist — a service that cannot satisfy these guardrails is not yet ready for safe progressive patching, and the remediation work should be tracked before the service is onboarded.

**Scope:** Applies to all services post-Mythos that consume the platform patching pipeline, including OS, runtime (JDK), container base image, AKS node pool, and Postgres minor-version patches.

**Owner:** SDLC Platform team (guardrail definition); Service owner (attestation and remediation).

---

## 1. Operating model

### 1.1 Ring topology

A minimum of four rings is expected. Services may justify fewer only with a documented platform-team exception.

| Ring | Purpose | Population | Default soak |
|---|---|---|---|
| R0 | Platform-internal validation | Synthetic + platform team workloads | 24h |
| R1 | Early adopter / pilot tenants | Low-criticality services, opt-in | 48h |
| R2 | Broad non-production + low-tier production | Tier 3/4 services | 72h |
| R3 | General production | Tier 1/2 services | Until next cycle |

Soak times are **minimums in the absence of signal**. A clean soak does not authorise promotion; positive evidence of health does.

### 1.2 DR-first / passive-side-first patching

For services deployed hot-hot across regions or AZs, the passive or lower-traffic side is patched first within each ring. Promotion to patch the active side requires:

- Successful traffic failover to the patched side under representative load.
- Steady-state observation on the patched side for the service's defined validation window.
- Explicit failback validation (the patched side can also accept failback).

Services that are nominally hot-hot but route <10% of steady-state traffic to one side are **not** considered hot-hot for this purpose and must declare a synthetic load strategy.

---

## 2. Readiness guardrails

Each guardrail is rated **Required** (must pass to onboard), **Expected** (must pass or have a tracked exception with expiry), or **Recommended** (improves safety, not gating).

### 2.1 Architectural readiness

- **[Required] Stateless or externalised state.** Application instances must not hold patch-relevant state on local disk or in-process beyond a single request lifecycle. Session, cache, and queue state must be externalised or reconstructible.
- **[Required] No singleton coupling.** The service must not depend on a single non-redundant instance of itself or a downstream component such that patching one node halts the system.
- **[Required] Schema and contract compatibility.** Database schema changes and API contracts must be backward-compatible across at least one patch version. Verified via Spring Cloud Contract / Pact in the existing test harness.
- **[Expected] Independent deployability of each ring.** The service can run mixed versions across rings simultaneously for the duration of the rollout without functional degradation.
- **[Expected] Idempotent startup and shutdown.** Restarts caused by patching do not produce duplicate side effects (duplicate messages, double-charged transactions, orphaned locks).

### 2.2 Health and observability contract

- **[Required] Liveness and readiness probes that reflect real health.** Probes must fail when the application cannot serve traffic, not merely when the process has crashed. A probe that returns 200 while the database connection pool is exhausted does not satisfy this guardrail.
- **[Required] Golden signals published.** Latency (p50/p95/p99), traffic, errors, and saturation must be emitted to the platform telemetry pipeline with consistent labels across rings.
- **[Required] Ring-aware dashboards.** A single view shows the same signals side-by-side across rings, so divergence after a ring promotion is visible within minutes, not discovered by users.
- **[Expected] Synthetic business transactions.** At least one end-to-end synthetic transaction exercising the critical user journey runs continuously in every ring, with alerting on failure.
- **[Expected] Defined SLOs and error budgets.** Promotion between rings is gated on the patched ring's error budget burn rate, not elapsed time alone.

### 2.3 Traffic management and failover

- **[Required] Documented failover mechanism.** For hot-hot services, the team must document how traffic is shifted between sides, the time it takes, and where the control point lives (DNS, service mesh, APIM, load balancer).
- **[Required] Tested failover within the last 90 days.** An untested failover path is assumed broken. Game-day evidence or an automated chaos test satisfies this.
- **[Expected] Drainable instances.** Patched instances can be drained gracefully (in-flight requests complete, no new connections) within a documented bound. Hard kills are a failure mode, not a strategy.
- **[Recommended] Progressive traffic shifting within a ring.** Even within a single ring, traffic to patched instances ramps (e.g. 1% → 10% → 50% → 100%) rather than cutting over instantly.

### 2.4 Rollback

- **[Required] Documented rollback procedure with a wall-clock estimate.** "Redeploy the previous version" is not a procedure. The document names the artefact, the command or pipeline, the data implications, and who is authorised to invoke it.
- **[Required] Rollback rehearsed in non-production within the last 180 days.** Rehearsal evidence is attached to the service's readiness record.
- **[Expected] Forward-fix vs rollback decision criteria.** The team has pre-agreed thresholds for when to roll back versus patch forward, removing the in-incident debate.
- **[Expected] Data compatibility for rollback.** If a patch involves a schema or message format change, rollback compatibility is verified. Otherwise the rollback is one-way and must be flagged as such at promotion time.

### 2.5 Dependencies and blast radius

- **[Required] Declared upstream and downstream dependencies.** The service registers what it calls and what calls it, so ring placement of dependents can be coordinated.
- **[Required] No cross-ring dependencies in the wrong direction.** A Ring 3 production service must not depend on a Ring 0/1 instance of another service for live traffic.
- **[Expected] Shared-fate analysis.** For services that share a database, a node pool, or a connection pool with others, the patch plan accounts for the shared-fate boundary — patching one does not silently destabilise the others.

### 2.6 Patch class scoping

Not every patch flows through every ring at the same pace. The service declares, per patch class, the minimum ring soak it requires:

| Patch class | Examples | Typical handling |
|---|---|---|
| Critical security (CVSS ≥ 9 / KEV-listed) | Active exploitation, RCE | Accelerated ring cadence with mandatory observability, never bypassed |
| High security | CVSS 7–8.9 | Standard cadence |
| Routine OS / runtime | Monthly Ubuntu, JDK CPU | Standard cadence |
| Postgres minor | Quarterly | Standard cadence with extra DR-first emphasis |
| AKS node image | Microsoft-driven | Coordinated with node pool surge settings |

Security urgency compresses cadence; it does not eliminate guardrails.

---

## 3. Attestation and exceptions

- Each service onboarding to the patching pipeline produces a **Patching Readiness Attestation** signed by the service owner and the SDLC platform team, referencing each guardrail above with: status, evidence link, and (where applicable) exception with expiry date.
- Exceptions are time-bound. There is no permanent exception to a **Required** guardrail; either the guardrail is met, or the service does not progress past R1.
- Attestations are revalidated annually or on material architecture change (new dependency, region added, state model changed).

## 4. Failure modes this guardrail is designed to prevent

This document exists because the following failure patterns recur in ringed-patching programmes elsewhere and should not recur here:

- **Time-based promotion without signal.** A ring "passed" because nobody looked, not because telemetry confirmed health.
- **Cold-hot masquerading as hot-hot.** DR side is patched, declared validated, but never carried real traffic.
- **Schema-bound rollback trap.** A patch ships a forward-only schema change; when the patch fails, rollback is unavailable and the incident extends by hours.
- **Singleton-on-the-critical-path.** A "redundant" service depends on a singleton config server, message broker, or identity provider that is patched without ringing.
- **Observability gap on the canary.** The canary ring has different telemetry plumbing from production, so problems only appear after broad rollout.
- **Untested failover.** The first time the failover is exercised in anger is during the patch — and it doesn't work.

## 5. Review and evolution

This guardrail document is owned by the SDLC platform team and reviewed quarterly. Service owners may propose amendments via the platform's standard change process. Material changes (adding or removing a Required guardrail) require platform leadership approval and a transition window for already-onboarded services.

---

*Companion documents: ring promotion runbook, patching telemetry standard, rollback rehearsal template, exception register.*
