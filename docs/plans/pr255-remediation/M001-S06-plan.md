# M001/S06 implementation plan — Report fidelity and LLM payloads

**Slice:** M001/S06 — Report fidelity and LLM payloads
**Ledger:** docs/plans/pr255-remediation/ledger.md
**Branch:** pr255-fixes
**Rows:** P1, P2, P3, L1


> **Evidence rule (ledger standard):** evidence is appended per task as it lands and never names a commit SHA; the commits are found with `git log --grep="Slice: M001/S06"`. Earlier wording in this plan that asked for SHAs was removed on 2026-11-11 before execution.

## Task status

- [x] Task 1 — P1: restore the Scoring Methodology / LLM Usage appendix in the Typst PDF
- [x] Task 2 — P2: render architecture diagrams at scale 4 on a 2400×1600 viewport
- [x] Task 3 — P3: disclose the model the arch LLM client resolved from config
- [x] Task 4 — L1: send oversized solution profiles to the market-comparison LLM call
- [ ] Task 5 — Slice gate and evidence

## Definition of Done

Copied verbatim from the ledger slice:

- [ ] The Typst PDF contains the Scoring Methodology appendix, including the LLM usage disclosure, that its body text refers to
- [ ] Architecture diagrams in the PDF render at scale 4 / width 2400
- [ ] The arch report's disclosed model equals the model the LLM client resolved from config
- [ ] An architecture profile over 8 KB still reaches the market-comparison LLM call

## Validation

Tokens from `.jk/validations.yml`, expanded. Run every command from the
worktree root with the project venv active (`source .venv/bin/activate`), so
`python` is `.venv/bin/python`.

1. `format` → `pre-commit run --all-files`
2. `unit` → `python -m pytest -n auto -m "not regression" tests/`
3. `gate` →
   `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`
   (the regression leg needs network on first run; repos are cached under
   `.regression-repos`)

After writing or modifying any `.py` file, run `.venv/bin/ruff format <file>`
on it before committing (CLAUDE.md "Auto-Mode Code Quality").

## Code facts this plan relies on

Verified against `pr255-fixes` at `2a3300b`:

- `render_pdf` in `src/nfr_review/output/pdf.py` takes `llm_info` and
  `score_section_md` but never uses `llm_info`. It builds the Typst source and
  passes it to the module-level `_compile_typst(typst_doc, image_files)`; no
  function returns the source without compiling, so the tests capture it by
  monkeypatching `nfr_review.output.pdf._compile_typst`.
- `_methodology_appendix(llm_info=...)` lives in
  `src/nfr_review/output/markdown.py`; it returns Markdown starting with
  `## Appendix — Scoring Methodology` and contains `### LLM Usage in This
  Report` with the model in backticks. `_md_to_typst` turns the backticks into
  `#raw("<model>")`. The converted appendix was test-compiled with Typst
  successfully while writing this plan.
- On `main`, the weasyprint `_pdf_appendices` emitted the appendix only when
  `score_section_md` was non-empty, titled "Appendix B — Scoring Methodology"
  when a dependency appendix (Appendix A) was present, otherwise "Appendix A
  — …". This plan reproduces that.
- On `main`, `arch_report_render._render_mermaid_to_img` called
  `render_mermaid_to_png(text, path, scale=4, width=2400, height=1600)` for all
  four architecture diagram kinds (C4 diagrams, domain context map, repo
  dependencies, service topology); no call site overrode the defaults. Today
  all four call `pdf._render_mermaid_for_typst(text, image_files, counter)`,
  which calls `render_mermaid_to_png(text, out_path)` with library defaults
  (scale 1, no viewport).
- `arch_orchestrator.run_arch_review` takes no config. `_init_llm_client`
  calls `create_llm_client()` (i.e. `LlmConfig().resolve()`), and
  `_assemble_report` discloses `os.environ.get("NFR_LLM_MODEL",
  "claude-sonnet-4-6")`. `os` is used nowhere else in the module.
