# Rollback Rehearsal Template

**Purpose:** Provide a structured artefact that service teams complete to evidence a rollback rehearsal. A completed rehearsal record is the evidence required by the Patching Readiness Guardrails for the "rollback rehearsed within 180 days" guardrail.

**Audience:** Service owners, on-call engineers, SDLC platform team (as evidence reviewer).

**How to use this template:** Copy this file into the service's repository under `docs/rollback-rehearsals/YYYY-MM-DD-rehearsal.md` and complete every section. An empty or "N/A"-padded section invalidates the rehearsal.

**Companion to:** Patching Readiness Guardrails, Ring Promotion Runbook.

---

## 1. Rehearsal identity

| Field | Value |
|---|---|
| Service name | _e.g. drum-generator-api_ |
| Service version at rehearsal start | _build SHA or semver_ |
| Target rollback version | _build SHA or semver_ |
| Date and time of rehearsal | _ISO 8601_ |
| Environment | _non-prod / DR / pre-prod_ |
| Patch class being simulated | _OS / JDK / container image / Postgres minor / AKS node / app version_ |
| Rehearsal lead | _name and role_ |
| Observers | _names and roles_ |

A rehearsal in production is permitted but must be planned as a controlled exercise, not an opportunistic one.

## 2. Scenario

Describe the failure scenario the rehearsal simulates. Examples:

- A bad JDK patch causes a class of requests to fail with a serialisation error 20 minutes after promotion to R2.
- A container image patch introduces a memory leak that becomes visible after 90 minutes of soak.
- A Postgres minor patch breaks a specific stored procedure on rollback only.
- An AKS node image patch causes pod scheduling failures on a subset of nodes.

The scenario must be specific. "A bad patch happens" is not a scenario.

| Field | Value |
|---|---|
| Scenario description | |
| Signal that would trigger rollback | _which alert, which dashboard panel, which user report_ |
| Time-to-detect target | _from defect introduction to alert fire_ |
| Time-to-rollback target | _from decision to service restored_ |

## 3. Pre-rehearsal state

Capture the system state at the start of the rehearsal. This baseline is what "rolled back" must restore to.

| Field | Value |
|---|---|
| Running version | |
| Active configuration revision | |
| Database schema version | |
| Feature flag state (relevant flags) | |
| Outstanding background jobs / migrations | |
| Synthetic transaction baseline (success rate, latency) | |
| Hot-hot side serving traffic | _active / passive / both_ |

## 4. Rollback procedure executed

Walk through the procedure as executed. This section is the heart of the rehearsal — it forces the team to confront whether the documented procedure actually works.

| Step | Action | Owner | Expected duration | Actual duration | Notes |
|---|---|---|---|---|---|
| 1 | _e.g. Decision to roll back recorded in incident channel_ | | | | |
| 2 | _e.g. Pipeline `redeploy-previous` triggered with version X_ | | | | |
| 3 | _e.g. Traffic drained from patched side via service mesh_ | | | | |
| 4 | _e.g. Rollback artefact promoted to AKS_ | | | | |
| 5 | _e.g. Readiness verified across all instances_ | | | | |
| 6 | _e.g. Synthetic transaction confirmed green_ | | | | |
| 7 | _e.g. Traffic re-attached_ | | | | |
| 8 | _e.g. Post-rollback announcement_ | | | | |

Total wall-clock time from decision to restored service: _value_

## 5. Data and state implications

Rollback is rarely just "swap the binary." Document what else moved.

| Item | Implication | How handled |
|---|---|---|
| Database schema | _Backward compatible? Forward-only? Required reverse migration?_ | |
| Message formats | _In-flight messages compatible across versions?_ | |
| Cached data | _Stale on rollback? Invalidation required?_ | |
| Feature flags | _Reset to pre-patch state? Left as-is?_ | |
| Configuration | _Rolled back with the binary or independent?_ | |
| External integrations (APIM, identity, payments) | _Compatible across versions?_ | |

If any row reads "incompatible" or "cannot be reversed," the rollback is **one-way**. This is recorded in the service's readiness attestation and surfaced at every promotion gate.

## 6. Hot-hot considerations (if applicable)

For services deployed hot-hot, the rehearsal must exercise rollback while traffic is live on the other side.

| Field | Value |
|---|---|
| Side rolled back | _active / passive_ |
| Other side state during rollback | _serving / drained / patched / unpatched_ |
| Failover invoked as part of rollback? | _yes / no_ |
| Failback verified after rollback? | _yes / no_ |
| Cross-side compatibility during the rollback window | _verified / not applicable_ |

## 7. What worked

Record the parts of the procedure that performed as expected. This is not a courtesy — it is the evidence that the documented procedure matches reality.

## 8. What surprised us

Record every deviation from expectation, however small. Common surprises that this section tends to expose:

- A step in the documented procedure that no longer matches the pipeline.
- An access permission the on-call did not have.
- A dependency on a tool, dashboard, or person that wasn't available.
- A timing assumption that proved optimistic.
- A monitoring blind spot during the rollback window itself.

| Surprise | Impact | Action |
|---|---|---|
| | | |

## 9. Action items

Concrete follow-ups arising from the rehearsal, with owners and due dates. Items must be tracked in the team's normal backlog, not held in this document.

| Action | Owner | Due | Tracking ID |
|---|---|---|---|
| | | | |

## 10. Decision criteria validated

Confirm the forward-fix-vs-rollback decision criteria documented in the service's readiness attestation are still appropriate based on what the rehearsal revealed.

| Field | Value |
|---|---|
| Existing criteria still appropriate? | _yes / no_ |
| Proposed amendments | |

## 11. Attestation

| Field | Value |
|---|---|
| Rehearsal lead sign-off | _name, date_ |
| Service owner sign-off | _name, date_ |
| Platform team reviewer | _name, date_ |
| Evidence retained at | _link to recording, dashboard snapshot, pipeline run, or incident channel transcript_ |

A rehearsal without retained evidence is not a rehearsal for the purpose of the guardrail.

## 12. Validity

This rehearsal evidences the rollback guardrail until: _date 180 days from rehearsal_

A new rehearsal is required before that date, or sooner if any of the following occur:

- The service's deployment topology changes materially.
- The rollback pipeline or tooling changes materially.
- A real-incident rollback exposes a gap not covered here.
- A dependency that the rollback touches (database, message broker, identity provider) changes version or vendor.

---

*The point of a rehearsal is to find the gap before the incident does. A rehearsal that finds no gaps is either a flawless service or a shallow rehearsal — and the second is far more common than the first.*
