---
name: nfr-review-domain
description: Domain model and rubric for non-functional reviews — categories, severity scale, evidence requirements, finding shape, scoring. Use when defining the report schema, writing review prompts, generating findings, or deciding what counts as a valid NFR finding versus a functional bug.
---

# NFR Review Domain

The domain this project automates: **non-functional reviews of other projects**. This skill defines what an NFR review *is* — what's in scope, how findings are shaped, how severity is assigned, what evidence is required. It's the rubric the tool itself produces and grades against.

When in doubt about whether something is an NFR concern, refer here.

Before adding or modifying collectors, rules, output formats, or config options, read `ARCHITECTURE.md` in the project root. It defines where each type of logic belongs and the contracts between modules.

## Architecture Review Gate

ARCHITECTURE.md is the authoritative reference for module responsibilities, data flow, contracts, and extension patterns. It must stay current. Two mandatory checkpoints enforce this:

### At slice planning (before execution begins)

After writing or reviewing the slice plan, ask:

1. Does any task introduce a **new module**, **new data flow path**, or **new registration pattern**?
2. Does any task **change an existing contract** (Evidence payload shape, Finding fields, protocol signatures, engine filtering pipeline)?
3. Does any task **add a new entry** to the Decision Guide table (new "You want to..." row)?

If **yes to any**: draft the specific ARCHITECTURE.md edits needed and present them for user approval before starting execution. Do not proceed until approved or the user says the change isn't architecturally significant.

If **no to all**: note "No ARCHITECTURE.md impact" in the plan and proceed.

### At slice completion (before marking done)

Review decisions made during execution:

1. Were any architectural decisions made that aren't reflected in ARCHITECTURE.md?
2. Did the implementation deviate from ARCHITECTURE.md in a way that the doc should now capture?
3. Were any new conventions established that future agents need to follow?

If **yes to any**: propose ARCHITECTURE.md edits for user approval as part of the slice completion. The slice is not done until the doc is current.

### What counts as architecturally significant

- New or removed modules in the module responsibility map
- Changes to the data flow diagram (new phases, new types between stages)
- Changes to the engine filtering pipeline (new gates, reordering)
- New contracts (new protocol, new Evidence kind convention)
- Changes to existing contracts (field additions/removals, behavioral changes)
- New entries in the Decision Guide
- New fault tolerance patterns

What does NOT require an update: new collectors/rules that follow existing patterns, bug fixes, test changes, config value additions within existing schema.

## What is an NFR review?

A review of a codebase for **how well it does things**, not **whether it does the right things**. Functional bugs ("login button broken") are out of scope. Non-functional concerns ("login flow has no rate limit, no audit log, no observable failure mode") are in scope.

If the question is *"does the feature work?"* → not NFR.
If the question is *"how does this hold up under load / attack / failure / scale / change / silence?"* → NFR.

## Categories

Five top-level categories. Every finding has exactly one.

| Category | Scope |
|---|---|
| **performance** | Latency, throughput, memory, CPU, algorithmic complexity, query efficiency, caching, bundle size, cold start. |
| **security** | AuthN/Z, input validation, secrets handling, injection, CSRF/XSS, supply chain, transport security, data exposure. |
| **observability** | Logs, metrics, traces, health endpoints, error surfaces, structured failure state, agent-debuggability. |
| **ops** | Deployability, config management, dependency hygiene, build reproducibility, runbook coverage, rollback, env parity. |
| **a11y** | WCAG conformance, keyboard nav, screen-reader support, color contrast, focus management, semantic HTML, alt text. |

A finding that spans two categories belongs to whichever is the *primary* concern — split into two findings if both are independently actionable.

Out of scope (do not file): functional bugs, design taste, library preferences without concrete tradeoff, code style without runtime impact.

## Severity scale

Five levels. Severity reflects **realistic impact**, not theoretical worst case.

| Severity | Score | Meaning | Example |
|---|---|---|---|
| **critical** | 9.0–10.0 | Production exploit / outage / data loss likely. Block release. | Hardcoded prod credentials in repo. SQL concatenation on user input. |
| **high** | 6.5–8.9 | Likely incident under normal conditions. Fix this sprint. | No rate limit on auth endpoint. Unbounded retries causing cascading failure. |
| **medium** | 3.5–6.4 | Real but bounded risk. Fix this quarter. | Missing structured logs in error paths. N+1 query on infrequent endpoint. |
| **low** | 1.0–3.4 | Minor concern. Address opportunistically. | Outdated dependency without known CVE. Missing alt text on decorative image. |
| **info** | 0.0–0.9 | Observation, not a defect. Improvement note. | "Consider adding OpenTelemetry — currently using ad-hoc logging." |

Calibration rule: if you can't describe the failure scenario in one sentence ("under X, Y happens, with impact Z"), the severity is too high — drop it a level.

## Finding shape

Every finding has these fields. Anything missing is a malformed finding.