- `cli.arch_cmd` has no `--config` option and loads no config; it keeps
  calling `run_arch_review` without `llm_config` (client and disclosure both
  resolve from `LlmConfig()` defaults plus `NFR_LLM_*` env). `cli.all`'s
  `_execute_all_pipelines` has `config_path` and already loads config for the
  NFR half through `run_report_pipeline`; its `_run_arch` closure does not.
- `arch_market_comparison.generate_market_comparison` calls
  `run_analysis(llm, prompt, [{"solution_profile": profile}], max_tokens=2048,
  max_bundle_bytes=8192)`. `serialize_bundle` (ai-tooling) is
  `json.dumps(items, separators=(",", ":"))` and returns `"[]"` once the single
  item exceeds the cap. `run_analysis` is used nowhere else in that module.

---

## Task 1 — P1: restore the Scoring Methodology / LLM Usage appendix

**Rows:** P1
**Files:**
- Modify `src/nfr_review/output/pdf.py` (`render_pdf`)
- Modify `tests/test_pdf.py`

**Consumes:** `_methodology_appendix` (`output/markdown.py`), `_md_to_typst`,
`render_pdf`'s existing `score_section_md`, `deps_section_md`, `llm_info`.
**Produces:** a `== Appendix A|B --- Scoring Methodology` section at the end of
every Typst PDF that has a score section.

### Steps

1. Add `import pytest` to the imports of `tests/test_pdf.py` (after
   `from pathlib import Path`, in its own third-party block, so ruff's isort
   order holds), and append this class at the end of the file:

   ```python
   _SCORE_MD = (
       "## Design Maturity Score\n\nSee **Appendix — Scoring Methodology** for full details.\n"
   )


   def _capture_typst(monkeypatch: pytest.MonkeyPatch) -> list[str]:
       """Replace the Typst compiler with one that records the source."""
       captured: list[str] = []

       def _fake_compile(typst_doc: str, image_files: dict[str, bytes]) -> bytes:
           captured.append(typst_doc)
           return b"%PDF-fake"

       monkeypatch.setattr("nfr_review.output.pdf._compile_typst", _fake_compile)
       return captured


   class TestMethodologyAppendix:
       def test_appendix_with_llm_disclosure(
           self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           """The appendix the score section points at is present, with the model."""
           captured = _capture_typst(monkeypatch)
           render_pdf(
               nfr_result=_make_run_result(),
               output_path=tmp_path / "r.pdf",
               score_section_md=_SCORE_MD,
               llm_info=("anthropic", "claude-test-model-x1"),
           )
           doc = captured[0]
           assert "== Appendix A --- Scoring Methodology" in doc
           assert "=== LLM Usage in This Report" in doc
           assert 'model #raw("claude-test-model-x1")' in doc

       def test_appendix_follows_dependency_appendix(
           self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           """With a dependency appendix (A), methodology is Appendix B; no LLM."""
           captured = _capture_typst(monkeypatch)
           render_pdf(
               nfr_result=_make_run_result(),
               output_path=tmp_path / "r.pdf",
               score_section_md=_SCORE_MD,
               deps_section_md="## Appendix A — Dependency Tree\n\nNo deps.\n",
           )
           doc = captured[0]
           assert "== Appendix A --- Dependency Tree" in doc
           assert "== Appendix B --- Scoring Methodology" in doc
           assert doc.index("== Appendix A --- Dependency Tree") < doc.index(
               "== Appendix B --- Scoring Methodology"
           )
           assert "*without LLM integration*" in doc

       def test_no_appendix_without_score_section(
           self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           """No score section means nothing refers to the appendix; omit it."""
           captured = _capture_typst(monkeypatch)
           render_pdf(
               nfr_result=_make_run_result(),
               output_path=tmp_path / "r.pdf",
               llm_info=("anthropic", "claude-test-model-x1"),
           )
           assert "Scoring Methodology" not in captured[0]

       def test_appendix_compiles(self, tmp_path: Path) -> None:
           """The real Typst compiler accepts the converted appendix."""
           out = tmp_path / "appendix.pdf"
           render_pdf(
               nfr_result=_make_run_result(),
               output_path=out,
               score_section_md=_SCORE_MD,
               llm_info=("anthropic", "claude-test-model-x1"),
           )
           assert out.read_bytes()[:5] == b"%PDF-"
   ```

