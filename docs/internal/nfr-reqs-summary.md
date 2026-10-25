# NFR Review — Requirements Summary

Source doc: `JK-nfr-review-OSS-reqs.pdf`

---

## Technology Dictionary

**Languages & runtimes**
- **Java** — primary language; Spring framework; Maven multi-module builds
- **Python** — AST-backed; pyproject.toml / setup.py / requirements.txt detection
- **Go** — go.mod detection; goroutine and defer analysis
- **Rust** — Cargo.toml detection; async, mutex, HTTP timeout analysis
- **C#** — csproj/sln detection; async void, blocking async, disposable patterns
- **Node.js / TypeScript** — package.json detection; promise, callback, sync FS patterns
- **C++** — CMakeLists.txt / Makefile / conan; sanitizer, memory, include guard analysis

**Frameworks & tools**
- **Spring** — XML/YAML/properties bean wiring; multi-module config scanning
- **Terraform** — HCL modules, provider pinning, state backend, IAM, sensitive outputs
- **Ansible** — content-aware detection; idempotency, package pinning, vault
- **Bicep** — database SKU, diagnostics, Key Vault secret handling
- **ARM** — API-version pinning, resource locks
- **Helm** — chart metadata, secret leakage, values validation
- **Kubernetes / AKS** — manifest normalisation; workload security, secrets, pipeline safety
- **Istio** — mTLS, circuit breaker, traffic policy
- **OpenTelemetry (OTel)** — collector pipeline config; SDK instrumentation detection
- **Prometheus** — metric labels, endpoints, service monitors
- **Gatling** — performance test evidence; p95 latency rules
- **JaCoCo** — Java coverage XML; threshold and coverage rules
- **JDepend** — Java coupling; cycle, distance, instability rules
- **Skaffold** — build and deploy config evidence
- **gRPC / Protobuf** — field numbering, method comments, service versioning
- **APIM** — auth, backend URL, rate limit rules

---

## Terms Dictionary

**Evidence** — a single piece of data produced by a collector. Has a `kind`, `locator`, `collector_name`, `collector_version`, and a typed `payload`. Rules consume evidence; they never read files directly.

**Payload** — the typed data inside an Evidence record. Defined as a `BasePayload` subclass specific to each collector. E.g. `OtelAnalysisPayload`, `RustAstFilePayload`, `DepsPayload`.

**Collector** — gathers raw signal from a target repo and emits Evidence. Never generates findings. Registered in `collector_registry` via entry point or `_register()`.

**Rule** — evaluates Evidence and emits a `RuleResult` containing zero or more `Finding` objects. Never reads files. Registered in `rule_registry`.

**Finding** — the output of a rule evaluation. Has `rule_id`, `rag`, `severity`, `summary`, `recommendation`, `evidence_locator`, `confidence`, `pattern_tag`.

**RAG** — Red / Amber / Green / Skipped. The traffic-light outcome of a finding.

**RuleResult** — wraps a rule's findings plus a `skipped` flag and `skip_reason` for when a rule couldn't run.

**Provenance** — the chain of source files and config values that caused a finding. Preserved through the collector → evidence → rule → finding pipeline so findings are traceable to their origin.

**Confidence** — a float 0–1 on each Finding indicating how certain the rule is. Calculated from evidence quality and rule-specific signals. Insufficient evidence never silently becomes confidence=1 / PASS.

**Locator** — a string identifying where evidence came from — typically a relative file path, optionally with a line number suffix (e.g. `src/main/App.java:42`).

**Canonical Rule ID** — a descriptive slug-based identifier for a rule (e.g. `k8s-container-no-resource-limits`). Replaces opaque numeric IDs. Legacy IDs are supported via case-insensitive aliases.

**Band** — rule tier. Band 1 = static analysis only. Band 2 = LLM-augmented analysis. Band 2 rules gracefully skip when `nfr-utils[llm]` is not installed.

**CRD (Canonical Report Dataset)** — the versioned, renderer-neutral contract between the engine and all output formats. Every renderer (Markdown, PDF, JSONL, SARIF, CSV, HTML) consumes the CRD.

**Publication Qualification** — the gate between raw rule results and published findings. Applies confidence thresholds, governance ignore/accepted-risk controls, and publication policies before anything reaches a report.

**NOT_APPLICABLE** — distinct outcome (not PASS) returned when a rule's target technology or resource is absent from the repo. Scores neither reward nor penalise it.

**INSUFFICIENT_EVIDENCE** — distinct outcome (not PASS) returned when the target exists but evidence is incomplete. Coverage gaps are exposed, not silently converted to green.

