# nfr-review — Consolidated UAT Checklist + Nightly Setup Guide

**Version:** 0.1.0
**Date:** 2026-05-25

This document has two parts:
1. **Part A** — Single UAT checklist covering all features (core CLI, M022, M023)
2. **Part B** — Step-by-step guide to install nfr-review as a nightly scan on `agentic-java-demo`

---

# Part A — UAT Checklist

## 0. Environment Setup

```bash
cd ~/dev/nfr-review
rm -rf .venv
./scripts/setup.sh
source .venv/bin/activate
nfr-review version          # expect: 0.1.0
```

- [ ] Exit code 0, `.venv/` created, `pip show nfr-review` shows editable install
- [ ] `which nfr-review` points to `.venv/bin/nfr-review`

Clone the target repo (if not already at `../agentic-java-demo`):

```bash
git clone https://github.com/JimAKennedy/agentic-java-demo.git /tmp/uat-target
```

Generate findings for issue-sync tests:

```bash
cd ../agentic-java-demo
nfr-review run . --jsonl /tmp/m023-findings.jsonl
```

- [ ] Exit code 0, `/tmp/m023-findings.jsonl` created and non-empty

---

## 1. Informational Commands

```bash
nfr-review list-rules
```
- [ ] Exit 0, >= 60 rules listed with ID, band, summary

```bash
nfr-review explain dockerfile-base-pinning
```
- [ ] Exit 0, full rule explanation shown

```bash
nfr-review explain nonexistent-rule-id
```
- [ ] Exit 1, "Rule not found" error

---

## 2. Core Scan (`run`)

```bash
cd /tmp/uat-target
nfr-review run .
```
- [ ] Exit 0
- [ ] Summary on stderr: tech_detected, collectors_run, rules_run, findings counts
- [ ] `nfr-review.csv` and `nfr-review.jsonl` created
- [ ] Java/Spring Boot auto-detected, findings > 0

```bash
nfr-review run . --config tests/fixtures/configs/agentic-java-demo.yaml
```
- [ ] Spring-specific rules fire, `health-endpoint-missing` skipped

```bash
nfr-review run . --csv /tmp/custom.csv --jsonl /tmp/custom.jsonl
```
- [ ] Files at custom paths, no default-path files in cwd

```bash
nfr-review run . --score
```
- [ ] Design maturity score on stderr (0-100, letter grade A-F)
- [ ] Per-category breakdown (SEC, OBS, etc.)

---

## 3. SARIF Output (M022)

```bash
nfr-review run . --sarif /tmp/test.sarif --score
```
- [ ] `/tmp/test.sarif` is valid JSON, SARIF v2.1.0
- [ ] Opens in VS Code SARIF Viewer (optional visual check)

---

## 4. Baseline & Regression Detection (M022)

```bash
nfr-review run . --jsonl /tmp/baseline.jsonl
nfr-review run . --baseline /tmp/baseline.jsonl --score
```
- [ ] Second run shows diff: only new/changed findings
- [ ] Trend indicator on stderr (arrow + delta)

---

## 5. Severity Threshold & Verbosity

```bash
# Threshold test — should exit 2
echo 'version: 1
severity_threshold: info' > /tmp/threshold-test.yaml
nfr-review run /tmp/uat-target --config /tmp/threshold-test.yaml
echo $?
```
- [ ] Exit code 2 (threshold exceeded), findings still written

```bash
nfr-review run /tmp/uat-target -v 2>/tmp/info.log
nfr-review run /tmp/uat-target -vv 2>/tmp/debug.log
nfr-review run /tmp/uat-target -q 2>/tmp/quiet.log
```
- [ ] `-v` shows INFO messages, `-vv` shows DEBUG, `-q` minimal output

```bash
nfr-review run /tmp/uat-target -v -q
```
- [ ] Exit 2 (mutual exclusion error)

```bash
nfr-review run /tmp/uat-target -v --log-file /tmp/nfr.log
```
- [ ] `/tmp/nfr.log` exists with log content, stderr minimal

---

## 6. Path Exclusion

```bash
nfr-review run /tmp/uat-target
nfr-review run /tmp/uat-target --exclude-tests
```
- [ ] Default run excludes test-path findings
- [ ] `--exclude-tests` further filters — fewer findings

