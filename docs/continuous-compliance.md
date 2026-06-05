<!--
  Copyright 2026 nfr-review contributors
  SPDX-License-Identifier: Apache-2.0
-->

# Continuous Compliance with nfr-review

This document explains how to use nfr-review as a continuous compliance tool:
mapping its 130+ static-analysis rules to audit frameworks, producing
machine-readable evidence, managing exemptions, and tracking maturity over time.

---

## Table of Contents

1. [Cadence Model](#1-cadence-model)
2. [Control Mappings](#2-control-mappings)
3. [Evidence Model](#3-evidence-model)
4. [Exemption Process](#4-exemption-process)
5. [Maturity Model](#5-maturity-model)
6. [Adding New Frameworks](#6-adding-new-frameworks)
7. [Limitations](#7-limitations)

---

## 1. Cadence Model

nfr-review is designed around two complementary scan cadences that together
provide continuous assurance without blocking developer velocity.

### Nightly Full Scan (Baseline Mode)

A scheduled workflow runs every night against the default branch. It evaluates
every rule against the entire repository and produces a **baseline** -- the
canonical set of findings that represents the current state of the codebase.

```yaml
# .github/workflows/nfr-review-nightly.yml
on:
  schedule:
    - cron: "0 3 * * *"
```

The nightly scan:

- Runs with `fail-on: "never"` so it never blocks the default branch.
- Uploads the JSONL output as an artifact named `nfr-review-baseline`.
- Optionally syncs findings to GitHub Issues (via `create-issues: "true"`).
- Uploads SARIF to the GitHub Security tab for long-term trending.
- Retains artifacts for 90+ days to support audit evidence retrieval.

### PR Diff Scan (Diff Mode)

Every pull request triggers a scan in **diff mode**. The PR workflow downloads
the most recent nightly baseline and passes it via the `baseline` input. The
engine then filters findings: only regressions (findings whose identity key is
new relative to the baseline) count toward the pass/fail threshold.

```yaml
# .github/workflows/nfr-review.yml
- name: Run NFR Review
  uses: JimAKennedy/nfr-review@v1
  with:
    baseline: ${{ steps.baseline.outcome == 'success' && '...' || '' }}
    fail-on: "red"
```

A finding's **identity key** is the tuple `(rule_id, evidence_locator,
pattern_tag)`. If a finding with the same identity key already exists in the
baseline, it is suppressed in the PR scan -- the developer is not held
responsible for pre-existing debt.

### How the Two Modes Work Together

| Aspect | Nightly (Baseline) | PR (Diff) |
|---|---|---|
| Scope | Full repository | New/changed findings only |
| Failure mode | Observational (never fails) | Gating (fails on red, configurable) |
| Purpose | Track absolute posture | Prevent regressions |
| Evidence output | Full JSONL + SARIF + CSV | Delta JSONL |
| Issue sync | Creates/updates/closes issues | Typically off (optional) |

This dual-cadence design means auditors see the full picture from nightly
scans, while developers get fast, focused feedback on PRs that only flags what
they introduced.

---

## 2. Control Mappings

The tables below map nfr-review rule families to specific controls in four
widely adopted compliance frameworks. These mappings are indicative -- your
organization's control interpretation may differ, and you should validate
mappings with your compliance team.

### 2.1 CI/CD Rules

| Rule ID | SOC 2 | ISO 27001 | PCI DSS | NIST 800-53 | What it proves |
|---|---|---|---|---|---|
| `ci-test-stage-missing` | CC8.1 | A.8.25 | 6.2 | SA-11, CM-3 | A test stage exists in the CI pipeline, demonstrating that changes undergo automated verification before deployment. |
| `ci-security-scan-missing` | CC8.1, CC7.1 | A.8.25, A.8.8 | 6.3 | RA-5, SA-11 | Security scanning (SAST/DAST/SCA) is integrated into the CI pipeline, proving that vulnerability detection is part of the change management process. |

### 2.2 Kubernetes Rules

| Rule ID | SOC 2 | ISO 27001 | PCI DSS | NIST 800-53 | What it proves |
|---|---|---|---|---|---|
| `probes-missing` | CC7.1 | A.8.9 | 10.1 | SI-4, CP-10 | Health probes (liveness/readiness) are configured, proving that the platform can detect and recover from application failures automatically. |
| `resource-limits-missing` | CC6.6 | A.8.9 | 6.5 | SC-7, CM-6 | CPU and memory limits are set, demonstrating resource isolation that prevents a single workload from affecting others (system boundary enforcement). |
| `network-policy-missing` | CC6.1, CC6.6 | A.8.9 | 6.5 | SC-7, AC-3 | Network policies restrict pod-to-pod traffic, proving least-privilege network segmentation is enforced at the infrastructure layer. |
| `non-root-container-violation` | CC6.1 | A.8.25, A.8.28 | 6.5 | AC-6, CM-6 | Containers run as non-root with appropriate security contexts, demonstrating privilege minimization and secure deployment configuration. |

### 2.3 Docker Rules

| Rule ID | SOC 2 | ISO 27001 | PCI DSS | NIST 800-53 | What it proves |
|---|---|---|---|---|---|
| `dockerfile-base-pinning` | CC8.1 | A.8.25, A.8.8 | 6.2, 6.3 | CM-2, SI-7 | Base images are pinned to specific digests or versions, proving builds are reproducible and not vulnerable to supply-chain tag mutation. |
| `dockerfile-secret-leakage` | CC6.1 | A.8.28 | 6.5 | IA-5, SC-28 | No secrets are embedded in Dockerfile instructions (ENV, ARG, COPY), demonstrating secure credential handling. |
| `dockerfile-user-directive` | CC6.1 | A.8.25 | 6.5 | AC-6 | A USER directive is present so the container process does not run as root, proving least-privilege execution. |
| `dockerfile-multistage` | CC6.8 | A.8.25 | 6.2 | CM-7 | Multi-stage builds are used to exclude build tools from the runtime image, reducing the attack surface. |
| `dockerfile-k8s-user-conflict` | CC6.1 | A.8.9, A.8.25 | 6.5 | AC-6, CM-6 | The UID in the Dockerfile USER directive is consistent with the Kubernetes securityContext runAsUser, proving no privilege escalation gap between build and deploy. |
| `dockerfile-k8s-image-drift` | CC8.1 | A.8.9 | 6.2 | CM-2, SI-7 | The image tag referenced in Kubernetes manifests matches the Dockerfile build output, proving there is no drift between what is built and what is deployed. |

### 2.4 Java/Spring Rules

| Rule ID | SOC 2 | ISO 27001 | PCI DSS | NIST 800-53 | What it proves |
|---|---|---|---|---|---|
| `health-endpoint-missing` | CC7.1 | A.8.9 | 10.1 | SI-4, AU-6 | A health endpoint exists for monitoring and orchestration, proving the application supports automated availability checks. |
| `resilience-annotation-missing` | CC7.2 | A.8.25 | 6.5 | CP-10, SI-13 | Resilience patterns (circuit breakers, retries, bulkheads) are declared, proving the application is designed to degrade gracefully under failure. |
| `exception-handling-antipattern` | CC7.1, CC7.2 | A.8.28 | 6.5 | SI-4, SI-11 | Exception handling follows best practices (no swallowed exceptions, no generic catches), proving errors are observable and actionable. |
| `thread-pool-misconfiguration` | CC7.1 | A.8.9, A.8.25 | 6.5 | SC-5, SI-4 | Thread pools have bounded sizes and rejection policies, proving the application is protected against resource exhaustion. |
| `actuator-exposure-risk` | CC6.1 | A.8.9, A.8.28 | 6.5 | AC-3, AC-6 | Spring Boot actuator endpoints are not exposed on the public port without authentication, proving sensitive management interfaces are access-controlled. |
| `logging-config-missing` | CC7.1 | A.8.9 | 10.1 | AU-2, AU-12 | A logging framework configuration exists (logback.xml, log4j2.xml), proving that log output is structured and controllable. |
| `spring-profile-misconfiguration` | CC8.1 | A.8.9 | 6.2 | CM-6, CM-2 | Spring profiles are correctly separated (no production secrets in default profile), proving environment-specific configuration is properly isolated. |

### 2.5 Security Rules

| Rule ID | SOC 2 | ISO 27001 | PCI DSS | NIST 800-53 | What it proves |
|---|---|---|---|---|---|
| `pii-in-log-statements` | CC6.1 | A.8.28, A.5.8 | 6.5, 10.1 | SI-12, PT-2 | Log statements do not contain personally identifiable information (email, SSN, credit card patterns), proving data-at-rest minimization in log sinks. |
| `apim-auth-policy-missing` | CC6.1 | A.8.25, A.8.28 | 6.5 | AC-3, IA-2 | API Management policies require authentication on all inbound operations, proving API endpoints enforce identity verification. |
| `apim-rate-limit-missing` | CC6.6 | A.8.25 | 6.5 | SC-5 | Rate limiting policies are applied to API operations, proving the system is protected against denial-of-service and abuse. |

### 2.6 Architecture Rules

| Rule ID | SOC 2 | ISO 27001 | PCI DSS | NIST 800-53 | What it proves |
|---|---|---|---|---|---|
| `adr-lifecycle-gap` | CC8.1 | A.5.8 | 6.2 | PL-8, CM-3 | Architecture Decision Records follow a complete lifecycle (proposed, accepted, superseded, deprecated), proving architectural changes are formally governed. |
| `architectural-drift-from-adr` | CC8.1 | A.5.8 | 6.2 | PL-8, CM-3 | The codebase is consistent with accepted ADRs, proving that implementation matches documented architectural decisions. |

### 2.7 C++ Rules

| Rule ID | SOC 2 | ISO 27001 | PCI DSS | NIST 800-53 | What it proves |
|---|---|---|---|---|---|
| `cmake-build-config` | CC8.1 | A.8.25 | 6.2 | CM-3, SA-15 | CMake build configuration follows best practices (out-of-source builds, modern target-based commands), proving reproducible and maintainable build infrastructure. |
| `cpp-clang-format` | CC8.1 | A.8.25 | 6.2 | SA-15 | A .clang-format configuration exists and CI enforces it, proving code style is automated and consistent. |
| `cpp-clang-tidy` | CC8.1, CC7.1 | A.8.25, A.8.28 | 6.3 | SA-11, RA-5 | clang-tidy static analysis is configured and integrated into CI, proving automated defect detection for C++ code. |
| `cpp-raw-memory` | CC6.8 | A.8.28 | 6.5 | SI-16, SA-11 | Raw `new`/`delete` usage is flagged in favor of RAII and smart pointers, proving memory safety practices that prevent use-after-free and leak vulnerabilities. |
| `cpp-sanitizer-ci` | CC8.1, CC7.1 | A.8.25, A.8.8 | 6.3 | SA-11, SI-7 | Address, thread, or undefined-behavior sanitizers are enabled in CI, proving runtime defect detection is part of the test pipeline. |

### 2.8 Patching Rules (PATCH-*)

The 22 PATCH-* rules cover deployment patching readiness across five
subcategories. They collectively prove that the organization can deploy
patches safely, roll back when needed, and observe the impact.

| Rule Subcategory | Rules | SOC 2 | ISO 27001 | PCI DSS | NIST 800-53 | What it proves |
|---|---|---|---|---|---|---|
| PATCH-SCOPE (patch scoping) | PATCH-SCOPE-001, PATCH-SCOPE-002 | CC8.1 | A.8.8 | 6.2 | SI-2, CM-3 | Patch class configuration and accelerated cadence for critical-security patches are defined, proving structured patch management. |
| PATCH-ARCH (architecture readiness) | PATCH-ARCH-001 through PATCH-ARCH-004 | CC8.1, CC7.2 | A.8.9, A.8.25 | 6.2, 6.5 | CP-10, CM-2 | Singleton avoidance, graceful shutdown, update strategy, and PodDisruptionBudgets are configured, proving the application architecture supports zero-downtime patching. |
| PATCH-HEALTH (health readiness) | PATCH-HEALTH-001 through PATCH-HEALTH-004 | CC7.1 | A.8.9 | 10.1 | SI-4, CP-10 | Liveness/readiness probes, non-trivial health checks, startup probes, and preStop hooks are properly configured, proving the platform can safely manage pod lifecycle during patches. |
| PATCH-TRAFFIC (traffic management) | PATCH-TRAFFIC-001 through PATCH-TRAFFIC-003 | CC7.1, CC7.2 | A.8.9 | 6.5 | CP-10, SC-5 | Traffic draining, connection handling, and load balancer integration are configured, proving in-flight requests are preserved during rolling updates. |
| PATCH-DEPS (dependency patching) | PATCH-DEPS-001 through PATCH-DEPS-003 | CC8.1 | A.8.8 | 6.2, 6.3 | SI-2, RA-5 | Dependency update automation, vulnerability scanning in lockfiles, and base image freshness are verified, proving third-party components are actively maintained. |
| PATCH-TELEM (telemetry) | PATCH-TELEM-001 through PATCH-TELEM-003 | CC7.1 | A.8.9 | 10.1 | AU-2, AU-12 | Deployment events are emitted to the observability pipeline, version labels are propagated, and rollout metrics are collected, proving patch deployments are observable and auditable. |
| PATCH-ROLL (rollback) | PATCH-ROLL-001 through PATCH-ROLL-003 | CC8.1, CC7.2 | A.8.8 | 6.2 | CP-10, CM-3 | Rollback procedures are documented, rollback is testable in CI, and forward-compatible database migrations support rollback, proving recovery capability for failed patches. |

### 2.9 Dependency Rules

| Rule ID | SOC 2 | ISO 27001 | PCI DSS | NIST 800-53 | What it proves |
|---|---|---|---|---|---|
| `dep-freshness` | CC8.1 | A.8.8 | 6.2, 6.3 | SI-2, RA-5 | Dependencies are within acceptable age thresholds, proving the project does not rely on abandoned or unmaintained libraries that may harbor known vulnerabilities. |
| `dep-upgrade-path` | CC8.1 | A.8.8 | 6.2 | SI-2, CM-3 | Major-version upgrade paths exist for out-of-date dependencies, proving the team has a plan to address technical debt in third-party components. |

### 2.10 Observability Rules

| Rule ID | SOC 2 | ISO 27001 | PCI DSS | NIST 800-53 | What it proves |
|---|---|---|---|---|---|
| `otel-exporter` | CC7.1 | A.8.9 | 10.1 | AU-2, SI-4 | An OpenTelemetry exporter is configured, proving telemetry data (traces, metrics, logs) is shipped to a collection backend. |
| `otel-pipeline` | CC7.1 | A.8.9 | 10.1 | SI-4, AU-6 | The OpenTelemetry pipeline is fully wired (SDK, exporter, propagator), proving end-to-end observability is enabled, not just partially configured. |
| `otel-sampling` | CC7.1 | A.8.9 | 10.1 | AU-2, AU-12 | A sampling strategy is explicitly configured (not relying on defaults), proving the organization has made a deliberate decision about trace volume vs. coverage. |
| `correlation-id` | CC7.1 | A.8.9 | 10.1 | AU-6, IR-4 | Correlation IDs are propagated across service boundaries, proving distributed requests can be traced end-to-end for incident investigation. |

### 2.11 Hygiene Rules

Hygiene rules are prefixed `HYG-` and span seven subcategories. They verify
foundational project health that underpins all compliance programs.

| Rule Subcategory | Example Rule IDs | SOC 2 | ISO 27001 | PCI DSS | NIST 800-53 | What it proves |
|---|---|---|---|---|---|---|
| Documentation (HYG-DOC-*) | HYG-DOC-001, HYG-DOC-002, HYG-DOC-003 | CC8.1 | A.5.8 | 6.2 | SA-5, PL-8 | API documentation, a docs directory, and package metadata exist, proving the project is documented for maintainers and consumers. |
| CI Automation (HYG-CI-*) | HYG-CI-001 through HYG-CI-007 | CC8.1 | A.8.25 | 6.2, 6.3 | SA-11, CM-3 | CI pipeline, test stage, lint stage, SAST, coverage gates, pinned actions, and release publishing are present, proving automated quality gates exist. |
| Community Standards (HYG-COM-*) | HYG-COM-001 through HYG-COM-006 | CC8.1 | A.5.8 | 6.2 | SA-5, PL-1 | README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY.md, CODEOWNERS, and CHANGELOG exist, proving the project follows open-source community standards. |
| Build Readiness (HYG-BLD-*) | HYG-BLD-001 through HYG-BLD-005 | CC8.1 | A.8.25 | 6.2 | CM-3, SA-15 | Build system, entry points, pre-commit hooks, version strategy, and code debt markers are tracked, proving the project is buildable and maintainable. |
| Privacy (HYG-PRV-*) | HYG-PRV-001 through HYG-PRV-003 | CC6.1 | A.8.28, A.5.8 | 6.5 | PT-2, SI-12 | PII patterns, internal references, and tracking IDs are absent from source, proving the codebase does not leak sensitive data. |
| License Compliance (HYG-LIC-*) | HYG-LIC-001 through HYG-LIC-004 | CC8.1 | A.5.8 | 6.2 | SA-4, SA-22 | License headers, SPDX identifiers, LICENSE/NOTICE files, and copyleft dependency checks are present, proving intellectual property governance. |

### Control Reference Summary

For quick lookup, the controls referenced above are:

**SOC 2 (Trust Services Criteria)**
| Control | Description |
|---|---|
| CC6.1 | Logical and physical access controls |
| CC6.6 | System boundary and network segmentation controls |
| CC6.8 | Controls over software acquisition and development |
| CC7.1 | Detection and monitoring of anomalies and events |
| CC7.2 | Incident response and recovery |
| CC8.1 | Change management controls |

**ISO 27001:2022 (Annex A)**
| Control | Description |
|---|---|
| A.5.8 | Information security in project management |
| A.8.8 | Management of technical vulnerabilities |
| A.8.9 | Configuration management |
| A.8.25 | Secure development lifecycle |
| A.8.28 | Secure coding |

**PCI DSS v4.0**
| Control | Description |
|---|---|
| 6.2 | Bespoke and custom software is developed securely |
| 6.3 | Security vulnerabilities are identified and addressed |
| 6.5 | Common software attacks are prevented |
| 10.1 | Audit trails link access to individual accountability |
| 11.3 | External and internal penetration testing methodology |

**NIST 800-53 Rev 5**
| Control | Description |
|---|---|
| AC-3 | Access Enforcement |
| AC-6 | Least Privilege |
| AU-2 | Event Logging |
| AU-6 | Audit Record Review, Analysis, and Reporting |
| AU-12 | Audit Record Generation |
| CM-2 | Baseline Configuration |
| CM-3 | Configuration Change Control |
| CM-6 | Configuration Settings |
| CM-7 | Least Functionality |
| CP-10 | System Recovery and Reconstitution |
| IA-2 | Identification and Authentication (Organizational Users) |
| IA-5 | Authenticator Management |
| IR-4 | Incident Handling |
| PL-1 | Planning Policy and Procedures |
| PL-8 | Security and Privacy Architectures |
| PT-2 | Authority to Process Personally Identifiable Information |
| RA-5 | Vulnerability Monitoring and Scanning |
| SA-4 | Acquisition Process |
| SA-5 | System Documentation |
| SA-11 | Developer Testing and Evaluation |
| SA-15 | Development Process, Standards, and Tools |
| SA-22 | Unsupported System Components |
| SC-5 | Denial-of-Service Protection |
| SC-7 | Boundary Protection |
| SC-28 | Protection of Information at Rest |
| SI-2 | Flaw Remediation |
| SI-4 | System Monitoring |
| SI-7 | Software, Firmware, and Information Integrity |
| SI-11 | Error Handling |
| SI-12 | Information Management and Retention |
| SI-13 | Predictable Failure Prevention |
| SI-16 | Memory Protection |

---

## 3. Evidence Model

Every nfr-review scan produces structured, machine-readable artifacts that
serve as audit evidence. The outputs are designed to be durable (stored as
CI artifacts), searchable (line-delimited JSON), and compatible with
security-tooling ecosystems (SARIF).

### 3.1 JSONL (Primary Evidence Format)

The JSONL output is the authoritative record of a scan. Each file begins with
a `run_metadata` record containing full provenance (tool version, target
repository, git SHA, branch, timestamp, collector versions, rules run, and
rules skipped), followed by one `finding` record per evaluated finding.

```
{"record_type":"run_metadata","tool_version":"1.2.0","target_repo":"myorg/myapp","git_sha":"abc123",...}
{"record_type":"finding","rule_id":"probes-missing","rag":"red","severity":"high","summary":"...","recommendation":"...","evidence_locator":"file://k8s/deployment.yaml:42",...}
{"record_type":"finding","rule_id":"ci-test-stage-missing","rag":"amber",...}
```

Each finding record contains the 10 canonical fields: `rule_id`, `rag`,
`severity`, `summary`, `recommendation`, `evidence_locator`,
`collector_name`, `collector_version`, `confidence`, and `pattern_tag`.
Skipped rules appear as synthetic records with `rag: "skipped"` and a reason.

**Audit use:** JSONL files are the evidence an auditor inspects. They answer
"what was checked, when, against which code, and what was found." Retain them
for the duration required by your compliance program (typically 1-3 years).

### 3.2 SARIF (Security Tooling Integration)

nfr-review produces SARIF 2.1.0 output compatible with GitHub's Code Scanning
Alerts. Findings are mapped to SARIF severity levels (`error` for
critical/high, `warning` for medium, `note` for low/info), and evidence
locators are parsed into physical locations with file paths and line numbers.

SARIF integrates nfr-review findings into the same dashboard as CodeQL, Trivy,
and other SARIF-producing tools, giving security teams a single pane of glass.

When `sarif-upload: "true"` is set in the GitHub Action, the SARIF file is
automatically uploaded to the repository's Security tab, creating persistent,
searchable alerts with audit trails.

### 3.3 CSV (Spreadsheet-Friendly Export)

The CSV output contains the same 10 canonical finding fields as JSONL, one row
per finding plus synthetic rows for skipped rules. This format is intended for
teams that consume findings in spreadsheets or BI tools for manual review and
reporting.

### 3.4 Executive Summary (LLM-Powered)

When an LLM backend is configured, nfr-review produces a structured executive
summary with a verdict (`fit`, `conditional`, `unfit`), risk highlights,
prioritized remediations, and an overall score (0-100). This is useful for
management reporting and go/no-go decisions.

### 3.5 GitHub Issues (Living Evidence)

When `create-issues: "true"` is enabled, nightly scans create, update, and
close GitHub Issues for findings that meet the configured RAG and severity
thresholds. Issues include labels, finding details, and remediation
guidance. The sync lifecycle (create, update, close) means the issue tracker
always reflects the current state of the codebase -- closed issues serve as
evidence of remediation.

### Evidence Retention Recommendations

| Artifact | Suggested retention | Rationale |
|---|---|---|
| JSONL (nightly) | 1-3 years | Primary audit evidence; retention should match your compliance program's record-keeping requirements. |
| SARIF | 365 days (GitHub default) | Security tab alerts are the trending view; raw files back them up. |
| JSONL (PR) | 30-90 days | Short-lived delta evidence; the nightly baseline is the canonical record. |
| CSV | As needed | Convenience export; regenerable from JSONL. |
| GitHub Issues | Indefinite | Living evidence of finding lifecycle; do not delete closed issues during audit periods. |

---

## 4. Exemption Process

Not every finding warrants immediate remediation. nfr-review supports a formal
exemption process through the `rules.skip` configuration in `nfr-review.yaml`,
combined with documentation that satisfies audit requirements.

### 4.1 Skipping Rules

Add rule IDs to the `rules.skip` list in your `nfr-review.yaml`:

```yaml
version: 1
rules:
  skip:
    - dockerfile-multistage        # Accepted risk: single-stage build for CLI tool
    - spring-profile-misconfiguration  # False positive: profiles managed by Kubernetes ConfigMaps
```

When a rule is skipped:

- The engine records a `RuleResult` with `skipped: true` and the reason
  `"excluded by config.rules.skip"`.
- JSONL output includes a synthetic finding record with `rag: "skipped"`.
- SARIF output includes a `notApplicable` result with a suppression entry.
- CSV output includes a row with `rag: "skipped"`.

This means skipped rules are **never silently hidden**. Auditors can always
see which rules were exempted and verify that exemptions are justified.

### 4.2 Documenting Exemptions

For each skipped rule, document the following alongside the `nfr-review.yaml`
entry:

1. **Rule ID** -- which rule is being exempted.
2. **Justification** -- why the finding is not applicable or is an accepted risk.
3. **Compensating control** -- what alternative measure addresses the underlying risk (if any).
4. **Review date** -- when the exemption should be re-evaluated.
5. **Approver** -- who approved the exemption.

A practical approach is to maintain an exemption register as a table in your
repository (e.g., in a `docs/exemptions.md` or as comments in
`nfr-review.yaml` itself):

```yaml
version: 1
rules:
  skip:
    # EXEMPTION: dockerfile-multistage
    # Justification: This repository produces a single-binary CLI tool.
    #   Multi-stage builds add complexity with no security benefit here
    #   because the final image contains only the static binary.
    # Compensating control: Image is scanned by Trivy in CI (see ci-security-scan).
    # Review date: 2026-09-01
    # Approved by: Jane Smith (Security Lead)
    - dockerfile-multistage
```

### 4.3 Selective Inclusion

For repositories that only need a subset of rules, use `rules.include_only`
instead:

```yaml
version: 1
rules:
  include_only:
    - probes-missing
    - resource-limits-missing
    - ci-test-stage-missing
    - ci-security-scan-missing
```

When `include_only` is set, all rules not in the list are skipped with reason
`"not present in config.rules.include_only"`. This is useful for phased
adoption where you progressively expand scope.

---

## 5. Maturity Model

Use aggregate scan results to assess and track your organization's
non-functional requirements maturity. The five levels below are based on the
proportion of green, amber, and red findings across nightly scans.

### Level Definitions

| Level | Name | Criteria | Description |
|---|---|---|---|
| 1 | Ad-hoc | Not running nfr-review, or no nightly cadence | No systematic NFR assessment. Compliance is ad-hoc and unverifiable. |
| 2 | Reactive | Nightly scans running; >30% red findings | Scans are producing data, but significant gaps exist. Teams react to individual findings without a systematic remediation plan. |
| 3 | Defined | Nightly scans running; <10% red findings, <40% amber | Core controls are in place. Most critical gaps are closed. Exemptions are documented. Teams actively triage findings. |
| 4 | Managed | Nightly scans running; <5% red, <20% amber; PR diff scans gating merges | Regressions are prevented at the PR level. Findings are tracked as issues with SLAs. Exemption register is reviewed quarterly. |
| 5 | Optimized | <2% red, <10% amber; all findings have owners; mean-time-to-remediate < 14 days | Continuous improvement is demonstrable. New rules are adopted proactively. Compliance evidence is generated automatically and retained for audit. |

### Measuring Maturity

Use the nightly scan outputs to compute aggregate metrics:

```
red_pct   = red_count   / findings_count * 100
amber_pct = amber_count / findings_count * 100
green_pct = green_count / findings_count * 100
```

Track these percentages over time. The GitHub Action outputs (`red-count`,
`amber-count`, `green-count`, `findings-count`) are available as step outputs
for integration with dashboards and reporting tools.

The executive summary's `overall_score` (0-100) provides a single-number proxy
for maturity when LLM summarization is enabled.

### Progression Guidance

- **1 to 2:** Install nfr-review nightly. No configuration needed -- defaults
  scan everything.
- **2 to 3:** Triage red findings. Document exemptions for accepted risks.
  Enable issue sync to track remediation.
- **3 to 4:** Enable PR diff scans with `fail-on: "red"`. Assign finding
  owners via CODEOWNERS and issue labels.
- **4 to 5:** Tighten to `fail-on: "red+amber"`. Review exemptions quarterly.
  Add custom rules for organization-specific requirements.

---

## 6. Adding New Frameworks

The control mappings in Section 2 cover four major frameworks but are not
exhaustive. Organizations subject to additional frameworks (HIPAA, FedRAMP,
CIS Benchmarks, etc.) can extend the mappings by following this process.

### Step 1: Identify Applicable Controls

Review the new framework's control catalog and identify controls that address:

- Change management and secure development lifecycle
- Vulnerability management and security testing
- Configuration management and hardening
- Monitoring, logging, and audit trails
- Access control and least privilege
- Incident response and recovery

### Step 2: Map Rules to Controls

For each applicable control, determine which nfr-review rule families provide
evidence. Use the "What it proves" column in Section 2 as a guide -- if the
evidence a rule produces addresses the control's objective, the mapping is
valid.

Example mapping for HIPAA:

| Rule Family | HIPAA | Rationale |
|---|---|---|
| Security rules | § 164.312(a) Access Control | Proves API endpoints enforce authentication and rate limiting to protect ePHI. |
| Observability rules | § 164.312(b) Audit Controls | Proves telemetry pipeline captures system activity for audit trail requirements. |
| Kubernetes rules | § 164.312(e) Transmission Security | Proves network policies enforce segmentation that protects data in transit between services. |

### Step 3: Document and Review

Maintain framework-specific mapping tables alongside this document or in your
organization's compliance documentation. Have your compliance team review and
approve the mappings, as control interpretation varies by organization and
audit firm.

### Step 4: Validate with Auditors

Share the mapping and sample nfr-review output (JSONL, SARIF) with your
auditors early in the audit cycle. Confirm that they accept automated
static-analysis evidence as supporting documentation for the mapped controls.

---

## 7. Limitations

nfr-review is a static-analysis tool that inspects source code, configuration
files, and project structure at rest. It provides valuable continuous
compliance evidence but does not replace the following:

### What nfr-review Does Not Cover

| Gap | Why it matters | What to use instead |
|---|---|---|
| **Runtime testing** | nfr-review does not execute code or observe running systems. It cannot verify that a health endpoint actually returns 200 OK, only that one is declared. | Integration tests, synthetic monitoring, smoke tests. |
| **Penetration testing** | Static analysis finds configuration weaknesses but cannot discover runtime vulnerabilities like injection flaws in running applications. | DAST tools (ZAP, Burp Suite), manual penetration testing (PCI DSS 11.3). |
| **Infrastructure-as-deployed verification** | nfr-review checks Kubernetes manifests and Terraform files as committed to source. It does not verify that the live cluster matches the declared configuration. | Drift detection tools (driftctl, Polaris), runtime policy engines (OPA/Gatekeeper, Kyverno). |
| **Data-at-rest encryption** | nfr-review cannot inspect storage configurations, key management, or encryption-at-rest settings in cloud providers. | Cloud security posture management (CSPM) tools, cloud-native audit logs. |
| **Access control verification** | nfr-review checks for authentication policies in API Management configs but does not verify IAM roles, RBAC bindings, or identity provider configurations. | Cloud IAM auditing, RBAC review tooling, identity governance platforms. |
| **Business logic correctness** | nfr-review evaluates non-functional requirements (resilience, observability, security posture). It does not validate that business logic is correct. | Functional tests, acceptance tests, domain-specific validation. |
| **License legal review** | The hygiene license rules detect copyleft dependencies and missing headers but do not constitute legal advice. | Legal counsel review for license compatibility. |
| **Secrets detection** | While `dockerfile-secret-leakage` checks for secrets in Dockerfiles specifically, nfr-review is not a general-purpose secrets scanner. | Dedicated secrets scanning tools (GitLeaks, TruffleHog, GitHub Secret Scanning). |

### Confidence and False Positives

Every nfr-review finding includes a `confidence` score (0.0-1.0) indicating
the engine's certainty. Rules that rely on pattern matching (e.g., PII
detection in log statements) may produce false positives. Use the exemption
process (Section 4) to manage confirmed false positives, and report patterns
to the nfr-review project so rule precision can be improved.

### Static vs. Runtime Assurance

A passing nfr-review scan proves that the codebase is **configured for**
resilience, observability, and security. It does not prove the system
**behaves** resiliently, observably, or securely at runtime. Continuous
compliance requires nfr-review as one layer in a defense-in-depth strategy
alongside runtime monitoring, testing, and manual review.
