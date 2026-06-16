# Coverage Matrix

What nfr-review actually covers today, derived from the live registry
(`nfr-review list-rules --format json`, 119 rules), the collector inventory, and the
command implementations — **not** from marketing copy. Use this to set user
expectations and to plan where to invest next.

> Regenerate the rule-derived numbers with:
> `nfr-review list-rules --format json` and the buckets in this doc.
> Last refreshed: 2026-06-16 (119 rules: 92 Band 1, 21 Band 2/LLM, 6 Band 3/quantitative).

---

## Language support (the headline)

Java is the clear leader; Python and Go are strong; C++ is deep on AST but missing
ecosystem features; C# and Node/TS are the thinnest. "Java and Python are best" is
right about Java, but the data refines it: **Python and Go are roughly equal**, and
**C++ has more rules than Python** while lacking dependency and cross-language coverage.

| Capability | Java | Python | Go | C++ | C# | Node/TS |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| AST collector | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AST extraction depth (extractor fns) | 15 | 14 | 14 | 14 | 6 | 7 |
| Typed payload classes | 9 | 12 | 13 | 15 | 7 | 8 |
| Dedicated rules (collector/tech-gated) | 18 | 7 | 7 | 10 | 6 | 6 |
| Cross-language rules (bare-except, stdout-logging) | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| **Effective rule count** | **20** | **9** | **9** | **10** | **8** | **8** |
| Dependency resolution (deps cmd) | ✅ maven | ✅ pypi | ✅ go | ❌ | ✅ nuget | ✅ npm |
| Package-cycle analysis (JDepend) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Coverage ingestion (JaCoCo) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Build-system collector | ✅ (deps) | ✅ (deps) | ✅ (deps) | ✅ cmake | ✅ (deps) | ✅ (deps) |
| Class diagrams (`arch`) | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Test execution (`report`) | ❌ | ✅ pytest | ❌ | ❌ | ❌ | ❌ |

### Support tiers

- **Tier 1 — Comprehensive: Java.** AST + Maven deps + JDepend cycles + JaCoCo
  coverage + class diagrams + 20 effective rules. Everything works.
- **Tier 1 — Strong: Python, Go.** Rich AST, dependency resolution, class diagrams,
  cross-language rules. ~9 effective rules each. (Python additionally gets `report`
  test execution via pytest.)
- **Tier 2 — Deep AST, narrow ecosystem: C++.** Rich AST (14 extractors) + CMake +
  class diagrams + 10 rules, but **no dependency resolution** and **not covered by the
  cross-language exception/logging rules**.
- **Tier 3 — Thin: C#, Node/TS.** Shallower AST (6–7 extractors), dependency
  resolution and cross-language rules present, but **no class diagrams** and the fewest
  language-specific rules.

---

## Environment / platform support

Driven by `required_tech` + `required_collectors` across the rule set (18 tech
detectors total in `detect.py`).

| Platform / domain | Collector(s) | Rules | Notes |
|---|---|:--:|---|
| Kubernetes | `k8s-manifest` | 18 | Deepest non-Java area: probes, limits, security context, network policy |
| Observability (OTel) | `otel`, `otel-trace`, `telemetry-config` | 17 | Static config + dynamic trace analysis (Band 3) |
| Docker | `dockerfile` | 6 | Base-image pinning, multistage, USER, secret leakage |
| Istio / service mesh | `istio`, `service-mesh` | 5 | Circuit breakers, mTLS, traffic policy |
| CI/CD (GitHub Actions) | `ci-artifact` | 4 | Test/lint/SAST stages, action pinning, coverage gate |
| Spring Boot | `spring-config` | 3 | Actuator exposure, logging, profiles |
| APIM (Azure) | `apim-policy` | 3 | Auth, backend URLs, rate limiting |
| Helm | `helm` | 3 | Chart metadata, values, secret leakage |
| Terraform | `terraform` | 3 | Provider pinning, state backend, IAM |
| gRPC / Protobuf | `proto` | 3 | Field numbering, versioning, comments |
| ADR / architecture | `adr`, `adr-derive` | 3 | Lifecycle/coverage gaps, drift (LLM) |
| Skaffold | `skaffold` | 1 | Build config validation |
| Gatling (perf) | `gatling` | 1 | Threshold validation |
| Deployment patching | multiple (k8s/helm/ci) | — | "patch_*" rule family: update strategy, PDB, graceful shutdown, rollback |