```bash
echo 'version: 1
exclude_paths:
  - "src/nfr_review/collectors/"' > /tmp/exclude-test.yaml
nfr-review run . --config /tmp/exclude-test.yaml
```
- [ ] No findings from excluded prefix, other findings present

---

## 7. Tech Filtering & Rule Gating

```bash
# No config — Spring rules skipped
nfr-review run /tmp/uat-target 2>&1 | grep -i "skipped"
```
- [ ] Spring-specific rules skipped without `spring_boot: true`

```bash
# rules.skip
echo 'version: 1
rules:
  skip:
    - dockerfile-base-pinning
    - k8s-resource-limits-missing' > /tmp/skip-test.yaml
nfr-review run /tmp/uat-target --config /tmp/skip-test.yaml
```
- [ ] Skipped rules absent from output

```bash
# rules.include_only
echo 'version: 1
rules:
  include_only:
    - dockerfile-base-pinning
    - dockerfile-user-directive' > /tmp/include-test.yaml
nfr-review run /tmp/uat-target --config /tmp/include-test.yaml
```
- [ ] Only the two specified rules in findings

- [ ] Kustomize: overlay patch files skipped, base manifests analyzed

---

## 8. Cross-Artifact Coherence (M022)

```bash
nfr-review run /tmp/uat-target --score
grep "cross-artifact" nfr-review.csv
```
- [ ] `cross-artifact-user-conflict` and/or `cross-artifact-image-drift` findings present

---

## 9. Hygiene Command

```bash
nfr-review hygiene --list-checks
```
- [ ] Exit 0, categories: bld, ci, com, doc, license, prv; >= 23 checks

```bash
nfr-review hygiene /tmp/uat-target --output-dir /tmp/hygiene-out
```
- [ ] `hygiene-report.csv` and `hygiene-report.jsonl` in output dir

```bash
nfr-review hygiene /tmp/uat-target --format csv --output-dir /tmp/hyg-csv
nfr-review hygiene /tmp/uat-target --format jsonl --output-dir /tmp/hyg-jsonl
```
- [ ] CSV-only creates only `.csv`, JSONL-only creates only `.jsonl`

```bash
nfr-review hygiene /tmp/uat-target --category ci,com
```
- [ ] Only CI and Community findings, no other categories

```bash
nfr-review hygiene tests/fixtures/hygiene-clean-repo
```
- [ ] All findings green

```bash
nfr-review hygiene tests/fixtures/hygiene-dirty-repo
```
- [ ] Multiple amber/red findings

```bash
nfr-review hygiene /tmp/uat-target --severity-threshold info
echo $?
```
- [ ] Exit 2 if findings present

---

## 10. Hygiene — License (optional, needs `[scancode]`)

```bash
pip install -e ".[scancode]"
nfr-review hygiene tests/fixtures/license-dirty-repo --category license
```
- [ ] HYG-LIC-001 through HYG-LIC-004 fire

```bash
nfr-review hygiene tests/fixtures/license-clean-repo --category license
```
- [ ] All license findings green

Without scancode installed:
- [ ] `nfr-review hygiene /tmp/uat-target --category license` completes with warning, no crash

---

## 11. Report Command

```bash
nfr-review report /tmp/uat-target --output-dir /tmp/report-out
```
- [ ] Timestamped `.md`, `.csv`, `.jsonl` files created
- [ ] Markdown has RAG x severity summary table

```bash
nfr-review report /tmp/uat-target --no-tests --output-dir /tmp/report-notest
```
- [ ] No pytest results section

```bash
nfr-review report /tmp/uat-target --no-deps --output-dir /tmp/report-nodeps
```
- [ ] No dependency analysis section

```bash
nfr-review report /tmp/uat-target --exclude-tests --output-dir /tmp/report-excl
```
- [ ] Test-path findings absent from report

```bash
nfr-review report /tmp/uat-target --no-diagrams --output-dir /tmp/report-nodiag
```
- [ ] No Mermaid diagrams, other sections intact

```bash
nfr-review report . --output-dir /tmp/report-score --score --no-tests --no-deps
```
- [ ] Design maturity score section in Markdown report

---

## 12. High-DPI Diagrams & PDF (M023)

