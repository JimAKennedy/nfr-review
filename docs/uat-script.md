# nfr-review UAT Script

**Version:** 0.1.0
**Last updated:** 2026-05-13

This script covers end-to-end acceptance testing of the `nfr-review` CLI.
Run it against a real target repository — the agentic-java-demo repo is the
reference target used in pilot UATs.

---

## Prerequisites

### 1. Run the setup script

The setup script creates a venv, installs nfr-review in editable mode with dev
dependencies, validates the installation, and optionally configures an Anthropic
API key for Band 2 LLM rules.

```bash
./scripts/setup.sh
```

After setup completes, activate the venv:

```bash
source .venv/bin/activate
```

Verify:

```bash
nfr-review version
# Expected: nfr-review 0.1.0
```

### 2. Clone a target repo

```bash
git clone https://github.com/JimAKennedy/agentic-java-demo.git /tmp/uat-target
```

> **Note:** If you skipped the API key prompt during setup and want to test
> Band 2 (LLM) rules later, either re-run `./scripts/setup.sh` or add
> `ANTHROPIC_API_KEY=sk-ant-...` to the `.env` file in the project root.

---

## 1. Informational Commands

### 1.1 list-rules

```bash
nfr-review list-rules
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| Output lists all registered rules | Each line: rule ID, band, summary |
| Rule count | >= 60 rules listed |

### 1.2 explain — valid rule

```bash
nfr-review explain dockerfile-base-pinning
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| Output includes rule ID, band, description | Full rule explanation displayed |

### 1.3 explain — unknown rule

```bash
nfr-review explain nonexistent-rule-id
```

| Check | Expected |
|-------|----------|
| Exit code | 1 |
| Error message | Rule not found |

---

## 2. Core Scan (`run`)

### 2.1 Default scan — no config

```bash
cd /tmp/uat-target
nfr-review run .
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| Summary on stderr | Shows `tech_detected`, `collectors_run`, `rules_run`, `findings` counts |
| `nfr-review.csv` created | 10-column CSV with header row |
| `nfr-review.jsonl` created | Line 1 = run metadata JSON, remaining = findings |
| Tech auto-detection | Java/Spring Boot detected from `pom.xml` |
| Findings count | > 0 findings |

### 2.2 Config-driven scan

```bash
nfr-review run . --config tests/fixtures/configs/agentic-java-demo.yaml
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| Spring-specific rules fire | `spring_boot: true` enables actuator/logging/profile rules |
| `health-endpoint-missing` skipped | Declared in config's `rules.skip` |

### 2.3 Custom output paths

```bash
nfr-review run . --csv /tmp/custom.csv --jsonl /tmp/custom.jsonl
```

| Check | Expected |
|-------|----------|
| Files written to custom paths | `/tmp/custom.csv` and `/tmp/custom.jsonl` exist |
| Default paths NOT created | `nfr-review.csv` / `nfr-review.jsonl` not created in cwd |

### 2.4 Severity threshold — exit code 2

Create a config that sets a low threshold:

```yaml
# /tmp/threshold-test.yaml
version: 1
severity_threshold: info
```

```bash
nfr-review run /tmp/uat-target --config /tmp/threshold-test.yaml
echo $?
```

| Check | Expected |
|-------|----------|
| Exit code | 2 (threshold exceeded) |
| Summary still printed | Findings written before exit |

### 2.5 Verbosity flags

```bash
# INFO level
nfr-review run /tmp/uat-target -v 2>/tmp/info.log
grep -c "INFO" /tmp/info.log

# DEBUG level
nfr-review run /tmp/uat-target -vv 2>/tmp/debug.log
grep -c "DEBUG" /tmp/debug.log

# Quiet mode
nfr-review run /tmp/uat-target -q 2>/tmp/quiet.log
wc -l /tmp/quiet.log
```

| Check | Expected |
|-------|----------|
| `-v` | INFO-level messages on stderr |
| `-vv` | DEBUG-level messages (more verbose than `-v`) |
| `-q` | Minimal output — only errors |

### 2.6 Mutual exclusion: verbose + quiet

```bash
nfr-review run /tmp/uat-target -v -q
```

