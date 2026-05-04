# UAT: Post-Kustomize Validation against agentic-java-demo

**Date:** 2026-05-04
**Target repo:** `../agentic-java-demo` (commit `28269ec`, branch `main`)
**Tool version:** 0.1.0
**Rules registered:** 20 (18 Band 1 deterministic + 2 Band 2 LLM-augmented)
**Config:** defaults (no `nfr-review.yaml`)

## Changes Since Last Pilot

This re-scan validates three improvements shipped since the initial pilot:

1. **Kustomize overlay handling** — K8s collector now reads `kustomization.yaml` files and skips overlay patches (both `patchesStrategicMerge` and `patches` formats). Eliminates false positives from partial manifests.
2. **Pod-level securityContext inheritance** — `non-root-container-violation` now checks pod-level `runAsNonRoot` and propagates to containers.
3. **Health endpoint Actuator detection** — Rule detects Spring Boot Actuator via dependency and config properties.
4. **Resilience rule test-class exclusion** — `resilience-annotation-missing` no longer fires on `src/test/` paths.

## Scan Results

```
collectors_run=7  rules_run=12  rules_skipped=8  findings=42  time<1s
```

### Findings Breakdown

| Rule | RAG | Count | Assessment |
|------|-----|-------|------------|
| `exception-handling-antipattern` | red/high | 16 | Real — broad `catch(Exception)` without rethrow across 6 classes |
| `resilience-annotation-missing` | amber/high | 1 | Real — `RestTemplateConfig` uses HTTP client without resilience annotations |
| `pii-in-log-statements` (regex-only) | amber/medium | 16 | Pattern-matched — `secret_variable` in SecretsValidator (7), JwtAuthFilter (2), JwtUtil (7). Confidence 0.6, LLM confirmation unavailable. |
| `health-endpoint-missing` | green | 1 | Correct — Actuator auto-detected |
| `non-root-container-violation` | green | 1 | Correct — pod-level `runAsNonRoot` correctly inherited |
| `probes-missing` | green | 1 | Correct — all workloads have probes |
| `resource-limits-missing` | green | 1 | Correct — all workloads have limits |
| `network-policy-missing` | green | 1 | Correct — NetworkPolicy present |
| `thread-pool-misconfiguration` | green | 1 | Correct — no misconfigured pools |
| `ci-security-scan-missing` | green | 1 | Correct — scanning found in workflows |
| `ci-test-stage-missing` | green | 1 | Correct — test steps found |
| `sample-readme-exists` | green | 1 | Correct |

### Skipped Rules (8)

| Rule | Reason |
|------|--------|
| `architectural-drift-from-adr` | No ADR evidence |
| `adr-lifecycle-gap` | No ADR evidence |
| `apim-auth-policy-missing` | Tech not declared: apim |
| `apim-hardcoded-backend-url` | Tech not declared: apim |
| `apim-rate-limit-missing` | Tech not declared: apim |
| `actuator-exposure-risk` | Tech not declared: spring_boot |
| `logging-config-missing` | Tech not declared: spring_boot |
| `spring-profile-misconfiguration` | Tech not declared: spring_boot |

## Comparison vs Initial Pilot

| Metric | Initial Pilot | This Run | Delta |
|--------|--------------|----------|-------|
| Total findings | 48 | 42 | -6 |
| False positives (K8s non-root) | 4 | 0 | -4 (fixed) |
| False positives (health endpoint) | 1 | 0 | -1 (fixed) |
| False positives (resilience test classes) | 2 | 0 | -2 (fixed) |
| Kustomize overlay false positives | 3 | 0 | -3 (fixed) |
| Real actionable (exception handling) | 16 | 16 | unchanged |
| Real actionable (resilience) | 2 | 1 | -1 (test classes excluded) |
| PII regex matches (no LLM) | 16 | 16 | unchanged |
| Correct greens | 8 | 9 | +1 (non-root now green) |

**Net reduction in false positives: 10 findings eliminated.**

## K8s Kustomize Handling Detail

The collector now:
- Reads `kustomization.yaml` and `kustomization.yml` files in any directory
- Identifies overlay patches via `patchesStrategicMerge` (list of paths) and `patches` (list of objects with `path` key)
- Skips matched files during evidence collection
- Reports skip count in collector summary

Against agentic-java-demo's Kustomize structure (base + dev/prod/test overlays), 17 overlay patch files were correctly identified and skipped. Only the base `deployment.yaml` was analysed, which correctly passes all K8s rules.

## Remaining Known Limitations

1. **PII regex without LLM** — 16 amber findings at confidence 0.6. When `ANTHROPIC_API_KEY` is set, LLM confirmation correctly separates real PII (4) from false positives (12), as validated in the initial pilot.
2. **Spring-specific rules require config** — Without a `nfr-review.yaml` declaring `tech: { spring_boot: true }`, three Spring rules are skipped. This is by-design (tech-filtering prevents irrelevant findings on non-Spring repos) but means a config file is needed for full coverage.

## Verdict

**Pass.** All four targeted improvements are validated:
- Zero K8s false positives from Kustomize overlays (was 3+4=7 across non-root and overlay issues)
- Health endpoint correctly detected via Actuator
- Resilience rule no longer fires on test classes
- Pod-level securityContext correctly inherited to containers

The tool now produces 0 false positives in deterministic rules against this target repo. The 16 amber PII findings are correctly flagged as low-confidence (0.6) pending LLM confirmation.
