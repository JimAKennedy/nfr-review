# Patching Guardrail Exception Register

**Purpose:** Provide the governance model and operational record for exceptions to the Patching Readiness Guardrails. Exceptions exist because the guardrails are ambitious and the estate is heterogeneous — but unmanaged exceptions are how guardrails decay into theatre. This document keeps exceptions visible, time-bound, and accountable.

**Audience:** SDLC platform team (register owner), service owners (exception requesters), platform leadership (approver for material exceptions).

**Companion to:** Patching Readiness Guardrails, Ring Promotion Runbook, Patching Telemetry Standard, Rollback Rehearsal Template.

---

## 1. Principles

1. **No permanent exceptions to Required guardrails.** A service either meets a Required guardrail or carries a time-bound exception with a remediation plan. There is no third option that allows indefinite production patching of a service that fails a Required guardrail.
2. **Exceptions are decisions, not status.** Every exception records who approved it, against what evidence, accepting what risk.
3. **Exceptions expire.** Every exception has an expiry date. At expiry, the exception is renewed (with fresh approval and justification), the guardrail is met, or the service is removed from the patching pipeline at its current ring.
4. **Exceptions are visible.** The register is open to engineering leadership and security. There is no quiet exception.
5. **Compensating controls are required.** An exception to a guardrail is not a removal of the risk it addresses; it is an acceptance of the risk with an alternative control in place. "We'll just be careful" is not a compensating control.

## 2. Exception classes

| Class | Definition | Approver | Maximum duration |
|---|---|---|---|
| Minor | Exception to a Recommended guardrail, or a short-term gap against an Expected guardrail with low blast radius | Service owner + platform team lead | 90 days |
| Standard | Exception to an Expected guardrail | Platform team lead + service owner's engineering manager | 180 days |
| Material | Exception to a Required guardrail, or any exception affecting a Tier 1 service | Platform leadership + service owner's engineering director + security representative | 90 days, renewable once |
| Emergency | Time-critical exception during an active incident or security event | Patch wave coordinator + on-call platform lead (retrospectively ratified within 5 working days) | 30 days |

A service with an open **Material** exception cannot be promoted past R2 until the exception is closed or the second renewal is approved.

## 3. Exception lifecycle

1. **Request.** Service owner submits a request via the platform's standard change process, referencing the specific guardrail, the gap, the proposed compensating control, the proposed expiry, and the remediation plan.
2. **Review.** Platform team reviews for completeness, risk classification, and adequacy of the compensating control.
3. **Approval.** Approver per the class table signs off. For Material exceptions, security and the engineering director must sign explicitly — not delegate.
4. **Registration.** The exception is added to this register and linked from the service's readiness attestation.
5. **Operational visibility.** The exception is surfaced on the service's ring comparison dashboard and on every pre-promotion check during a patch wave.
6. **Review at expiry.** Before the expiry date, the service owner presents either evidence that the guardrail is now met (exception closed), or a renewal request with updated justification.
7. **Closure.** When the underlying guardrail is met, the exception is closed and the closure is recorded.

## 4. What a valid compensating control looks like

A compensating control reduces, in a verifiable way, the risk that the guardrail was designed to manage. Examples:

| Guardrail not met | Acceptable compensating control | Not acceptable |
|---|---|---|
| Untested failover within 90 days | Reduced ring soak compression — service holds in each ring for double the standard window, with additional synthetic coverage | "We'll test it next quarter" |
| No tested rollback in 180 days | Pre-patch full backup of state + extended canary on a 5% traffic slice + named rollback executor on standby | "The pipeline has a rollback button" |
| Synthetic business transaction missing | Heightened real-traffic monitoring with manual review of business KPI at each ring boundary, plus shorter promotion windows | "The team will watch it" |
| Schema not backward-compatible | Patch deferred to a coordinated release with explicit data migration plan and read-only window | Proceeding with forward-only schema in a routine wave |
| Hot-hot service routes <10% to one side | Synthetic load generator runs against passive side during soak to validate under representative load | Patching passive side and declaring it validated without traffic |