| Check | Expected |
|-------|----------|
| Exit code | 2 (Click UsageError) |
| Error message | Indicates mutual exclusion |

### 2.7 Log file redirect

```bash
nfr-review run /tmp/uat-target -v --log-file /tmp/nfr.log
```

| Check | Expected |
|-------|----------|
| `/tmp/nfr.log` created | Contains log output |
| stderr | Minimal (summary only, logs redirected to file) |

---

## 3. Tech Filtering and Rule Gating

### 3.1 Spring rules require declaration

```bash
# No config — Spring rules should be skipped
nfr-review run /tmp/uat-target 2>&1 | grep -i "skipped"
```

| Check | Expected |
|-------|----------|
| Spring-specific rules skipped | Rules like `actuator-health-exposure`, `spring-logging-format`, `spring-profile-active-default` skipped without `spring_boot: true` |

### 3.2 rules.skip

```yaml
# /tmp/skip-test.yaml
version: 1
rules:
  skip:
    - dockerfile-base-pinning
    - k8s-resource-limits-missing
```

```bash
nfr-review run /tmp/uat-target --config /tmp/skip-test.yaml
grep "dockerfile-base-pinning" nfr-review.csv
```

| Check | Expected |
|-------|----------|
| Skipped rules absent from output | No findings for skipped rule IDs |

### 3.3 rules.include_only

```yaml
# /tmp/include-test.yaml
version: 1
rules:
  include_only:
    - dockerfile-base-pinning
    - dockerfile-user-directive
```

```bash
nfr-review run /tmp/uat-target --config /tmp/include-test.yaml
```

| Check | Expected |
|-------|----------|
| Only listed rules fire | CSV contains only findings from the two specified rules |

### 3.4 Kustomize overlay handling

Target a repo with `kustomization.yaml` overlays (agentic-java-demo has these):

| Check | Expected |
|-------|----------|
| Overlay patch files skipped | No K8s findings from `overlays/` partial manifests |
| Base manifests analysed | Findings from `k8s/` base directory present |

---

## 4. Hygiene Command

### 4.1 List checks

```bash
nfr-review hygiene --list-checks
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| Categories listed | `bld`, `ci`, `com`, `doc`, `license`, `prv` |
| Check count | >= 23 checks listed |

### 4.2 Full hygiene scan

```bash
nfr-review hygiene /tmp/uat-target --output-dir /tmp/hygiene-out
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| `hygiene-report.csv` in output dir | CSV findings with RAG ratings |
| `hygiene-report.jsonl` in output dir | JSONL findings |

### 4.3 Format selection

```bash
# CSV only
nfr-review hygiene /tmp/uat-target --format csv --output-dir /tmp/hyg-csv
ls /tmp/hyg-csv/

# JSONL only
nfr-review hygiene /tmp/uat-target --format jsonl --output-dir /tmp/hyg-jsonl
ls /tmp/hyg-jsonl/
```

| Check | Expected |
|-------|----------|
| `--format csv` | Only `hygiene-report.csv` created |
| `--format jsonl` | Only `hygiene-report.jsonl` created |

### 4.4 Category filter

```bash
nfr-review hygiene /tmp/uat-target --category ci,com
```

| Check | Expected |
|-------|----------|
| Only CI and Community findings | No `bld`, `doc`, or `prv` findings in output |

### 4.5 Clean repo (all green)

```bash
nfr-review hygiene tests/fixtures/hygiene-clean-repo
```

| Check | Expected |
|-------|----------|
| All findings green | Every check passes — RAG = green |

### 4.6 Dirty repo (issues detected)

```bash
nfr-review hygiene tests/fixtures/hygiene-dirty-repo
```

| Check | Expected |
|-------|----------|
| Multiple amber/red findings | Missing README, CHANGELOG, CI, etc. flagged |

### 4.7 License category — copyleft detection

> Requires `pip install nfr-review[scancode]` (scancode-toolkit optional dependency).