**Observability evidence** — evidence about a repo's telemetry setup: OTel collector config, SDK instrumentation, Prometheus metrics, alert definitions, dashboards, logging config.

**Telemetry config evidence** — richer OTel-specific evidence from `telemetry_config` collector: pipeline topology, exporter targets, resource attributes, SDK init patterns, synthetic test configs. Complements the lighter `otel` collector evidence.

**Taxonomy** — the versioned category/subcategory hierarchy rules resolve to (e.g. Reliability > Resilience). Used for scoring, report grouping and output consistency across renderers.

**Applicability** — whether a rule applies to the scanned repo. Determined by technology detection and evidence presence. Gates rule execution; absent targets return NOT_APPLICABLE rather than being skipped silently.

**Dormant class** — a class with no reachable source or configuration references. Config-wiring-aware detection excludes classes reachable through Spring or framework injection.

**Deduplication** — merging overlapping evidence items (e.g. the same telemetry setting found by both the OTel and telemetry-config collectors) into one logical item retaining all source locations. Must be deterministic across scan order and OS.

**Entry point** — the Python packaging mechanism (`importlib.metadata`) used by lang packs and utils to self-register collectors and rules into `nfr-core`'s registries on import. No central file needs editing to add a new pack.

---

## Requirements by Section

### Observability
- Versioned, normalised evidence payload — source, kind, technology, confidence, applicability, caching, provenance
- Collectors for logging, metrics, Prometheus, alerts, dashboards across app/YAML/JSON/XML/IaC sources
- Deduplication of overlapping OTel and telemetry-config evidence — deterministic, retains all source locations
- Rule packs for all observability profiles; missing profile → NOT_APPLICABLE, never PASS

### AKS / Kubernetes
- Normalise manifest evidence; fallback to runbook/doc evidence when manifests can't prove the control
- Workload security rules — security context, identity, privilege, isolation captured in normalised payloads
- Secret detection in manifests, build args, env vars, generated artifacts; skip approved secret-store references
- Pipeline deployment safety — missing validation, approval, immutability, rollout/rollback safeguards
- Applicability gating — no AKS findings on non-AKS repos; descriptive canonical rule names

### IaC
- Normalised collector for Terraform, Ansible, Bicep, ARM; universal rules where semantics are portable
- Framework-specific rules per tool (Terraform IAM/state/pinning, Ansible idempotency/vault, Bicep KV, ARM locks)
- Content-aware Ansible detection — not filename only; support multi-IaC repos
- Terraform module scoping — one module-level finding; AST-parsed output blocks; semantic `sensitive` evaluation

### Java / Spring
- Parse Spring XML/YAML/properties; emit wiring evidence with source locations; integrate with Java AST
- XXE mitigation; multi-module Maven discovery; META-INF/spring and app config paths

### Dependency Analysis
- Config-wiring fusion API for dependency graph — AST + configuration edges, no duplication
- Dormant-class detection aware of framework wiring — config-reachable classes not reported dormant

### Taxonomy and Scoring
- Versioned taxonomy with categories/subcategories; each rule resolves to a path; legacy metadata supported
- Scores calculated from taxonomy paths; grouped output; OTel rolled into Observability; stable migration semantics

### Rule IDs
- Descriptive slug-based canonical IDs; case-insensitive legacy aliases; normalised at all ingress points

### Publication and CRD
- Versioned CRD as the renderer-neutral contract; all renderers consume it
- Actionable/advisory/skipped/insufficient-evidence outcomes; parity across Markdown, PDF, JSONL, CSV, HTML, SARIF
- Human-readable category labels; consistent across all renderers; no opaque prefixes needed

### Finding Quality
- Evidence envelope with kind, provenance, confidence, scope; direct/inferred/absent/insufficient distinguished
- Insufficient evidence never silently → PASS; governance ignore and accepted-risk with auditable normalisation
- Coverage gaps exposed; derived assessments consume only qualified findings

### False Positives
- Explicit applicability checks; NOT_APPLICABLE with reason when target absent; scores don't penalise out-of-scope
- SCM URIs not treated as email PII; security scanning only counted in active/gating CI steps; content-based Ansible detection

### False Negatives
- Recursive discovery; all Maven modules scanned; external observability bundles supported; bounded for large repos

### Assessment
- Optional readiness layer; core scan identical when disabled; traces only to qualified findings

### Platform and CI
- Pinned base images; Git in runtime image; reproducible local container scan command
- Isolated doc-site build and automated deployment; no private infra dependencies

### Developer Workflow
- Provider-neutral role guidance; architecture alignment gate before cross-cutting changes; human approval required

### Documentation
- Public portal covering all major capabilities with extension points; glossary; no broken links; no private-hosting assumptions
