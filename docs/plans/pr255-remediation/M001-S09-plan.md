# M001/S09 plan — Real LLM isolation in tests

**Slice:** M001/S09 — ledger `docs/plans/pr255-remediation/ledger.md`

**Task status**

- [ ] Task 1 — T2: an autouse `offline_llm` fixture patches `create_llm_client` at every lookup site and the LLM rules' import-time clients
- [ ] Task 2 — T2: remove the `_AI_TOOLING_AVAILABLE` patches; make the unavailable-client tests deterministic
- [ ] Task 3 — Slice gate and evidence

**Definition of Done**

- [ ] No test patches `_AI_TOOLING_AVAILABLE`; tests needing a fake or absent LLM patch `create_llm_client`
- [ ] The suite passes with `ANTHROPIC_API_KEY` set in the environment

**Validation**

Run from the worktree root with the venv active (`source .venv/bin/activate`, so
`python` is `.venv/bin/python`):

- `format` → `pre-commit run --all-files`
- `unit` → `python -m pytest -n auto -m "not regression" tests/`
- `gate` → `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`


> **Evidence rule (ledger standard):** evidence is appended per task as it lands and never names a commit SHA; the commits are found with `git log --grep="Slice: M001/S09"`. Earlier wording in this plan that asked for SHAs was removed on 2026-11-11 before execution.

## Context the executor needs

- `src/nfr_review/llm_integration.py` sets `_AI_TOOLING_AVAILABLE` in its
  `try: from ai_tooling … except ImportError:` block, and nothing reads it, so
  `monkeypatch.setattr(…, "_AI_TOOLING_AVAILABLE", …)` changes nothing. With
  ai-tooling installed (it is in this venv) `create_llm_client()` returns
  `ai_tooling.providers.AnthropicProvider`, whose `available` is `True`
  whenever `ANTHROPIC_API_KEY` is set. `_UnavailableClient` exists only in the
  `except ImportError` branch.
- `create_llm_client` is looked up in two ways:
  - bound at import (module level `from nfr_review.llm_integration import (…, create_llm_client, …)`)
    in `nfr_review.collectors.adr_derive`, `nfr_review.output.summarize`,
    `nfr_review.rules.adr_drift`, `nfr_review.rules.pii_logging`;
  - imported inside a function at call time in `nfr_review.cli`
    (`_resolve_llm_info`, `_warn_llm_cost`) and
    `nfr_review.arch_orchestrator`, which read the attribute on
    `nfr_review.llm_integration` when called.
- The rules `ArchitecturalDriftFromAdrRule` (`architectural-drift-from-adr`)
  and `PiiInLogStatementsRule` (`pii-in-log-statements`) are registered by
  `@register` as singletons whose `__init__` runs
  `self._llm = … create_llm_client()` at import, i.e. during test collection.
  Patching `create_llm_client` later does not reach those instances; their
  `_llm` must be replaced too.
- `_load_dotenv_once()` copies the checkout's `.env` into `os.environ` on the
  first `create_llm_client()` call (that is, at rule import). The owner's main
  checkout has a `.env`; once this branch lands there, the suite would pick up
  whatever key it holds.
- Measured on 2026-11-10 at the head of `pr255-fixes`, with
  `ANTHROPIC_API_KEY=dummy` and a tripwire on the providers' `_call_backend`
  (step 2 of Task 1): 91 real LLM calls from 65 tests in 21 files, from
  `collectors/adr_derive.py:collect` (67), `output/summarize.py:generate_executive_summary`
  (9), `rules/adr_drift.py:_analyze_with_llm` (8) and
  `rules/pii_logging.py:_try_llm_confirmation` (7). They pass today only
  because a 401 is swallowed as "LLM unavailable". These are T2 findings and
  this slice fixes them all; the only outright failure is
  `tests/test_llm_client.py::TestCreateLlmClientStub::test_returns_unavailable_client_when_no_ai_tooling`.