```bash
nfr-review hygiene tests/fixtures/license-dirty-repo --category license
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| `HYG-LIC-001` fires | Copyleft license detected — red for GPL/AGPL, amber for LGPL |
| `HYG-LIC-002` fires | NOTICE file missing or incomplete |
| `HYG-LIC-003` fires | Source files missing license headers |
| `HYG-LIC-004` fires | Invalid or missing SPDX license expressions |

```bash
nfr-review hygiene tests/fixtures/license-clean-repo --category license
```

| Check | Expected |
|-------|----------|
| All license findings green | All deps permissive, NOTICE present, headers present, SPDX valid |

### 4.8 License — scancode not installed

If scancode-toolkit is **not** installed (`pip install nfr-review` without `[scancode]`):

```bash
nfr-review hygiene /tmp/uat-target --category license
```

| Check | Expected |
|-------|----------|
| Run completes | Does not crash on missing scancode |
| Warning logged | `scancode-toolkit not installed` at WARNING level |
| No license findings | License rules skipped — collector produces no evidence |

### 4.9 License in combined report

```bash
nfr-review report /tmp/uat-target --output-dir /tmp/report-license
```

| Check | Expected |
|-------|----------|
| License findings included | `HYG-LIC-*` findings appear in combined markdown, CSV, and JSONL |
| Category column | License findings show `license` category |

---

## 5. Report Command

### 5.1 Full combined report

```bash
nfr-review report /tmp/uat-target --output-dir /tmp/report-out
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| Timestamped `.md` file | Markdown report with summary tables |
| Timestamped `.csv` file | Combined NFR + hygiene findings |
| Timestamped `.jsonl` file | Combined JSONL output |
| Markdown structure | RAG x severity summary table, source/test partitioned findings |

### 5.2 Skip tests

```bash
nfr-review report /tmp/uat-target --no-tests --output-dir /tmp/report-notest
```

| Check | Expected |
|-------|----------|
| No test execution section | Markdown report omits pytest results |
| Faster execution | No pytest invocation overhead |

### 5.3 Skip deps

```bash
nfr-review report /tmp/uat-target --no-deps --output-dir /tmp/report-nodeps
```

| Check | Expected |
|-------|----------|
| No dependency section | Markdown report omits deps analysis |
| No API calls to deps.dev | Faster execution, no network dependency |

---

## 6. Dependency Analysis (`deps`)

### 6.1 Basic dependency scan

```bash
nfr-review deps /tmp/uat-target
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| Ecosystem detected | Java/Maven from `pom.xml` |
| Upgrade recommendations | Lists outdated dependencies with recommended versions |
| Output to terminal | Table rendered to stdout |

### 6.2 Output to file

```bash
nfr-review deps /tmp/uat-target --output /tmp/deps-report.md
```

| Check | Expected |
|-------|----------|
| File created | Markdown report at specified path |
| Terminal output | Minimal (file path confirmation) |

### 6.3 No-tree mode (skip transitive resolution)

```bash
nfr-review deps /tmp/uat-target --no-tree
```

| Check | Expected |
|-------|----------|
| Faster execution | Skips transitive dependency resolution |
| Direct deps only | No transitive dependency tree in output |

### 6.4 Multi-ecosystem repo

```bash
nfr-review deps tests/fixtures/multi-ecosystem-deps-repo
```

| Check | Expected |
|-------|----------|
| Multiple ecosystems detected | Handles mixed package managers |
| Per-ecosystem sections | Each ecosystem's deps reported separately |

---

## 7. Fault Tolerance

### 7.1 Missing target directory

```bash
nfr-review run /nonexistent/path
```

| Check | Expected |
|-------|----------|
| Exit code | 1 |
| Clear error message | Target path does not exist |

### 7.2 Invalid config

```bash
nfr-review run /tmp/uat-target --config tests/fixtures/configs/invalid.yaml
```

| Check | Expected |
|-------|----------|
| Exit code | 1 |
| Validation error | Describes what's wrong with the config |

### 7.3 Collector failure doesn't abort

A collector that throws should be caught and surfaced as a warning, not crash the run.

| Check | Expected |
|-------|----------|
| Run completes | Other collectors/rules execute normally |
| Warning in output | Failed collector noted in run metadata / warnings |

### 7.4 Helm without binary

If `helm` is not installed:

```bash
nfr-review run tests/fixtures/helm-sample-repo
```

| Check | Expected |
|-------|----------|
| Run completes | Does not crash on missing `helm` |
| Static analysis runs | `Chart.yaml` and `values.yaml` still analysed |
| Warning logged | `helm binary not found` at WARNING level |

---

## 8. Band 2 — LLM-Augmented Rules

> Requires `ANTHROPIC_API_KEY` set in the environment.

### 8.1 PII detection with LLM

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
nfr-review run tests/fixtures/java-pii-sample
```