A compensating control that cannot be evidenced is not a control.

## 5. Register entry template

Each entry in the register contains:

```
Exception ID:        EXC-YYYY-NNNN
Service:             <service name>
Service tier:        <1-4>
Guardrail:           <section reference and short name, e.g. §2.4 "Rollback rehearsed in non-prod within 180 days">
Class:               <Minor | Standard | Material | Emergency>
Status:              <Open | In remediation | Renewed | Closed | Expired-without-closure>

Requested by:        <name, role, date>
Approved by:         <names, roles, date>
Security review:     <required? signed by whom, date>

Gap description:     <what specifically is not met and why>
Risk accepted:       <plain-language description of the residual risk>
Compensating control: <what is in place instead, who operates it, how it is evidenced>

Remediation plan:    <concrete steps to close the exception>
Remediation owner:   <name>
Target close date:   <date>
Expiry date:         <date>

Renewals:            <count, with dates and re-approval evidence>
Closure evidence:    <link to evidence that the guardrail is now met, if closed>
Notes:               <anything else material>
```

The register itself is maintained as a structured document (spreadsheet, table, or database — the platform team's choice) with the entries above as fields. This template is the source of truth for what each entry must contain.

## 6. Reporting

The platform team publishes a quarterly report covering:

- Total open exceptions, by class and by service tier.
- Exceptions opened, renewed, and closed in the period.
- Exceptions approaching expiry within the next 30 days.
- Exceptions that **expired without closure** — the most important number in the report, because it measures whether the governance is working.
- Patterns: guardrails most frequently exceptioned, services with the most open exceptions, common root causes.

The report goes to platform leadership and security. Persistent patterns drive guardrail amendments or targeted remediation programmes — they do not drive guardrail relaxation by default.

## 7. Expired-without-closure handling

If an exception reaches its expiry without being closed or renewed:

1. The service is **automatically held** at its current ring on the next patch wave.
2. The service owner and their engineering manager are notified within 24 hours.
3. A grace period of 10 working days is granted to either renew the exception with proper approval or close it by meeting the guardrail.
4. If the grace period elapses without action, the service is **removed from the patching pipeline** at its current ring. Re-onboarding requires the service to meet the guardrail; renewal is no longer an option for that cycle.

This mechanism exists so that lapsing into exception-by-default is operationally unpleasant for the service, not merely a paperwork irregularity.

## 8. Emergency exceptions

Emergency exceptions are granted during active incidents or security events when waiting for the standard approval path would itself constitute a greater risk. They differ from standard exceptions in three ways:

- They can be granted by the patch wave coordinator and on-call platform lead together, without prior approval from the standard approver.
- They must be **retrospectively ratified** by the standard approver within 5 working days. Failure to ratify converts the exception into an expired-without-closure record and triggers §7 handling.
- They have a hard 30-day cap and cannot be renewed in their emergency form — at 30 days, the service must either meet the guardrail or hold a properly-approved standard or material exception.

Emergency exceptions are tracked separately in the register so their use can be reviewed for patterns. Repeated emergency exceptions for the same guardrail on the same service indicate a systemic issue requiring escalation, not another emergency.

## 9. Audit

The register is audited annually by an independent reviewer (internal audit or an equivalent function) for:

- Completeness — every service in the patching pipeline with a gap has a corresponding register entry.
- Currency — no entries are stale beyond their expiry.
- Approval integrity — approvals match the class table; no Material exceptions approved by Standard-class approvers.
- Compensating control reality — sampled entries are tested to confirm the compensating control is actually operating.

Audit findings are tabled with platform leadership and tracked to closure.

## 10. Initial seeding

When this register is first established post-Mythos, every service onboarded to the patching pipeline is assessed against the guardrails. Gaps identified at onboarding are entered as exceptions with realistic expiry dates and remediation plans. This produces a (likely substantial) initial population of exceptions — that is expected and desirable. The register's value comes from its trajectory: exceptions trending down over time, not the absolute number on day one.

---

*The register makes the cost of not meeting a guardrail visible. Visibility is what prevents the exception path from quietly becoming the default path.*