2. Run and see it fail:

   ```
   .venv/bin/python -m pytest -n auto tests/test_pdf.py -k TestMethodologyAppendix
   ```

   Expected: `test_appendix_with_llm_disclosure` and
   `test_appendix_follows_dependency_appendix` fail with `AssertionError:
   assert '== Appendix A --- Scoring Methodology' in ...` /
   `assert '== Appendix B --- Scoring Methodology' in ...`.
   `test_no_appendix_without_score_section` and `test_appendix_compiles` pass
   (guards).

3. Implement. In `render_pdf` in `src/nfr_review/output/pdf.py`, directly
   after the `if deps_section_md:` block (the one appending
   `"== Appendix A --- Dependency Tree\n\n"`) and before
   `typst_doc = _build_typst_document(sections, title)`, insert:

   ```python
       if score_section_md:
           # The score section tells readers to "See Appendix — Scoring
           # Methodology"; emit it (with the LLM usage disclosure) whenever the
           # score section is present, lettered after the dependency appendix.
           from nfr_review.output.markdown import _methodology_appendix

           appendix_label = "B" if deps_section_md else "A"
           methodology_md = _methodology_appendix(llm_info=llm_info)
           body = methodology_md.split("\n", 1)[1] if "\n" in methodology_md else ""
           sections.append("#pagebreak()\n\n")
           sections.append(f"== Appendix {appendix_label} --- Scoring Methodology\n\n")
           sections.append(_md_to_typst(body, image_files, counter))
   ```

4. Run `.venv/bin/ruff format src/nfr_review/output/pdf.py tests/test_pdf.py`,
   then re-run the step 2 command. Expected: 4 passed.