```yaml
id: F0042                           # Fxxxx, monotonic per report
title: "Auth endpoint has no rate limit"
category: security                  # one of the five
severity: high                      # one of the five
score: 7.5                          # within severity band
location:                           # where in the target codebase
  file: src/auth/login.py
  line: 42
  symbol: login_handler             # optional
description: |                      # what's wrong, in one paragraph
  The /login endpoint accepts unlimited POST requests from any IP.
  No middleware enforces a rate limit, and the upstream nginx config
  does not throttle by path. Credential stuffing is unmitigated.
impact: |                           # what could go wrong, concretely
  Attacker can attempt 1000s of credential combinations per second.
  No alerting fires until the auth service itself degrades.
remediation: |                      # how to fix, with concrete options
  Add slowapi or fastapi-limiter middleware: 5 attempts per minute
  per IP, plus 10/hour per username. Log throttle events to the
  auth audit stream so brute-force attempts are visible.
evidence:                           # see Evidence section
  - kind: code
    file: src/auth/login.py
    line: 42
    snippet: "@app.post('/login')\ndef login_handler(...)"
  - kind: command
    command: "rg 'rate.?limit|throttle' src/auth/"
    exit_code: 1
    output: "(no matches)"
references:                         # optional external context
  - "OWASP ASVS V2.2.1"
  - "https://owasp.org/www-community/attacks/Credential_stuffing"
```

## Evidence requirements

A finding without evidence is an opinion. Two evidence types:

**Code evidence** — file path, line number, and the snippet that demonstrates the issue. Required for any finding that points at specific code.

**Command evidence** — a command that was run, its exit code, and its output (truncated to relevant). Use to prove absence (no rate-limit middleware found), to demonstrate runtime behavior (load test latency), or to surface tool output (security scanner result).

Severity gates evidence requirements:

| Severity | Minimum evidence |
|---|---|
| critical | ≥ 1 code AND ≥ 1 command |
| high | ≥ 1 code OR ≥ 1 command + reasoned argument |
| medium | ≥ 1 piece of evidence |
| low | recommended but optional |
| info | optional |

Critical findings without two evidence pieces should be downgraded to high. The model validation should enforce this.

## Scoring

Within a severity band, score reflects exploitability + reach + reversibility:

- **Exploitability** — how easy is it to trigger? (script kiddie → APT)
- **Reach** — how much of the system is affected? (one user → all data)
- **Reversibility** — can damage be undone? (logs only → permanent loss)

A `high` security finding that's hard to exploit and limited in reach scores 6.5–7.0. A `high` finding that's easy and broad scores 8.5–8.9.

Report-level score is **not** the sum or average — it's the count of findings per severity, presented as a vector. Single-number aggregates lie.

## Report structure

```yaml
target:
  name: project-name
  commit: abc123
  reviewed_at: 2026-05-03T12:00:00Z
summary: |
  3-5 sentence executive summary. Lead with critical findings.
  State what was reviewed and what was not. Be specific.
findings:
  - { id: F0001, ... }
  - { id: F0002, ... }
counts:
  critical: 1
  high: 4
  medium: 7
  low: 2
  info: 3
not_reviewed:                       # what was deliberately out of scope
  - "Frontend a11y — no UI surfaces in this PR"
  - "Database performance — no schema or query changes"
methodology: |
  How the review was conducted: tools used, commits inspected,
  manual review vs automated. Important for reproducibility.
```

The `not_reviewed` field is required. A review that doesn't say what it skipped is misleading.

## Anti-patterns to reject

- **Findings without location** — "the codebase has no observability" with no file pointer is a vibe, not a finding. Either point at specific gaps or omit.
- **Synthetic severity inflation** — calling a missing comment "high severity" because the rubric has "high" as the second tier. Severity must reflect impact.
- **Functional bugs in disguise** — "the feature is broken" is not NFR. Reject and refer to bug tracker.
- **Tool-output dumps as findings** — "ruff reports 47 errors" is not a finding. Either a single finding ("lint config is not enforced — 47 violations") with the count as evidence, or per-rule findings if they cluster meaningfully.
- **Scope creep** — refactoring suggestions, library swaps, "code smells" without runtime/security/operational impact. These belong in code review, not NFR review.
- **No-evidence claims** — "this is probably slow" without a measurement, "this might be insecure" without a threat model. Either gather evidence or downgrade to `info` and label as observation.

## Calibration heuristics

- A clean codebase still has `info` and `low` findings. A report with zero is suspicious — either the reviewer didn't look or didn't write things up.
- Most well-run projects produce 0–2 critical, 2–8 high. A flood of criticals usually means severity inflation.
- If two findings share the same root cause (e.g. "no logging in module X" + "no logging in module Y" + "no logging in module Z"), merge into one finding scoped to the root cause ("structured logging is not adopted project-wide") with each instance as evidence.
- Findings should be actionable in isolation. If fixing finding A requires also fixing B and C, they're really one finding.

## Verification of the review itself

A review is done when:

1. Every finding has its required evidence (severity-appropriate)
2. `not_reviewed` lists explicit scope exclusions
3. `methodology` describes how the review was conducted
4. Counts match the actual finding list
5. The summary names the top 1–3 critical/high findings

If any of these fail, the review is not ready to ship.