```bash
cd ../agentic-java-demo
nfr-review report . --output-dir /tmp/m023-report --score --no-tests --no-deps
```
- [ ] Report files created
- [ ] Mermaid diagrams render at 3x scale (sharp, not blurry)
- [ ] Severity column headers colored by RAG

PDF (requires `weasyprint`):
- [ ] Major sections start on new page
- [ ] Diagrams not split across pages

---

## 13. Issue Sync Lifecycle (M023)

```bash
nfr-review issues sync /tmp/m023-findings.jsonl --dry-run
```
- [ ] Exit 0, planned actions shown (create/update/close), no API calls

```bash
nfr-review issues sync /tmp/m023-findings.jsonl --dry-run --first-run-cap 5
```
- [ ] Max 5 creates shown, remaining deferred

```bash
nfr-review issues sync /tmp/m023-findings.jsonl --dry-run --rag-min red
```
- [ ] Only red findings in create plan

```bash
nfr-review issues sync /tmp/m023-findings.jsonl --dry-run --rag-min amber
```
- [ ] Red + amber findings shown, green excluded

```bash
nfr-review issues sync /tmp/m023-findings.jsonl --dry-run --extra-labels "team:platform,sprint:23"
```
- [ ] Custom labels listed alongside defaults

---

## 14. Backward Compatibility (M023)

```bash
nfr-review issues --dry-run ../agentic-java-demo
```
- [ ] Exit 0, one-shot scan + issue plan — same as pre-M023 behavior

---

## 15. Issue Filing — One-Shot (M022)

```bash
nfr-review issues . --dry-run
```
- [ ] Shows what issues would be filed (titles + bodies)

---

## 16. Dependency Analysis (`deps`)

```bash
nfr-review deps /tmp/uat-target
```
- [ ] Exit 0, Maven ecosystem detected, upgrade recommendations shown

```bash
nfr-review deps /tmp/uat-target --output /tmp/deps-report.md
```
- [ ] Markdown file at specified path

```bash
nfr-review deps /tmp/uat-target --no-tree
```
- [ ] Faster, direct deps only

```bash
nfr-review deps /tmp/uat-target --dot /tmp/deps.dot
```
- [ ] Valid Graphviz DOT file

---

## 17. Fault Tolerance

```bash
nfr-review run /nonexistent/path
```
- [ ] Exit 1, clear error

```bash
nfr-review run /tmp/uat-target --config tests/fixtures/configs/invalid.yaml
```
- [ ] Exit 1, validation error

- [ ] Collector failure doesn't abort the run (warning surfaced)
- [ ] `nfr-review run tests/fixtures/helm-sample-repo` completes without `helm` binary

---

## 18. Band 2 — LLM Rules (optional, needs `ANTHROPIC_API_KEY`)

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
nfr-review run tests/fixtures/java-pii-sample
```
- [ ] `pii-in-log-statements` fires with varied confidence levels

```bash
unset ANTHROPIC_API_KEY
nfr-review run tests/fixtures/java-pii-sample
```
- [ ] Falls back to regex-only, uniform confidence 0.6

---

## 19. Edge Cases

```bash
mkdir /tmp/empty-repo && cd /tmp/empty-repo && git init
nfr-review run .
```
- [ ] Exit 0, zero findings, clean summary

```bash
nfr-review run tests/fixtures/polyglot-sample-repo
```
- [ ] Multiple techs detected, cross-language rules fire

```bash
nfr-review run /tmp/uat-target/pom.xml
```
- [ ] Exit 2, "not a valid directory" error

---

## 20. Output Quality

- [ ] CSV: header row present, no empty required fields, relative paths
- [ ] JSONL: line 1 is valid JSON metadata, remaining lines are findings
- [ ] Markdown: RAG x severity matrix, source/test partitioning, skipped rules section

---

## 21. Performance

```bash
time nfr-review run /tmp/uat-target
```
- [ ] < 30 seconds for medium Java project

```bash
time nfr-review deps /tmp/uat-target -v
```
- [ ] Concurrent API calls visible, response caching active

---

## 22. Cleanup

```bash
cd ~/dev/nfr-review
deactivate
rm -rf .venv
rm -rf /tmp/uat-target /tmp/empty-repo
rm -f /tmp/custom.csv /tmp/custom.jsonl /tmp/test.sarif /tmp/baseline.jsonl
rm -f /tmp/threshold-test.yaml /tmp/exclude-test.yaml
rm -f /tmp/skip-test.yaml /tmp/include-test.yaml
rm -f /tmp/info.log /tmp/debug.log /tmp/quiet.log /tmp/nfr.log
rm -f /tmp/deps-report.md /tmp/deps.dot
rm -f /tmp/m023-findings.jsonl
rm -rf /tmp/hygiene-out /tmp/hyg-csv /tmp/hyg-jsonl
rm -rf /tmp/report-out /tmp/report-notest /tmp/report-nodeps
rm -rf /tmp/report-excl /tmp/report-nodiag /tmp/report-score
rm -rf /tmp/report-license /tmp/m023-report /tmp/m023-pdf
```
- [ ] All temp files and venv removed

---

# Part B — Installing nfr-review as a Nightly Scan on agentic-java-demo

This sets up two GitHub Actions workflows in `agentic-java-demo`:
a **nightly full scan** (creates issues, publishes baseline) and a
**PR diff scan** (comments on PRs, fails on red).

## Prerequisites

- `agentic-java-demo` repo pushed to GitHub (at `JimAKennedy/agentic-java-demo`)
- GitHub Actions enabled on the repo
- The `nfr-review.yaml` config already exists in the repo root (it does)

## Step 1 — Add the nightly workflow

Create `.github/workflows/nfr-review-nightly.yml` in the `agentic-java-demo` repo:

```yaml
name: NFR Review (nightly)