- `tests/test_pilot_validation.py` runs only where
  `/Users/jim/dev/agentic-java-demo` exists (it does on the owner's machine).
- `tests/` is a package (`tests/__init__.py`), so a test can
  `from tests.conftest import …`; `tests/test_pdf_typst_safety.py` already
  imports from `tests.…`.
- `tests/fixtures/*/graphify-out/` directories (gitignored) appear during the
  test run because graphify writes into the scanned fixture repos (row GR1,
  fixed by M001/S04). In a checkout whose path contains digit runs, the
  `graphify-out/cache/stat-index.json` this leaves in
  `tests/fixtures/hygiene-clean-repo` can trip the privacy rule and fail
  `tests/test_hygiene_integration.py::TestPythonCleanRepoRegression` and
  `tests/test_hygiene_integration_s05.py::TestCleanRepoE2E`. That is not an
  S09 regression; if it happens, `rm -rf tests/fixtures/*/graphify-out` and
  rerun, and note it in the evidence.
- Known pre-existing issue that affects `gate`: on 2026-11-10 the `httpx`
  and `gin` regression snapshots fail with new `dep-freshness` findings ("no
  release in N months"), with or without `ANTHROPIC_API_KEY`. Do not refresh
  snapshots in this slice; record it and stop for the owner.
- After editing any `.py` file run `ruff format <file>` before committing
  (project CLAUDE.md).

## Task 1 — T2: an autouse `offline_llm` fixture patches `create_llm_client` at every lookup site and the LLM rules' import-time clients

**Rows:** T2
**Files:** `tests/test_llm_isolation.py` (create), `tests/conftest.py` (modify),
`tests/test_llm_config.py` (modify: opt out), `pyproject.toml` (modify: register the `real_llm_factory` marker)
**Consumes:** `nfr_review.llm_integration.ProviderUnavailableError`, `nfr_review.registry.rule_registry` (`.all()`), the lookup sites listed above.
**Produces:** in `tests/conftest.py`: `CREATE_LLM_CLIENT_SITES`, `OfflineLlmClient`, `_offline_create_llm_client`, the autouse fixture `offline_llm`; the `real_llm_factory` marker; `_ENV_LOADED = True` set at conftest import.

Steps:

1. Write the failing test. Create `tests/test_llm_isolation.py`:

   ```python
   """T2: the test suite never reaches a real LLM, whatever the environment holds.

   The autouse ``offline_llm`` fixture in ``tests/conftest.py`` patches
   ``create_llm_client`` everywhere it is looked up and the clients that the
   registered LLM rules built at import time. These tests set a dummy
   ``ANTHROPIC_API_KEY`` themselves, so they fail if that isolation is lost
   even on a machine where the key is unset.
   """

   from __future__ import annotations

   import importlib
   import re
   from pathlib import Path

   import pytest

   import nfr_review
   from nfr_review.registry import rule_registry
   from tests.conftest import CREATE_LLM_CLIENT_SITES

   _MODULE_LEVEL_IMPORT = re.compile(
       r"^from nfr_review\.llm_integration import (\([^)]*\)|[^\n]*)", re.MULTILINE
   )


   @pytest.mark.parametrize("module_name", CREATE_LLM_CLIENT_SITES)
   def test_create_llm_client_is_offline_at_every_lookup_site(
       module_name: str, monkeypatch: pytest.MonkeyPatch
   ) -> None:
       monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
       client = importlib.import_module(module_name).create_llm_client()
       assert client.available is False


   def test_registered_rules_hold_offline_clients() -> None:
       llm_rules = [rule for rule in rule_registry.all() if hasattr(rule, "_llm")]
       assert {rule.id for rule in llm_rules} >= {
           "architectural-drift-from-adr",
           "pii-in-log-statements",
       }
       for rule in llm_rules:
           assert rule._llm.available is False, rule.id


   def test_sites_cover_every_module_level_import() -> None:
       """A module that binds create_llm_client at import keeps the real function
       unless it is patched by name, so each one must be listed."""
       src_root = Path(nfr_review.__file__).parent
       importers: set[str] = set()
       for path in src_root.rglob("*.py"):
           for match in _MODULE_LEVEL_IMPORT.finditer(path.read_text(encoding="utf-8")):
               if re.search(r"\bcreate_llm_client\b", match.group(1)):
                   importers.add(
                       ".".join(path.relative_to(src_root.parent).with_suffix("").parts)
                   )
       assert "nfr_review.output.summarize" in importers  # the scan works
       assert importers <= set(CREATE_LLM_CLIENT_SITES)
   ```

2. Run and see it fail, and measure the real calls it is guarding against.

   a. `ANTHROPIC_API_KEY=dummy .venv/bin/python -m pytest -n0 tests/test_llm_isolation.py`
   Expected: collection error, `ImportError: cannot import name
   'CREATE_LLM_CLIENT_SITES' from 'tests.conftest'`.

   b. Create the throwaway tripwire plugin (not committed)
   `/tmp/llm_tripwire/llm_tripwire.py`:

   ```python
   import os
   import traceback

   from ai_tooling import providers

   _LOG = os.environ["LLM_TRIPWIRE_LOG"]


   def _make(cls):
       def _call_backend(self, prompt, max_tokens):
           frames = [f for f in traceback.extract_stack() if "/nfr_review/" in f.filename]
           origin = " <- ".join(
               f"{f.filename.split('/nfr_review/')[1]}:{f.name}" for f in reversed(frames[-3:])
           )
           with open(_LOG, "a", encoding="utf-8") as fh:
               fh.write(f"{cls.__name__}\t{os.environ.get('PYTEST_CURRENT_TEST')}\t{origin}\n")
           raise providers.ProviderUnavailableError("tripwire: real LLM call in tests")

       return _call_backend


   for _cls in (
       providers.AnthropicProvider,
       providers.OpenAICompatibleProvider,
       providers.ClaudeCliProvider,
   ):
       _cls._call_backend = _make(_cls)
   ```

   and run the suite (minus the new file, which cannot be collected yet) with it:

   ```sh
   rm -f /tmp/llm_tripwire/hits.log
   ANTHROPIC_API_KEY=dummy LLM_TRIPWIRE_LOG=/tmp/llm_tripwire/hits.log PYTHONPATH=/tmp/llm_tripwire \
     .venv/bin/python -m pytest -p llm_tripwire -m "not regression" tests/ \
     --ignore=tests/test_llm_isolation.py -q
   cut -f3 /tmp/llm_tripwire/hits.log | sort | uniq -c | sort -rn
   ```

   Expected: `1 failed` (`test_returns_unavailable_client_when_no_ai_tooling`)
   and a non-empty `hits.log` — about 91 lines from the four origins listed
   in the context section. Save the `uniq -c` output for the evidence.

3. Implement.

   a. `tests/conftest.py`: replace the opening

   ```python
   import logging

   import pytest
   ```

   with

   ```python
   import importlib
   import logging

   import pytest

   import nfr_review.llm_integration as _llm_integration
   from nfr_review.llm_integration import ProviderUnavailableError

   # Never read the checkout's .env: it may hold a real API key, and the first
   # create_llm_client() call (made at import time by the LLM rules) would copy
   # it into os.environ for the rest of the session.
   _llm_integration._ENV_LOADED = True

   # Every module that binds ``create_llm_client`` at import time, plus
   # ``nfr_review.llm_integration`` itself for the call-time imports in cli.py and
   # arch_orchestrator.py. tests/test_llm_isolation.py fails if one is missing.
   CREATE_LLM_CLIENT_SITES = (
       "nfr_review.llm_integration",
       "nfr_review.collectors.adr_derive",
       "nfr_review.output.summarize",
       "nfr_review.rules.adr_drift",
       "nfr_review.rules.pii_logging",
   )
   ```

   and append at the end of the file:

   ```python
   class OfflineLlmClient:
       """Stand-in for an unconfigured LLM: reports unavailable and refuses calls."""

       available = False

       def call(self, prompt: str, *, max_tokens: int = 1024) -> str:
           raise ProviderUnavailableError("LLM calls are disabled in tests (tests/conftest.py)")


   def _offline_create_llm_client(config: object = None) -> OfflineLlmClient:
       return OfflineLlmClient()


   @pytest.fixture(autouse=True)
   def offline_llm(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
       """Keep every test off real LLM backends, whatever the environment holds.

       Patches ``create_llm_client`` where it is looked up, and the clients the
       registered LLM rules created at import. Tests that exercise the real
       factory opt out with ``@pytest.mark.real_llm_factory``; tests that need a
       fake with behaviour patch ``create_llm_client`` (or pass ``llm_client=``)
       themselves, which overrides this.
       """
       if request.node.get_closest_marker("real_llm_factory"):
           return
       from nfr_review.registry import rule_registry

       for module_name in CREATE_LLM_CLIENT_SITES:
           monkeypatch.setattr(
               importlib.import_module(module_name),
               "create_llm_client",
               _offline_create_llm_client,
           )
       for rule in rule_registry.all():
           if hasattr(rule, "_llm"):
               monkeypatch.setattr(rule, "_llm", OfflineLlmClient())
   ```

   Tests that already patch `create_llm_client` themselves (for example
   `tests/test_summarize.py` with
   `patch("nfr_review.output.summarize.create_llm_client", …)` and
   `tests/test_adr_derive_collector.py`) keep working: their patch is applied
   after the autouse fixture and wins.

   b. `tests/test_llm_config.py` calls the real factory through
   `_llm_mod.create_llm_client(...)` to check the `ProviderConfig` mapping (it
   never calls the returned client). Opt the module out: replace

   ```python
   _NFR_ENV = (
   ```

   with

   ```python
   # These tests exercise the real factory's config mapping; none of them calls
   # the client it returns.
   pytestmark = pytest.mark.real_llm_factory

   _NFR_ENV = (
   ```

   c. `pyproject.toml`, `[tool.pytest.ini_options].markers`: replace

   ```toml
       "loadtest: sustained-traffic load tests for the monitor (longer running)",
   ]
   ```

   with

   ```toml
       "loadtest: sustained-traffic load tests for the monitor (longer running)",
       "real_llm_factory: run with the real create_llm_client instead of the offline stub from tests/conftest.py",
   ]
   ```

4. Run and pass:
   `ANTHROPIC_API_KEY=dummy .venv/bin/python -m pytest -n0 tests/test_llm_isolation.py tests/test_llm_config.py tests/test_summarize.py tests/test_adr_derive_collector.py tests/test_adr_drift_rule.py tests/test_pii_logging_rule.py tests/test_s04_integration.py`
   Expected: all pass. Then rerun the tripwire over all of `tests/` (the
   step 2b command without the `--ignore`):

   ```sh
   rm -f /tmp/llm_tripwire/hits.log
   ANTHROPIC_API_KEY=dummy LLM_TRIPWIRE_LOG=/tmp/llm_tripwire/hits.log PYTHONPATH=/tmp/llm_tripwire \
     .venv/bin/python -m pytest -p llm_tripwire -m "not regression" tests/ -q
   test ! -s /tmp/llm_tripwire/hits.log && echo "no real LLM calls"
   ```

   Expected: `no real LLM calls`, and the only failure is
   `test_returns_unavailable_client_when_no_ai_tooling` (Task 2 fixes it; it
   binds the real `create_llm_client` at import and constructs a real
   provider without calling it).

5. Check (`format`): `ruff format tests/conftest.py tests/test_llm_isolation.py tests/test_llm_config.py`,
   then `pre-commit run --all-files` passes.

6. Commit:

   ```sh
   git add tests/conftest.py tests/test_llm_isolation.py tests/test_llm_config.py pyproject.toml
   git commit -F - <<'EOF'
   test: keep the suite off real LLM backends

   With ANTHROPIC_API_KEY set, 65 tests made real LLM calls (adr-derive,
   executive summary, adr-drift, pii-logging) and passed only because the
   401 was swallowed. An autouse offline_llm fixture now patches
   create_llm_client at every module that looks it up and replaces the
   clients the LLM rule singletons built at import; tests of the real
   factory opt out with the real_llm_factory marker. conftest also stops
   the checkout's .env from being loaded into the test process.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S09
   Rows: T2

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

## Task 2 — T2: remove the `_AI_TOOLING_AVAILABLE` patches; make the unavailable-client tests deterministic

**Rows:** T2
**Files:** `tests/test_llm_client.py` (modify `TestCreateLlmClientStub` and imports),
`tests/test_baseline.py` (modify `TestCLIBaseline.test_baseline_filters_known_findings_exit_0`),
`tests/test_pilot_validation.py` (modify `test_pilot_band2_graceful_degradation`)
**Consumes:** the `offline_llm` fixture from Task 1; `nfr_review.llm_integration.__file__`.
**Produces:** `_load_llm_integration_without_ai_tooling(monkeypatch)` in `tests/test_llm_client.py`; no `_AI_TOOLING_AVAILABLE` reference under `tests/`.

Steps:

1. The failing test already exists. Confirm the T2 failure:
   `ANTHROPIC_API_KEY=dummy .venv/bin/python -m pytest -n0 "tests/test_llm_client.py::TestCreateLlmClientStub"`
   Expected: `test_returns_unavailable_client_when_no_ai_tooling` fails with
   `assert True is False` (`create_llm_client()` returned a real
   `AnthropicProvider`, available because the key is set), and
   `test_stub_call_raises_provider_unavailable` is skipped ("ai-tooling is
   installed; stub path not active") — it never runs in this venv.
   Also `grep -rn _AI_TOOLING_AVAILABLE tests/` lists three hits:
   `tests/test_baseline.py`, `tests/test_llm_client.py`,
   `tests/test_pilot_validation.py`.

2. Rewrite the stub tests so they build the no-ai-tooling module
   deterministically. In `tests/test_llm_client.py`:

   a. Replace the imports

   ```python
   import json
   from unittest.mock import MagicMock

   import pytest

   from nfr_review.llm_integration import (
       ProviderUnavailableError,
       create_llm_client,
       extract_json,
       run_analysis,
       serialize_bundle,
   )
   ```

   with

   ```python
   import importlib.util
   import json
   import sys
   from types import ModuleType
   from unittest.mock import MagicMock

   import pytest

   from nfr_review.llm_integration import (
       extract_json,
       run_analysis,
       serialize_bundle,
   )
   ```

   b. Replace the whole `class TestCreateLlmClientStub:` (from
   `class TestCreateLlmClientStub:` down to, not including, the
   `# ---…` banner that precedes `# extract_json`) with:

   ```python
   def _load_llm_integration_without_ai_tooling(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
       """Execute a private copy of ``nfr_review.llm_integration`` with ai-tooling unimportable.

       The copy is never registered in ``sys.modules``, so the real module, and the
       classes other tests hold, are untouched. The result does not depend on
       whether ai-tooling is installed or on ``ANTHROPIC_API_KEY``.
       """
       import nfr_review.llm_integration as real

       loaded = [n for n in sys.modules if n == "ai_tooling" or n.startswith("ai_tooling.")]
       for name in {"ai_tooling", *loaded}:
           monkeypatch.setitem(sys.modules, name, None)
       spec = importlib.util.spec_from_file_location(
           "_llm_integration_without_ai_tooling", real.__file__
       )
       assert spec is not None and spec.loader is not None
       module = importlib.util.module_from_spec(spec)
       spec.loader.exec_module(module)
       return module


   class TestCreateLlmClientStub:
       """When ai-tooling is not installed the stub must be importable and inert,
       even with an API key in the environment."""

       def test_returns_unavailable_client_when_no_ai_tooling(
           self, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
           stub = _load_llm_integration_without_ai_tooling(monkeypatch)
           assert stub.create_llm_client().available is False

       def test_stub_call_raises_provider_unavailable(
           self, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           stub = _load_llm_integration_without_ai_tooling(monkeypatch)
           with pytest.raises(stub.ProviderUnavailableError, match="ai-tooling is not installed"):
               stub.create_llm_client().call("hello")
   ```

   Every `ai_tooling*` entry in `sys.modules` is set to `None`, not just
   `ai_tooling`: a cached `ai_tooling.config` would otherwise satisfy
   `from ai_tooling.config import ProviderConfig` and the copy would take the
   ai-tooling branch.

3. Remove the no-op flag patches.

   a. `tests/test_baseline.py`, in `class TestCLIBaseline`, replace

   ```python
   def test_baseline_filters_known_findings_exit_0(
       self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
   ) -> None:
       """When all findings match the baseline, exit 0 (no regressions)."""
       # Suppress LLM-powered rules (adr-gap etc.) which are non-deterministic
       monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
       monkeypatch.setenv("NFR_LLM_BACKEND", "api")
       import nfr_review.llm_integration as _lc

       monkeypatch.setattr(_lc, "_AI_TOOLING_AVAILABLE", True)
   ```

   with

   ```python
       @pytest.mark.usefixtures("offline_llm")
       def test_baseline_filters_known_findings_exit_0(self, tmp_path: Path) -> None:
           """When all findings match the baseline, exit 0 (no regressions).

           LLM-powered rules and collectors are non-deterministic; ``offline_llm``
           (tests/conftest.py) patches ``create_llm_client`` so they skip.
           """
   ```

   b. `tests/test_pilot_validation.py`, replace

   ```python
   @_skip_unless_pilot
   def test_pilot_band2_graceful_degradation(
       tmp_path: Path, monkeypatch: pytest.MonkeyPatch
   ) -> None:
       monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
       monkeypatch.setenv("NFR_LLM_BACKEND", "api")
       import nfr_review.llm_integration as _lc

       monkeypatch.setattr(_lc, "_AI_TOOLING_AVAILABLE", True)
   ```

   with

   ```python
   @_skip_unless_pilot
   @pytest.mark.usefixtures("offline_llm")
   def test_pilot_band2_graceful_degradation(tmp_path: Path) -> None:
       """Band 2 rules are accounted for when no LLM is available (``offline_llm``
       in tests/conftest.py patches ``create_llm_client``)."""
   ```

   (`offline_llm` is autouse; naming it states the dependency explicitly.)

4. Run and pass:
   `ANTHROPIC_API_KEY=dummy .venv/bin/python -m pytest -n0 tests/test_llm_client.py tests/test_baseline.py tests/test_pilot_validation.py tests/test_llm_isolation.py`
   Expected: all pass; neither `TestCreateLlmClientStub` case is skipped.
   Then `env -u ANTHROPIC_API_KEY .venv/bin/python -m pytest -n0 tests/test_llm_client.py`
   — all pass. Then `grep -rn _AI_TOOLING_AVAILABLE tests/` prints nothing
   (exit status 1).

5. Check (`format`): `ruff format tests/test_llm_client.py tests/test_baseline.py tests/test_pilot_validation.py`,
   then `pre-commit run --all-files` passes.

6. Commit:

   ```sh
   git add tests/test_llm_client.py tests/test_baseline.py tests/test_pilot_validation.py
   git commit -F - <<'EOF'
   test: drop no-op _AI_TOOLING_AVAILABLE patches

   Nothing reads _AI_TOOLING_AVAILABLE, so patching it isolated nothing.
   The baseline and pilot CLI tests now rely on the offline_llm fixture,
   which patches create_llm_client. The stub-client tests build a private
   copy of llm_integration with ai_tooling unimportable, so they run (rather
   than skip) with ai-tooling installed and pass with ANTHROPIC_API_KEY set.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S09
   Rows: T2

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

## Task 3 — Slice gate and evidence

**Rows:** T2 (verification only)
**Files:** `docs/plans/pr255-remediation/evidence/M001-S09.md` (create)
**Consumes:** Tasks 1–2 committed; `/tmp/llm_tripwire/llm_tripwire.py` and the "before" tripwire counts from Task 1 step 2b.
**Produces:** the evidence file for M001/S09.

Steps:

1. `grep -rn _AI_TOOLING_AVAILABLE tests/` — expected: no output (first half
   of T2's Verification cell).

2. Run `format`: `pre-commit run --all-files`. Expected: all hooks pass.

3. Run `unit` with a dummy key (second half of T2's Verification cell):
   `ANTHROPIC_API_KEY=dummy python -m pytest -n auto -m "not regression" tests/`.
   Expected: no failures. Then run `unit` as written, without the key:
   `env -u ANTHROPIC_API_KEY python -m pytest -n auto -m "not regression" tests/`.
   Expected: no failures. (If only the two hygiene clean-repo classes named in
   the context section fail, apply the `graphify-out` cleanup described there
   and rerun.)

4. Prove no real calls remain:

   ```sh
   rm -f /tmp/llm_tripwire/hits.log
   ANTHROPIC_API_KEY=dummy LLM_TRIPWIRE_LOG=/tmp/llm_tripwire/hits.log PYTHONPATH=/tmp/llm_tripwire \
     python -m pytest -p llm_tripwire -m "not regression" tests/ -q
   test ! -s /tmp/llm_tripwire/hits.log && echo "no real LLM calls"
   ```

   Expected: no failures and `no real LLM calls`. Any line in `hits.log` is a
   T2 finding: add its lookup site to `CREATE_LLM_CLIENT_SITES` (or its rule's
   `_llm` is already covered by the fixture), rerun, and include the fix in a
   further commit with the Task 1 trailers.

5. Run `gate`:
   `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`.
   Expected: no failures. If only
   `tests/regression/test_snapshots.py::test_regression_snapshot[httpx]` and
   `[gin]` fail with `dep-freshness` "no release in N months" findings, that
   is the pre-existing drift noted above: record it and stop for the owner.

6. Write `docs/plans/pr255-remediation/evidence/M001-S09.md` with: T2 → the empty `grep` result; the before/after tripwire counts (the
   `uniq -c` table from Task 1 step 2b, then "0 calls"); the pass/fail counts
   of `unit` with `ANTHROPIC_API_KEY=dummy` and without it; the `format` and
   `gate` results; the date.

7. Commit:

   ```sh
   git add docs/plans/pr255-remediation/evidence/M001-S09.md
   git commit -F - <<'EOF'
   docs(plans): record M001/S09 evidence

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S09
   Rows: T2

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```
