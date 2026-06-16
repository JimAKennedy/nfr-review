# Architecture Documentation (Experimental)

`nfr-review arch` generates architecture documentation for one or more repositories, including domain models, component diagrams, technology maps, and market comparisons. It is experimental — the output format and analysis depth are evolving.

## Usage

```bash
# Generate architecture docs for a single repo (JSON + Markdown + PDF)
nfr-review arch /path/to/target/repo

# Generate for multiple repos as a unified report
nfr-review arch /path/to/repo1 /path/to/repo2

# Skip LLM-based analysis (domain model enhancement, market comparison)
nfr-review arch --no-llm /path/to/target/repo

# Output only JSON and Markdown (no PDF)
nfr-review arch --format json --format md /path/to/target/repo
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir PATH` | `reports` | Directory where report files are written |
| `--format FORMAT` | `json` + `md` + `pdf` | Output format(s): `json`, `md`, `pdf` (repeat for multiple) |
| `--no-llm` | off | Skip LLM-based analysis (domain model enhancement, market comparison) |
| `--diagram-mode MODE` | `hierarchical` | Component diagram layout: `hierarchical` (overview + detail) or `flat` |
| `-v` / `-q` / `--log-file` | — | Same as `run` command |

## What it produces

- **Technology map** — detected languages, frameworks, infrastructure, and CI/CD tools with file counts and locations
- **Domain model** — extracted entity relationships and bounded contexts (LLM-enhanced when a backend is configured)
- **Component diagrams** — Mermaid architecture diagrams in hierarchical or flat layout
- **Market comparison** — how the project's architecture compares to common patterns in its domain (LLM-assisted)
- **Multi-repo unified view** — when given multiple repos, produces a cross-repo architecture overview

## LLM dependency

Without an LLM backend, `arch` still produces technology maps and static component analysis. With an LLM backend configured, it adds domain model enhancement and market comparison sections. See [install.md](install.md#7-llm-features) for LLM setup.