on:
  schedule:
    - cron: "0 3 * * *"          # 03:00 UTC daily
  workflow_dispatch:              # manual trigger for ad-hoc runs

concurrency:
  group: nfr-review-nightly
  cancel-in-progress: false

permissions:
  contents: read
  issues: write
  security-events: write

jobs:
  nfr-review:
    name: NFR Review (nightly)
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run NFR Review
        id: nfr
        uses: JimAKennedy/nfr-review@v1
        with:
          path: .
          config: "nfr-review.yaml"
          fail-on: "never"
          sarif-upload: "true"
          comment: "false"
          create-issues: "true"
          rag-min: "amber"
          first-run-cap: "25"

      - name: Upload baseline artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: nfr-review-baseline
          path: ${{ steps.nfr.outputs.jsonl-path }}
          retention-days: 90

      - name: Upload SARIF artifact
        if: always() && steps.nfr.outputs.sarif-path != ''
        uses: actions/upload-artifact@v4
        with:
          name: nfr-review-sarif
          path: ${{ steps.nfr.outputs.sarif-path }}
          retention-days: 365

      - name: Summary
        if: always()
        run: |
          echo "## NFR Review (nightly)" >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          echo "| Metric | Value |" >> $GITHUB_STEP_SUMMARY
          echo "|--------|-------|" >> $GITHUB_STEP_SUMMARY
          echo "| Findings | ${{ steps.nfr.outputs.findings-count }} |" >> $GITHUB_STEP_SUMMARY
          echo "| Red | ${{ steps.nfr.outputs.red-count }} |" >> $GITHUB_STEP_SUMMARY
          echo "| Amber | ${{ steps.nfr.outputs.amber-count }} |" >> $GITHUB_STEP_SUMMARY
          echo "| Green | ${{ steps.nfr.outputs.green-count }} |" >> $GITHUB_STEP_SUMMARY
          echo "| Issues created | ${{ steps.nfr.outputs.issues-created }} |" >> $GITHUB_STEP_SUMMARY
          echo "| Issues updated | ${{ steps.nfr.outputs.issues-updated }} |" >> $GITHUB_STEP_SUMMARY
          echo "| Issues closed | ${{ steps.nfr.outputs.issues-closed }} |" >> $GITHUB_STEP_SUMMARY
```

## Step 2 — Add the PR workflow

Create `.github/workflows/nfr-review.yml` in the `agentic-java-demo` repo:

```yaml
name: NFR Review

on:
  pull_request:
    branches: [main]

concurrency:
  group: nfr-review-pr-${{ github.event.pull_request.number }}
  cancel-in-progress: true

permissions:
  contents: read
  pull-requests: write
  security-events: write
  actions: read

