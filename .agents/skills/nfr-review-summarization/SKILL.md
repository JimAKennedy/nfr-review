# NFR Review Summarization

Generate LLM-powered executive summaries for non-functional review reports, assessing open-source readiness and production fitness.

## When to use

- When generating PDF reports with `--pdf` flag
- When crafting or tuning the executive summary prompt
- When modifying the ExecSummary schema or verdict criteria
- When reviewing or improving summarization output quality

## Architecture

### Data flow

```
RunResult + HygieneResult + PytestResult + DepsSection
  -> _build_findings_summary() compresses to counts + top findings
  -> _build_prompt_data() creates structured JSON for LLM
  -> ClaudeClient.analyze() sends prompt + data
  -> JSON response parsed into ExecSummary Pydantic model
  -> render_pdf() embeds summary into HTML -> PDF via weasyprint
```

### Key files

| File | Purpose |
|------|---------|
| `src/nfr_review/output/summary_models.py` | ExecSummary and RemediationItem Pydantic models |
| `src/nfr_review/output/summarize.py` | Prompt engineering and LLM call orchestration |
| `src/nfr_review/output/pdf.py` | HTML/CSS template with verdict box rendering |
| `src/nfr_review/llm_client.py` | ClaudeClient wrapper around Anthropic SDK |
| `tests/test_summarize.py` | Unit tests with mocked LLM responses |

### ExecSummary schema

```python
class ExecSummary(BaseModel):
    verdict: Literal["fit", "conditional", "unfit"]
    verdict_explanation: str
    risk_highlights: list[str]
    remediation_priorities: list[RemediationItem]
    production_risks: str
    open_source_readiness: str
    overall_score: int  # 0-100
```

### Verdict criteria

| Verdict | Criteria |
|---------|----------|
| `fit` | No critical/high findings, adequate test coverage, dependencies managed |
| `conditional` | Some high findings but all have clear remediation paths |
| `unfit` | Critical security/licensing issues or fundamental architectural problems |

## Prompt tuning

The system prompt in `summarize.py` instructs the LLM to:
1. Assess open-source readiness (licensing, documentation, security posture)
2. Evaluate production fitness (dependency health, test coverage, architectural risks)
3. Provide actionable remediation priorities with urgency levels
4. Reference actual rule IDs and finding counts from the data

When tuning:
- Keep the JSON schema instruction explicit to avoid format drift
- The `_build_findings_summary()` function limits critical/high findings to top 20 to stay within token budgets
- The `max_tokens=2048` on the analyze call is generous for the expected response size
- Code-fence stripping handles LLMs that wrap JSON in markdown

## Graceful degradation

- No ANTHROPIC_API_KEY: returns None, PDF renders without summary section
- LLM returns invalid JSON: returns None with warning log
- LLM response fails schema validation: returns None with warning log
- weasyprint not installed: CLI exits with install instructions
- mmdc not installed: Mermaid diagrams skipped, DOT diagrams attempted via graphviz
