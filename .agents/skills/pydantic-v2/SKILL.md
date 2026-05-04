---
name: pydantic-v2
description: Pydantic v2 idioms — BaseModel, Field constraints, validators, model_config, discriminated unions, settings, JSON schema, serialization. Use when defining or modifying data models, parsing/validating external input (CLI args, YAML configs, API responses), or designing the evidence/finding/report schema.
---

# Pydantic v2

Pydantic v2 is the data layer for nfr-review. Every external input (config files, tool output, LLM responses) and every persisted artifact (findings, reports, evidence) goes through a model. Models are the contract.

This skill covers v2 only. v1 syntax (`class Config:`, `@validator`, `parse_obj`) is rejected on review.

## When to use a model

- Anywhere data crosses a boundary: file → memory, network → memory, LLM → app, app → JSON
- Any structure with > 2 fields or any field with constraints
- Anything that will be serialized to disk (use `model_dump`/`model_dump_json`)

Don't use a model for purely-internal value objects with no validation needs — a `dataclass` or `NamedTuple` is lighter.

## Base model conventions

```python
from pydantic import BaseModel, ConfigDict, Field

class Finding(BaseModel):
    model_config = ConfigDict(
        extra="forbid",          # reject unknown fields — catches typos in YAML
        frozen=True,             # immutable; safer to pass around
        str_strip_whitespace=True,
        validate_assignment=True, # re-validate on attribute set
    )

    id: str = Field(pattern=r"^F\d{4}$")
    title: str = Field(min_length=1, max_length=120)
    severity: Literal["info", "low", "medium", "high", "critical"]
    category: Literal["performance", "security", "observability", "ops", "a11y"]
    evidence: list["Evidence"] = Field(default_factory=list)
    score: float = Field(ge=0.0, le=10.0)
```

Defaults to set on every model in this project:
- `extra="forbid"` — typos in YAML/JSON should fail loudly
- `frozen=True` for value-like models (findings, evidence) — mutation is a smell
- `str_strip_whitespace=True` — user input is messy

## Field constraints

Prefer `Field(...)` constraints over hand-written validators when the constraint is structural.

```python
score: float = Field(ge=0.0, le=10.0)
title: str = Field(min_length=1, max_length=120)
tags: list[str] = Field(default_factory=list, max_length=20)
url: str = Field(pattern=r"^https?://")
```

For type-narrow strings, prefer `Literal[...]` over a free `str` with a regex.

## Validators

Use `@field_validator` for single-field rules, `@model_validator` for cross-field rules.

```python
from pydantic import field_validator, model_validator

class Report(BaseModel):
    findings: list[Finding]
    summary: str

    @field_validator("findings")
    @classmethod
    def at_least_one_critical_has_evidence(cls, v: list[Finding]) -> list[Finding]:
        for f in v:
            if f.severity == "critical" and not f.evidence:
                raise ValueError(f"critical finding {f.id} must have evidence")
        return v

    @model_validator(mode="after")
    def summary_mentions_critical_count(self) -> "Report":
        n = sum(1 for f in self.findings if f.severity == "critical")
        if n > 0 and "critical" not in self.summary.lower():
            raise ValueError("summary must mention critical findings when any exist")
        return self
```

Validator rules:
- `mode="before"`: input mutation/coercion, runs on raw input
- `mode="after"` (default): runs on the already-parsed value — types are guaranteed
- Always include `@classmethod` for `field_validator`
- Return the validated value; raise `ValueError` on failure

## Discriminated unions

Use for evidence types, finding categories, anything where shape depends on a tag field.

```python
from typing import Annotated, Literal, Union
from pydantic import Field

class CodeEvidence(BaseModel):
    kind: Literal["code"] = "code"
    file: Path
    line: int
    snippet: str

class CommandEvidence(BaseModel):
    kind: Literal["command"] = "command"
    command: str
    exit_code: int
    output: str

Evidence = Annotated[
    Union[CodeEvidence, CommandEvidence],
    Field(discriminator="kind"),
]
```

This gives clean JSON, fast parsing, and unambiguous error messages.

## Settings (CLI/env config)

Use `pydantic-settings` (separate package: `pydantic-settings`) for env-var and `.env` loading. Do not roll your own.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class NfrSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NFR_",
        env_file=".env",
        extra="ignore",
    )

    anthropic_api_key: str
    output_dir: Path = Path("./nfr-reports")
    max_concurrency: int = Field(default=4, ge=1, le=32)
```

Never reach for `os.environ` directly — settings models give you typing, validation, and documentation in one place.

## Serialization

```python
finding.model_dump()              # → dict
finding.model_dump(mode="json")   # → JSON-safe dict (Path → str, datetime → iso)
finding.model_dump_json(indent=2) # → JSON string
Finding.model_validate(data)      # ← dict (parse with validation)
Finding.model_validate_json(text) # ← JSON string
```

- Always use `mode="json"` when the output goes to disk or wire — handles `Path`, `datetime`, `UUID`, etc.
- Use `exclude_none=True` only when callers expect optional fields to be omitted
- Use `by_alias=True` when the wire format uses different names from the Python attributes

## YAML/TOML loading

Pydantic does not parse YAML or TOML directly. Two-step:

```python
import yaml
from pathlib import Path

raw = yaml.safe_load(Path("config.yaml").read_text())
config = NfrConfig.model_validate(raw)
```

Always use `yaml.safe_load` (never `yaml.load`).

## JSON schema for tooling

```python
schema = NfrReport.model_json_schema()
Path("schemas/nfr-report.json").write_text(json.dumps(schema, indent=2))
```

Useful for: documenting the report format, generating editor autocomplete, validating downstream consumers.

## Aliases for compatibility

When the input format uses different names (e.g. `kebab-case` keys in YAML, camelCase from JS):

```python
class Finding(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    finding_id: str = Field(alias="finding-id")
```

`populate_by_name=True` lets both Python and YAML names work as input.

## Common mistakes

- `class Config:` — that's v1. Use `model_config = ConfigDict(...)`.
- `@validator` — that's v1. Use `@field_validator` (v2) with `@classmethod`.
- `.dict()` / `.json()` — v1. Use `.model_dump()` / `.model_dump_json()`.
- `parse_obj` / `parse_raw` — v1. Use `model_validate` / `model_validate_json`.
- Mutable defaults like `field: list = []` — use `Field(default_factory=list)`.
- Loose `Any` everywhere — defeats the point of Pydantic. Be specific.
- Forgetting `extra="forbid"` — silent typos in YAML get parsed and lost.

## Performance notes

- Pydantic v2 is fast (Rust core). Don't pre-optimize by avoiding it.
- For hot paths, prefer `TypeAdapter` over re-parsing the same shape:
  ```python
  finding_adapter = TypeAdapter(list[Finding])
  findings = finding_adapter.validate_python(raw)
  ```
- `model_construct(**data)` skips validation — only use when input is already trusted (e.g. round-tripping).

## Verification

After model changes:

```bash
ruff check .
pytest tests/test_models.py
```

When schema changes affect persisted data, regenerate the JSON schema and review the diff before claiming done.