5. Commit:

   ```
   git add src/nfr_review/output/pdf.py tests/test_pdf.py
   git commit -F - <<'EOF'
   fix(pdf): restore the scoring-methodology appendix in the Typst PDF

   The typst migration dropped the Scoring Methodology / LLM Usage appendix
   although the score section still says "See Appendix — Scoring
   Methodology", and render_pdf ignored llm_info. Emit the appendix again
   when a score section is present, lettered after the dependency appendix
   as before.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S06
   Rows: P1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

6. Check (`format`, `unit` scoped): `.venv/bin/ruff check src/ tests/` is clean
   and `.venv/bin/python -m pytest -n auto tests/test_pdf.py tests/test_pdf_cli.py tests/test_pdf_cascade.py tests/test_pdf_typst_safety.py`
   passes.

---

## Task 2 — P2: architecture diagrams at scale 4, 2400×1600

**Rows:** P2
**Files:**
- Modify `src/nfr_review/output/pdf.py` (`_render_mermaid_for_typst`)
- Modify `src/nfr_review/arch_report_render.py`
- Modify `tests/test_arch_report_render.py`

**Consumes:** `render_mermaid_to_png(mermaid_text, output_path, *, timeout=30,
scale=1, width=None, height=None)` in `src/nfr_review/output/render.py`.
**Produces:** keyword-only `scale`, `width`, `height` parameters on
`_render_mermaid_for_typst` (defaults unchanged: 1 / None / None, so the NFR
PDF is unaffected); `_render_arch_mermaid` helper and three constants in
`arch_report_render.py`, used by all four architecture diagram call sites.

### Steps

1. In `tests/test_arch_report_render.py`, add `import pytest` (third-party
   block, after `from pathlib import Path`), and append at the end of the file:

   ```python
   class TestArchDiagramResolution:
       def test_arch_diagrams_render_at_scale_4_width_2400(
           self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           """Every arch diagram is rendered at the pre-typst resolution."""
           calls: list[dict[str, object]] = []

           def _fake_render(
               mermaid_text: str, output_path: Path, **kwargs: object
           ) -> Path | None:
               calls.append(kwargs)
               return None  # fall through to the SVG/table fallbacks

           monkeypatch.setattr("nfr_review.output.render.render_mermaid_to_png", _fake_render)
           render_arch_pdf(_make_full_report(), tmp_path / "report.pdf")

           # _make_full_report has a C4 diagram and a domain context map.
           assert len(calls) >= 2
           for kwargs in calls:
               assert kwargs.get("scale") == 4
               assert kwargs.get("width") == 2400
               assert kwargs.get("height") == 1600
   ```

2. Run and see it fail:

   ```
   .venv/bin/python -m pytest -n auto tests/test_arch_report_render.py -k TestArchDiagramResolution
   ```

   Expected: `AssertionError: assert None == 4` (the call carries no kwargs).

3. Implement.

   a. In `src/nfr_review/output/pdf.py`, change the signature of
   `_render_mermaid_for_typst` to:

   ```python
   def _render_mermaid_for_typst(
       mermaid_text: str,
       image_files: dict[str, bytes],
       counter: list[int],
       *,
       scale: int = 1,
       width: int | None = None,
       height: int | None = None,
   ) -> str:
   ```

   add to its docstring, after the tier list:

   ```
       *scale*, *width* and *height* are passed to ``render_mermaid_to_png``
       for the tier-1 render (``mmdc -s/-w/-H``).
   ```

   and change the tier-1 call from
   `result = render_mermaid_to_png(mermaid_text, out_path)` to:

   ```python
   result = render_mermaid_to_png(mermaid_text, out_path, scale=scale, width=width, height=height)
   ```

   b. In `src/nfr_review/arch_report_render.py`, directly after
   `_WIDE_DIAGRAM_ASPECT_THRESHOLD = 1.8`, add:

   ```python
   # Architecture diagrams are dense C4/topology graphs: render them on a wide
   # 2400x1600 viewport at 4x, as the pre-typst renderer did, so node labels
   # stay legible when the PDF is zoomed.
   _ARCH_MERMAID_SCALE = 4
   _ARCH_MERMAID_WIDTH = 2400
   _ARCH_MERMAID_HEIGHT = 1600


   def _render_arch_mermaid(
       mermaid_text: str,
       image_files: dict[str, bytes],
       counter: list[int],
   ) -> str:
       """Render an architecture diagram for Typst at high resolution."""
       return _render_mermaid_for_typst(
           mermaid_text,
           image_files,
           counter,
           scale=_ARCH_MERMAID_SCALE,
           width=_ARCH_MERMAID_WIDTH,
           height=_ARCH_MERMAID_HEIGHT,
       )
   ```

   c. In the same file replace the four `_render_mermaid_for_typst(` calls with
   `_render_arch_mermaid(` (same arguments):
   - `_arch_diagrams_typst`: `_render_arch_mermaid(diagram.mermaid, image_files, counter)`
   - `_arch_domain_model_typst`: `_render_arch_mermaid(dm.context_map_mermaid, image_files, counter)`
   - `_arch_repo_dependencies_typst`: `_render_arch_mermaid(mermaid, image_files, counter)`
   - `_arch_dynamic_analysis_typst`: `_render_arch_mermaid(da.topology_mermaid, image_files, counter)`

   After this, `grep -n "_render_mermaid_for_typst(" src/nfr_review/arch_report_render.py`
   shows only the call inside `_render_arch_mermaid`.

4. Run `.venv/bin/ruff format src/nfr_review/output/pdf.py src/nfr_review/arch_report_render.py tests/test_arch_report_render.py`,
   then re-run the step 2 command. Expected: 1 passed.

5. Commit:

   ```
   git add src/nfr_review/output/pdf.py src/nfr_review/arch_report_render.py tests/test_arch_report_render.py
   git commit -F - <<'EOF'
   fix(arch): render architecture diagrams at scale 4 on a 2400x1600 viewport

   The typst migration routed architecture diagrams through
   _render_mermaid_for_typst, which rendered at mmdc defaults and lost the
   scale=4, 2400x1600 render the weasyprint path used. Make scale and
   viewport parameters (defaults unchanged for the NFR report) and pass the
   old values from every architecture diagram call site.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S06
   Rows: P2

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

6. Check (`format`, `unit` scoped): `.venv/bin/ruff check src/ tests/` is clean
   and `.venv/bin/python -m pytest -n auto tests/test_arch_report_render.py tests/test_pdf.py`
   passes.

---

## Task 3 — P3: disclose the model resolved from config

**Rows:** P3
**Files:**
- Modify `src/nfr_review/arch_orchestrator.py`
- Modify `src/nfr_review/cli.py` (`_execute_all_pipelines._run_arch`)
- Modify `tests/test_arch_orchestrator.py`

**Consumes:** `LlmConfig` and `LlmConfig.resolve()` (`src/nfr_review/config.py`),
`create_llm_client(config)` (`src/nfr_review/llm_integration.py`),
`cli._load_effective_config(config_path, *, quiet)`.
**Produces:** `run_arch_review(..., llm_config: LlmConfig | None = None)`;
`_init_llm_client(skip_llm, cb, llm_config=None)` returning
`(client | None, model | None)`; `_assemble_report(..., llm_model=...)`.
`nfr-review all` passes the loaded config's `llm` block. `nfr-review arch` is
unchanged (it has no config option; its client and disclosure both resolve
from `LlmConfig()` plus `NFR_LLM_*`).

### Steps

1. In `tests/test_arch_orchestrator.py`, extend the imports to:

   ```python
   import click
   import pytest
   from click.testing import CliRunner

   from nfr_review.arch_models import ArchReport
   from nfr_review.arch_orchestrator import run_arch_review
   from nfr_review.cli import _execute_all_pipelines, cli
   from nfr_review.config import LlmConfig
   from nfr_review.llm_integration import ProviderUnavailableError
   ```

   and append at the end of the file:

   ```python
   class _OfflineClient:
       """An available LLM client whose calls fail, so analysis falls back."""

       available = True

       def call(self, prompt: str, *, max_tokens: int = 1024) -> str:
           raise ProviderUnavailableError("offline test client")


   class TestArchLlmModelDisclosure:
       @pytest.fixture()
       def created_with(self, monkeypatch: pytest.MonkeyPatch) -> list[LlmConfig | None]:
           """Clear NFR_LLM_* and record the config each client is created with."""
           for var in (
               "NFR_LLM_MODEL",
               "NFR_LLM_PROVIDER",
               "NFR_LLM_BACKEND",
               "NFR_LLM_BASE_URL",
           ):
               monkeypatch.delenv(var, raising=False)
           seen: list[LlmConfig | None] = []

           def _fake_create(config: LlmConfig | None = None) -> _OfflineClient:
               seen.append(config)
               return _OfflineClient()

           monkeypatch.setattr("nfr_review.llm_integration.create_llm_client", _fake_create)
           return seen

       def test_model_from_config_only(
           self, sample_repo: Path, created_with: list[LlmConfig | None]
       ) -> None:
           report = run_arch_review(
               [sample_repo], llm_config=LlmConfig(model="config-only-model")
           )
           assert report.metadata.llm_available is True
           assert report.metadata.llm_model == "config-only-model"
           assert created_with[0] is not None
           assert created_with[0].model == "config-only-model"

       def test_env_override_is_disclosed(
           self,
           sample_repo: Path,
           created_with: list[LlmConfig | None],
           monkeypatch: pytest.MonkeyPatch,
       ) -> None:
           monkeypatch.setenv("NFR_LLM_MODEL", "env-model")
           report = run_arch_review([sample_repo], llm_config=LlmConfig(model="config-model"))
           assert report.metadata.llm_model == "env-model"

       def test_default_model_without_config(
           self, sample_repo: Path, created_with: list[LlmConfig | None]
       ) -> None:
           report = run_arch_review([sample_repo])
           assert report.metadata.llm_model == LlmConfig().model

       def test_all_pipeline_passes_config_llm(
           self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           cfg = tmp_path / "nfr-review.yaml"
           cfg.write_text("llm:\n  model: cfg-file-model\n", encoding="utf-8")
           seen: dict[str, object] = {}

           def _fake_run_arch_review(targets: list[Path], **kwargs: object) -> ArchReport:
               seen.update(kwargs)
               raise RuntimeError("stop after capturing the arguments")

           monkeypatch.setattr(
               "nfr_review.arch_orchestrator.run_arch_review", _fake_run_arch_review
           )
           with pytest.raises(click.exceptions.Exit):
               _execute_all_pipelines(
                   target_list=[tmp_path],
                   repo_names=["repo"],
                   timestamp="20260101T000000",
                   output_dir=tmp_path / "out",
                   config_path=cfg,
                   no_arch=False,
                   no_tests=True,
                   no_deps=True,
                   no_diagrams=True,
                   no_pdf=True,
                   no_summary=True,
                   test_timeout=1,
                   no_score=True,
                   max_resolve_rounds=None,
                   no_llm=False,
                   diagram_mode="hierarchical",
                   exclude_tests=False,
                   workers=1,
                   quiet=True,
               )
           llm_config = seen["llm_config"]
           assert isinstance(llm_config, LlmConfig)
           assert llm_config.model == "cfg-file-model"
   ```

2. Run and see it fail:

   ```
   .venv/bin/python -m pytest -n auto tests/test_arch_orchestrator.py -k TestArchLlmModelDisclosure
   ```

   Expected: `test_model_from_config_only` and `test_env_override_is_disclosed`
   fail with `TypeError: run_arch_review() got an unexpected keyword argument
   'llm_config'`; `test_all_pipeline_passes_config_llm` fails with
   `KeyError: 'llm_config'`; `test_default_model_without_config` passes (guard).

3. Implement.

   a. `src/nfr_review/arch_orchestrator.py`:
   - Delete `import os` (its only use is the line being replaced).
   - Add `from nfr_review.config import LlmConfig` after
     `from nfr_review.arch_models import (...)`.
   - Replace `_init_llm_client` with:

     ```python
     def _init_llm_client(  # type: ignore[return]
         skip_llm: bool,
         cb: ProgressCallback,
         llm_config: LlmConfig | None = None,
     ):
         """Initialise an LLM client from *llm_config*.

         Returns ``(client, model)``, where *model* is the model the client was
         created with (config plus ``NFR_LLM_*`` overrides), or ``(None, None)``
         when LLM use is skipped or no backend is available.
         """
         if skip_llm:
             return None, None
         from nfr_review.llm_integration import create_llm_client

         resolved = (llm_config if llm_config is not None else LlmConfig()).resolve()
         client = create_llm_client(resolved)
         if client.available:
             cb("LLM available — domain model and market analysis enabled")
             return client, resolved.model
         cb("LLM not available — skipping LLM-dependent analysis")
         return None, None
     ```

   - In `_assemble_report`, add the keyword parameter `llm_model: str | None,`
     directly after `llm,`, and replace the three-line
     `llm_model=os.environ.get("NFR_LLM_MODEL", "claude-sonnet-4-6") if llm is not None else None,`
     expression with `llm_model=llm_model,`.
   - In `run_arch_review`, add the parameter `llm_config: LlmConfig | None = None,`
     after `progress: ProgressCallback | None = None,`; add to its docstring:

     ```
         llm_config:
             LLM configuration (normally ``Config.llm``). ``NFR_LLM_*``
             overrides apply on top; defaults to ``LlmConfig()``.
     ```

     replace `llm = _init_llm_client(skip_llm, cb)` with
     `llm, llm_model = _init_llm_client(skip_llm, cb, llm_config)`, and add
     `llm_model=llm_model,` after `llm=llm,` in the `_assemble_report(...)` call.

   b. `src/nfr_review/cli.py`, in `_execute_all_pipelines`'s nested `_run_arch`,
   insert as its first statement after the two imports:

   ```python
           # Same config the NFR half loads, so the arch LLM client and its
           # disclosed model follow the configured llm block.
           llm_config = _load_effective_config(config_path, quiet=True).llm
   ```

   and add `llm_config=llm_config,` to its `run_arch_review(...)` call (after
   `diagram_mode=diagram_mode,`).

4. Run `.venv/bin/ruff format src/nfr_review/arch_orchestrator.py src/nfr_review/cli.py tests/test_arch_orchestrator.py`,
   then re-run the step 2 command. Expected: 4 passed. Then
   `.venv/bin/python -m pytest -n auto tests/test_arch_orchestrator.py tests/test_arch_drum_validation.py`
   passes (existing `skip_llm=True` callers unaffected).

5. Commit:

   ```
   git add src/nfr_review/arch_orchestrator.py src/nfr_review/cli.py tests/test_arch_orchestrator.py
   git commit -F - <<'EOF'
   fix(arch): disclose the LLM model resolved from config

   The arch report disclosed NFR_LLM_MODEL or a hard-coded default, and its
   client ignored the config's llm block. run_arch_review now takes the
   LlmConfig, creates the client from its resolved form and discloses that
   model; `nfr-review all` passes the loaded config's llm block.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S06
   Rows: P3

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

6. Check (`format`, `unit` scoped): `.venv/bin/ruff check src/ tests/` is clean
   and `pre-commit run mypy --all-files` passes (the return shape of
   `_init_llm_client` changed).

---

## Task 4 — L1: oversized profiles reach the market-comparison call

**Rows:** L1
**Files:**
- Modify `src/nfr_review/arch_market_comparison.py` (`generate_market_comparison`, imports)
- Modify `tests/test_arch_market_comparison.py`

**Consumes:** `LlmClient.call(prompt, *, max_tokens)`, the existing
`ProviderUnavailableError` / `Exception` handlers.
**Produces:** `generate_market_comparison` sends
`prompt + "\n\n" + json.dumps([{"solution_profile": profile}], separators=(",", ":"))`
directly — byte-identical to the old bundle for profiles under 8 KB, and no
longer replaced by `"[]"` above it (same fix as `f307a2a` for the summary).

### Steps

1. In `tests/test_arch_market_comparison.py`, add to `class TestGenerateMarketComparison`
   (after `test_max_comparisons_in_prompt`):

   ```python
       def test_oversized_profile_reaches_llm(self) -> None:
           """A profile over 8 KB is sent whole, not dropped to "[]"."""
           llm = _make_llm_mock(response=_make_valid_llm_response(1))
           profile = {
               "architecture_style": "microservices",
               "domain_hints": [f"domain-hint-{i:04d}" for i in range(600)],
           }
           assert len(json.dumps(profile).encode()) > 8192

           generate_market_comparison(profile, llm)

           sent = llm.call.call_args[0][0]
           assert not sent.rstrip().endswith("[]")
           assert '"architecture_style":"microservices"' in sent
           assert "domain-hint-0599" in sent
           assert llm.call.call_args.kwargs["max_tokens"] == 2048
   ```

2. Run and see it fail:

   ```
   .venv/bin/python -m pytest -n auto tests/test_arch_market_comparison.py -k test_oversized_profile_reaches_llm
   ```

   Expected: `AssertionError: assert not True` on the `endswith("[]")` line
   (the bundle was truncated to `[]`).

3. Implement in `src/nfr_review/arch_market_comparison.py`:
   - Remove `run_analysis,` from the `from nfr_review.llm_integration import (...)`
     block (leaving `LlmClient` and `ProviderUnavailableError`).
   - In `generate_market_comparison`, replace
     `evidence_items = [{"solution_profile": profile}]` with:

     ```python
         # Send the profile whole. It is already a bounded summary (counts and
         # name lists), and must not go through run_analysis: its byte-capped
         # bundle drops whole items, so this single-item payload became "[]"
         # once it exceeded 8 KB and the LLM compared nothing.
         payload = json.dumps([{"solution_profile": profile}], separators=(",", ":"))
     ```

     and replace the `raw_response = run_analysis(llm, prompt, evidence_items, max_tokens=2048, max_bundle_bytes=8192)`
     call inside the `try:` with:

     ```python
             raw_response = llm.call(prompt + "\n\n" + payload, max_tokens=2048)
     ```

     Keep both `except` clauses unchanged.

4. Run `.venv/bin/ruff format src/nfr_review/arch_market_comparison.py tests/test_arch_market_comparison.py`,
   then `.venv/bin/python -m pytest -n auto tests/test_arch_market_comparison.py`.
   Expected: all pass, including the new case and the existing
   `test_max_comparisons_in_prompt`, `test_llm_unavailable_error`,
   `test_llm_unexpected_error`.

5. Commit:

   ```
   git add src/nfr_review/arch_market_comparison.py tests/test_arch_market_comparison.py
   git commit -F - <<'EOF'
   fix(arch): send the full solution profile to the market-comparison LLM

   run_analysis caps the bundle at 8 KB by dropping whole items; the profile
   is a single item, so an oversized profile was sent as "[]". Call the
   client directly with the same JSON payload, as f307a2a did for the
   executive summary, and add a >8 KB regression test.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S06
   Rows: L1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

6. Check (`format`, `unit` scoped): `.venv/bin/ruff check src/ tests/` is clean.

---

## Task 5 — Slice gate and evidence

**Rows:** P1, P2, P3, L1
**Files:** create `docs/plans/pr255-remediation/evidence/M001-S06.md`
**Consumes:** the four commits above.
**Produces:** the slice's evidence record.

### Steps

1. `format`: `pre-commit run --all-files` — expect every hook to pass. If a
   hook rewrites a file, re-stage it and amend it into the commit that
   introduced the change, then re-run until clean.
2. `unit`: `python -m pytest -n auto -m "not regression" tests/` — expect 0 failed.
3. `gate`: `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`
   — expect all three legs to pass. No snapshot refresh is expected: the
   regression snapshots are rule/collector JSONL and DSL, and this slice
   changes only PDF rendering, arch LLM wiring and the market LLM payload.
4. Write `docs/plans/pr255-remediation/evidence/M001-S06.md` in the layout of
   `evidence/M001-S01.md`: heading `# Evidence — M001/S06`, section
   `## M001/S06 — Report fidelity and LLM payloads`, one bullet per row
   (P1, P2, P3, L1) naming the test that locks it, then the observed
   `format` / `unit` / `gate` results (pass/fail counts copied from the output)
   and the date. Record only identifiers that appear in that command output.
5. Commit:

   ```
   git add docs/plans/pr255-remediation/evidence/M001-S06.md
   git commit -F - <<'EOF'
   docs(plans): record M001/S06 evidence

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S06
   Rows: P1, P2, P3, L1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

6. Check (`gate`): the step 3 run is green on the head commit.

---

## Self-review

- **DoD coverage:** DoD 1 → Task 1 (`test_appendix_with_llm_disclosure`,
  `test_appendix_follows_dependency_appendix`, `test_appendix_compiles`);
  DoD 2 → Task 2 (`test_arch_diagrams_render_at_scale_4_width_2400`);
  DoD 3 → Task 3 (`test_model_from_config_only`, `test_env_override_is_disclosed`,
  `test_all_pipeline_passes_config_llm`); DoD 4 → Task 4
  (`test_oversized_profile_reaches_llm`).
- **Row coverage:** P1 → Task 1, P2 → Task 2, P3 → Task 3, L1 → Task 4; all
  four in Task 5's evidence.
- **Placeholder scan:** no TBD/TODO; every code block is complete. Commit SHAs
  are not written in this plan; Task 5 copies them from `git log` output.
- **Name consistency:** `_render_mermaid_for_typst(…, *, scale, width, height)`,
  `_render_arch_mermaid`, `_ARCH_MERMAID_SCALE/WIDTH/HEIGHT`,
  `_init_llm_client(skip_llm, cb, llm_config)`, `_assemble_report(…, llm_model=…)`,
  `run_arch_review(…, llm_config=…)`, `_load_effective_config`,
  `_methodology_appendix`, `_md_to_typst`, `_compile_typst`, `_make_full_report`,
  `_make_run_result`, `_make_llm_mock`, `_make_valid_llm_response` all exist in
  the tree or are defined by the task that first uses them.
