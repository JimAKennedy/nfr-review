# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x: (pre-release)  |

## Reporting a Vulnerability

If you discover a security vulnerability in nfr-review, please report it
responsibly:

1. **Email:** [the.jim.kennedy@gmail.com](mailto:the.jim.kennedy@gmail.com)
2. **GitHub Security Advisories:**
   [Report via GitHub](https://github.com/JimAKennedy/nfr-review/security/advisories/new)

Please **do not** open a public issue for security vulnerabilities.

### Response Timeline

| Stage      | Target        |
|------------|---------------|
| Acknowledge | 48 hours      |
| Assessment  | 7 days        |
| Fix release | 30 days       |

We will keep you informed of progress toward a fix and coordinate disclosure
timing with you.

## Scope

nfr-review is a static analysis tool that scans repository files locally. It
does **not** store or transmit user repository contents beyond the local
filesystem.

When LLM-assisted rules are enabled (PII detection, ADR drift analysis),
nfr-review sends code snippets to the **Anthropic API** for analysis using your
configured `ANTHROPIC_API_KEY`. These API calls are subject to
[Anthropic's usage policy](https://www.anthropic.com/policies). No repository
data is sent to any other external service.

## Security Practices

- Dependencies are pinned and audited via CI (`bandit`, `gitleaks`).
- The project does not execute user-supplied code; it performs read-only AST
  parsing and pattern matching.
- API keys are read from environment variables, never stored in configuration
  files.
