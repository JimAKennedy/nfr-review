# M023 S01 UAT Script — Issue Sync & High-DPI Rendering

**Version:** 0.1.0
**Last updated:** 2026-05-25

This script covers acceptance testing for the M023 S01 features:
issue sync lifecycle (`issues sync` subcommand) and high-DPI diagram rendering.

Run against a real target repository — `agentic-java-demo` is the reference target.

---

## 0. Prerequisites

```bash
cd /path/to/nfr-review
source .venv/bin/activate
nfr-review version
# Expected: 0.1.0
```

Generate findings for issue sync tests:

```bash
cd ../agentic-java-demo
nfr-review run . --jsonl /tmp/m023-findings.jsonl
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| `/tmp/m023-findings.jsonl` created | Non-empty JSONL file |

---

## 1. Issue Sync — Dry Run

```bash
nfr-review issues sync /tmp/m023-findings.jsonl --dry-run
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| No GitHub API calls | Output shows planned actions only |
| Create/update/close decisions | Each finding mapped to create, update, or close |
| Output on stdout | Human-readable plan summary |

---

## 2. Issue Sync — First-Run Cap

```bash
nfr-review issues sync /tmp/m023-findings.jsonl --dry-run --first-run-cap 5
```

| Check | Expected |
|-------|----------|
| Max 5 creates shown | When no prior `nfr-review` issues exist, caps at 5 |
| Remaining findings deferred | Findings beyond cap noted as deferred |

---

## 3. Issue Sync — RAG Filter (red only)

```bash
nfr-review issues sync /tmp/m023-findings.jsonl --dry-run --rag-min red
```

| Check | Expected |
|-------|----------|
| Only red findings shown | No amber or green findings in create plan |
| Lower count than unfiltered | Fewer planned issues than test 1 |

---

## 4. Issue Sync — RAG Filter (amber+)

```bash
nfr-review issues sync /tmp/m023-findings.jsonl --dry-run --rag-min amber
```

| Check | Expected |
|-------|----------|
| Red and amber findings shown | Green findings excluded |
| Count between red-only and all | More than test 3, fewer than test 1 |

---

## 5. Issue Sync — Extra Labels

```bash
nfr-review issues sync /tmp/m023-findings.jsonl --dry-run --extra-labels "team:platform,sprint:23"
```

| Check | Expected |
|-------|----------|
| Labels shown in plan | `team:platform` and `sprint:23` listed alongside default labels |

---

## 6. Backward Compatibility — `issues` One-Shot

```bash
nfr-review issues --dry-run ../agentic-java-demo
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| Scan + issue plan in one step | Runs NFR scan then shows issue filing plan |
| No regression | Same behavior as pre-M023 `issues` command |

---

## 7. PDF Rendering — High-DPI Diagrams

```bash
cd ../agentic-java-demo
nfr-review report . --output-dir /tmp/m023-report --score --no-tests --no-deps
```

| Check | Expected |
|-------|----------|
| Exit code | 0 |
| Report files created | Markdown, CSV, JSONL in `/tmp/m023-report/` |

Open the Markdown report and verify diagrams:

| Check | Expected |
|-------|----------|
| Mermaid diagrams sharp | 3x scale rendering (not blurry) |
| SVG renderers used | Where available, SVG versions present |
| Severity column headers | Colored by RAG rating in tables |

---

## 8. PDF Section Page Breaks

If you generate a PDF (requires `weasyprint` or similar):

```bash
nfr-review report . --output-dir /tmp/m023-pdf --score --no-tests --no-deps
```

| Check | Expected |
|-------|----------|
| Major sections start on new page | Section breaks between NFR, Hygiene, Deps |
| Diagrams not split across pages | Each diagram on a single page |

---

## 9. Cleanup

```bash
rm -f /tmp/m023-findings.jsonl
rm -rf /tmp/m023-report /tmp/m023-pdf
```

---

## Checklist Summary

| # | Area | Scenarios | Status |
|---|------|-----------|--------|
| 0 | Prerequisites | venv active, findings generated | |
| 1 | Issue sync dry-run | Planned actions shown, no API calls | |
| 2 | First-run cap | Caps at 5 creates | |
| 3 | RAG filter (red) | Only red findings | |
| 4 | RAG filter (amber+) | Red + amber findings | |
| 5 | Extra labels | Custom labels in plan | |
| 6 | Backward compat | One-shot `issues` still works | |
| 7 | High-DPI diagrams | Sharp Mermaid, SVG, colored headers | |
| 8 | PDF page breaks | Section breaks, diagrams not split | |
| 9 | Cleanup | Temp files removed | |