| Check | Expected |
|-------|----------|
| `pii-in-log-statements` rule fires | Findings present |
| Confidence levels varied | Real PII at ~0.85 confidence, false positives at ~0.4 |
| LLM calls made | Visible in `-vv` debug output |

### 8.2 PII detection without LLM

```bash
unset ANTHROPIC_API_KEY
nfr-review run tests/fixtures/java-pii-sample
```

| Check | Expected |
|-------|----------|
| Rule still fires | Falls back to regex-only detection |
| All findings at confidence 0.6 | No LLM triage — uniform amber confidence |

---

## 9. Output Quality

### 9.1 CSV structure

```bash
head -1 nfr-review.csv
```

| Check | Expected |
|-------|----------|
| Header row | 10 columns in fixed order |
| No empty required fields | Every finding has rule_id, severity, rag |
| Paths are relative | File paths relative to target root |

### 9.2 JSONL structure

```bash
head -1 nfr-review.jsonl | python3 -m json.tool
```

| Check | Expected |
|-------|----------|
| Line 1 is valid JSON | Run metadata object |
| Remaining lines valid JSON | Each line parseable as a finding |
| Consistent schema | All findings have the same keys |

### 9.3 Markdown report structure

Check `reports/nfr-review-*.md`:

| Check | Expected |
|-------|----------|
| Summary table | RAG x severity matrix with counts |
| Source/test partitioning | Findings split by code region |
| Skipped rules section | Lists rules that didn't run (with reason) |

---

## 10. Performance

### 10.1 Single-repo scan time

```bash
time nfr-review run /tmp/uat-target
```

| Check | Expected |
|-------|----------|
| Wall time | < 30 seconds for a medium Java project |
| No unnecessary network calls | Deps.dev calls only when deps analysis is active |

### 10.2 Concurrent prefetch

```bash
time nfr-review deps /tmp/uat-target -v
```

| Check | Expected |
|-------|----------|
| Concurrent API calls visible | Multiple ecosystems fetched in parallel |
| Response caching | Repeated deps.dev lookups use cache |

---

## 11. Edge Cases

### 11.1 Empty repository

```bash
mkdir /tmp/empty-repo && cd /tmp/empty-repo && git init
nfr-review run .
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| Zero findings | No collectors match, no rules fire |
| Clean summary | Shows 0 collectors, 0 rules, 0 findings |

### 11.2 Polyglot repository

```bash
nfr-review run tests/fixtures/polyglot-sample-repo
```

| Check | Expected |
|-------|----------|
| Multiple tech detected | Java + Go + Python (or whichever combo is in fixture) |
| Cross-language rules fire | `bare-except-catch-all`, `logging-to-stdout` across languages |

### 11.3 Target is a file, not directory

```bash
nfr-review run /tmp/uat-target/pom.xml
```

| Check | Expected |
|-------|----------|
| Exit code | 1 |
| Error message | Target must be a directory |

---

## Checklist Summary

| # | Area | Scenarios | Status |
|---|------|-----------|--------|
| 1 | Informational commands | list-rules, explain (valid + invalid) | |
| 2 | Core scan | no-config, config-driven, custom paths, threshold, verbosity, log-file | |
| 3 | Tech filtering | spring gating, rules.skip, include_only, kustomize | |
| 4 | Hygiene | list-checks, full scan, format, category, clean/dirty repos, license (copyleft/NOTICE/headers/SPDX), scancode graceful skip | |
| 5 | Report | full, no-tests, no-deps | |
| 6 | Deps | basic, file output, no-tree, multi-ecosystem | |
| 7 | Fault tolerance | missing target, invalid config, collector failure, no helm | |
| 8 | Band 2 LLM | with key, without key | |
| 9 | Output quality | CSV structure, JSONL structure, Markdown structure | |
| 10 | Performance | scan time, concurrent prefetch | |
| 11 | Edge cases | empty repo, polyglot, file-as-target | |