GitHub Actions is the only CI system covered (no GitLab CI / Jenkins / CircleCI).

---

## Per-command coverage

| Command | Purpose | Languages exercised | Environments exercised | Notes |
|---|---|---|---|---|
| `run` | NFR scan (collect → rules) | All 6 (per detected/enabled tech) | All platforms above | Core path; output CSV/JSONL/SARIF |
| `report` | Full report (NFR + hygiene + tests + deps + diagrams + PDF) | All 6; **tests = Python only** (pytest) | All | `deps` covers 5 ecosystems; exec summary is LLM-gated |
| `hygiene` | Repo hygiene audit | Language-agnostic + build-readiness (pyproject/gradle/pom/cargo/go.mod/package.json) | n/a | docs, CI, community, build, privacy, license |
| `arch` | Multi-repo architecture report | Class diagrams: **C++/Java/Python/Go only**; integration discovery: maven/gradle/npm/python/go/**rust**/**dotnet** | k8s, compose, cmake, proto | Bypasses the Engine (see CLEANUP_TASKS.md #6); covers Rust/.NET deps with no AST collector |
| `deps` | Dependency tree + upgrade advice | maven, pypi, go, nuget, npm (**5 ecosystems**) | n/a | No C++/Cargo/other resolution |
| `issues scan`/`sync` | File/sync GitHub issues from findings | Language-agnostic | n/a | Driven by findings, not source directly |
| `init` | Detect tech, scaffold config | All 18 tech keys | All | Detection only |
| `all` | `arch` (cross-repo) + `report` per repo | As `arch` + `report` | All | Orchestration wrapper |
| `baseline create`/`diff` | OTel interaction baselines | Language-agnostic (trace-based) | Observability | Dynamic analysis |
| `monitor` | Live OTel collector | Language-agnostic | Observability | Requires `monitor` extra |
| `list-rules` / `explain` / `version` | Metadata | n/a | n/a | `list-rules --format json` is the source of truth for this doc |

### Notable asymmetries (improvement signals)

1. **`report` test execution is Python-only.** Java (Surefire/JUnit), Go (`go test`),
   etc. produce no test section. High-value gap for a polyglot tool.
2. **C++ has no dependency resolution** despite 10 rules and rich AST — CMake/Conan/vcpkg
   resolution would lift it to Tier 1.
3. **Rust and .NET appear in `arch` integration discovery but have no AST collector**
   (Rust) — coverage is inconsistent across commands for the same language.
4. **C# / Node-TS AST is ~half the depth** of the others (6–7 extractors vs 14–15).
   Deepening these would directly raise their rule ceiling.
5. **Class diagrams skip C# and Node/TS** even though their AST collectors exist.
6. **Cross-language rules skip C++** — adding C++ to `bare-except`/`logging-to-stdout`
   coverage is cheap and +2 effective rules.
7. **CI coverage is GitHub-Actions-only** — no other CI provider.

---

## Suggested investment priorities

Ordered by leverage (effort vs. coverage gained):

| Priority | Improvement | Why |
|---|---|---|
| 1 | Add C++ to the cross-language rules | Trivial table entry, +2 effective rules, closes a Tier-2 gap |
| 2 | Polyglot test execution in `report` (Go, Java, JS) | Removes the biggest single-language assumption in the pipeline |
| 3 | Class diagrams for C# and Node/TS | Collectors already emit class data; only `arch_orchestrator` dispatch is missing |
| 4 | Deepen C# and Node/TS AST extractors toward parity (14–15 fns) | Raises the rule ceiling for Tier-3 languages |
| 5 | C++ dependency resolution (Conan/vcpkg/CMake) | Promotes C++ from Tier 2 to Tier 1 |
| 6 | Add a non-GitHub CI collector (GitLab CI or Jenkins) | Broadens the CI/CD domain beyond one provider |
| 7 | Add a Rust AST collector | `arch` already half-supports Rust; make it consistent |

Each row maps to either a new collector + rules (extendability path documented in
`ARCHITECTURE.md`) or a dispatch addition in an existing module.