jobs:
  nfr-review:
    name: NFR Review
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Download nightly baseline
        id: baseline
        uses: dawidd6/action-download-artifact@v6
        with:
          workflow: nfr-review-nightly.yml
          branch: main
          name: nfr-review-baseline
          path: ${{ runner.temp }}/baseline
          if_no_artifact_found: warn

      - name: Run NFR Review
        id: nfr
        uses: JimAKennedy/nfr-review@v1
        with:
          path: .
          config: "nfr-review.yaml"
          fail-on: "red"
          baseline: ${{ steps.baseline.outcome == 'success' && format('{0}/baseline/nfr-review-output.jsonl', runner.temp) || '' }}
          sarif-upload: "true"
          comment: "true"
          create-issues: "false"

      - name: Upload PR scan results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: nfr-review-pr-${{ github.event.pull_request.number }}
          path: ${{ steps.nfr.outputs.jsonl-path }}
          retention-days: 30

      - name: Summary
        if: always()
        run: |
          echo "## NFR Review" >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          echo "| Metric | Value |" >> $GITHUB_STEP_SUMMARY
          echo "|--------|-------|" >> $GITHUB_STEP_SUMMARY
          echo "| Findings | ${{ steps.nfr.outputs.findings-count }} |" >> $GITHUB_STEP_SUMMARY
          echo "| Red | ${{ steps.nfr.outputs.red-count }} |" >> $GITHUB_STEP_SUMMARY
          echo "| Amber | ${{ steps.nfr.outputs.amber-count }} |" >> $GITHUB_STEP_SUMMARY
          echo "| Green | ${{ steps.nfr.outputs.green-count }} |" >> $GITHUB_STEP_SUMMARY
```

## Step 3 — Commit and push

```bash
cd ~/dev/agentic-java-demo
git add .github/workflows/nfr-review-nightly.yml .github/workflows/nfr-review.yml
git commit -m "ci: add nfr-review nightly scan and PR check"
git push origin main
```

## Step 4 — First run (prove it works)

1. Go to **GitHub > agentic-java-demo > Actions > NFR Review (nightly)**
2. Click **Run workflow** (manual dispatch)
3. Wait for the run to complete (~2 min)
4. Verify:
   - [ ] Job succeeded (green check)
   - [ ] Step summary shows findings count, red/amber/green breakdown
   - [ ] SARIF uploaded to **Security > Code scanning alerts**
   - [ ] Issues created in the **Issues** tab (labelled `nfr-review`)
   - [ ] `nfr-review-baseline` artifact published

## Step 5 — Verify PR diff mode

1. Create a test branch and open a PR:
   ```bash
   git checkout -b test/nfr-review-pr
   echo "# test" >> README.md
   git add README.md
   git commit -m "test: trigger nfr-review PR check"
   git push -u origin test/nfr-review-pr
   gh pr create --title "Test NFR review PR check" --body "Testing nfr-review integration"
   ```
2. Wait for the NFR Review check to run
3. Verify:
   - [ ] PR check appears in the Checks tab
   - [ ] Sticky PR comment with RAG summary posted
   - [ ] Diff mode active (fewer findings than nightly, only new/changed)
   - [ ] SARIF results in Security tab
4. Close the test PR and delete the branch:
   ```bash
   gh pr close --delete-branch
   ```

## What You Get

| Trigger | What happens |
|---------|-------------|
| **03:00 UTC daily** | Full scan, SARIF upload, issue sync (create/update/close), baseline published |
| **Every PR to main** | Diff scan against nightly baseline, PR comment, fails on red findings |
| **Manual dispatch** | Same as nightly — use to get an immediate baseline |

## Tuning

| Want to... | Change |
|------------|--------|
| Change scan time | Edit `cron` in nightly workflow |
| Fail PRs on amber too | Set `fail-on: "red+amber"` in PR workflow |
| Limit issue creation | Adjust `first-run-cap` (default 25) |
| Only file red issues | Set `rag-min: "red"` in nightly workflow |
| Add labels to issues | Set `extra-labels: "team:platform,nfr"` |
| Skip Spring rules | Edit `nfr-review.yaml` > `rules.skip` |
| Use container mode | Set `execution: "container"` in both workflows |
