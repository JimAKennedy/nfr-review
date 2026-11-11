# M001/S08 implementation plan — Privacy SCM-username filter

**Slice:** M001/S08 — Privacy SCM-username filter
**Ledger:** docs/plans/pr255-remediation/ledger.md
**Branch:** pr255-fixes
**Rows:** PV1


> **Evidence rule (ledger standard):** evidence is appended per task as it lands and never names a commit SHA; the commits are found with `git log --grep="Slice: M001/S08"`. Earlier wording in this plan that asked for SHAs was removed on 2026-11-11 before execution.

## Task status

- [x] Task 1 — PV1: suppress SCM local parts only in SSH remotes, and lock both directions
- [ ] Task 2 — Slice gate and evidence

## Definition of Done

Copied verbatim from the ledger slice:

- [ ] `github@acme-corp.com` and `deploy@acme.com` in prose are reported
- [ ] `git@github.com:org/repo` in an SSH remote is not reported
- [ ] Both are locked by tests

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

- `src/nfr_review/hygiene/collectors/privacy.py`: `_scan_pii` skips every
  `_EMAIL_RE` match whose local part is in `_SCM_USERNAMES`
  (`git, hg, svn, deploy, ci, bitbucket, github, gitlab, ssh`), whatever
  follows it. Confirmed by running the collector on a scratch repo:
  `Contact github@acme-corp.com` in a `.md` file produces no email match,
  while `Contact user@example.com` does.
- `_EMAIL_RE` is `[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}` — the domain
  is one label plus a TLD, so on `git@gitlab.example.com:org/repo.git` the
  match is `git@gitlab.example` and `.com:org/...` follows it. The SSH test
  therefore has to skip remaining host characters before looking for `:`.
- Existing tests in `tests/test_hygiene_privacy.py` drive the collector with
  `_write_file(tmp_path, rel, content)` then
  `PrivacyCollector().collect(tmp_path, None)[0].payload["pii_matches"]`
  (list of dicts with `pattern_type`). The file does not import `pytest` yet.
- No regression snapshot can change: `tests/regression/` contains no hygiene
  or `HYG-PRV` output (searched `tests/regression/*.py`, `manifest.yaml` and
  `snapshots/`), and no hygiene report JSONL is committed (`git ls-files`
  shows only `tests/regression/snapshots/*.jsonl`). No fixture under
  `tests/fixtures/` contains an SCM-local-part address, so fixture-driven
  hygiene tests are unaffected. No regeneration step is needed.

---

## Task 1 — PV1: SCM local parts suppressed only in SSH remotes

**Rows:** PV1
**Files:**
- Modify `src/nfr_review/hygiene/collectors/privacy.py`
- Modify `tests/test_hygiene_privacy.py`

**Consumes:** `_EMAIL_RE`, `_SCM_USERNAMES`, `_scan_pii`.
**Produces:** `_SCP_REMOTE_TAIL_RE` and `_is_scm_ssh_remote(line, match)`; an
SCM local part is suppressed only when the match is preceded by `ssh://`
(also covers `git+ssh://`) or is scp-style — after any remaining host
characters it is followed by `:` and a non-space character. Everything else,
including `deploy@acme.com` and `github@acme-corp.com` in prose, is reported.

### Steps

1. In `tests/test_hygiene_privacy.py`, add `import pytest` (third-party block,
   after `from typing import Any`), and append after `class TestPrivacyCollector`
   (before the `# HYG-PRV-001: PII Patterns Rule` banner):

   ```python
   def _emails(tmp_path: Path, content: str) -> list[dict[str, Any]]:
       """Collect privacy evidence for one Markdown file; return its email matches."""
       _write_file(tmp_path, "docs/notes.md", content)
       pii = PrivacyCollector().collect(tmp_path, None)[0].payload["pii_matches"]
       return [m for m in pii if m["pattern_type"] == "email"]


   class TestScmUsernameFilter:
       """SCM service accounts are noise only inside SSH remotes."""

       @pytest.mark.parametrize(
           "line",
           [
               "Contact github@acme-corp.com for access.",
               "Pager alerts go to deploy@acme.com.",
               "Escalate to ci@acme.com: the on-call owner.",
               "Write to gitlab@corp-mail.org today",
           ],
       )
       def test_scm_local_part_in_prose_is_reported(self, tmp_path: Path, line: str) -> None:
           assert len(_emails(tmp_path, line + "\n")) == 1

       @pytest.mark.parametrize(
           "line",
           [
               "git clone git@github.com:org/repo.git",
               "url = ssh://git@github.com/org/repo",
               "pip install git+ssh://git@gitlab.com/org/repo.git",
               "remote: git@gitlab.example.com:org/repo.git",
               "hg clone ssh://hg@bitbucket.org/org/repo",
           ],
       )
       def test_scm_user_in_ssh_remote_is_not_reported(self, tmp_path: Path, line: str) -> None:
           assert _emails(tmp_path, line + "\n") == []

       def test_non_scm_user_in_ssh_remote_is_reported(self, tmp_path: Path) -> None:
           assert len(_emails(tmp_path, "git clone alice@example.com:org/repo.git\n")) == 1
   ```

2. Run and see it fail:

   ```
   .venv/bin/python -m pytest -n auto tests/test_hygiene_privacy.py -k TestScmUsernameFilter
   ```

   Expected: the four `test_scm_local_part_in_prose_is_reported[...]` cases fail
   with `assert 0 == 1`; the five SSH cases and
   `test_non_scm_user_in_ssh_remote_is_reported` pass (they lock the existing
   SSH suppression, which has no test today).

3. Implement in `src/nfr_review/hygiene/collectors/privacy.py`.

   a. Directly after the `_SCM_USERNAMES = frozenset(...)` assignment, add:

   ```python
   # An SCM service account (git@, deploy@, ...) is noise only as the user of an
   # SSH remote: URL-style ``ssh://git@host/...`` or scp-style
   # ``git@host:org/repo``. _EMAIL_RE stops after the first domain label, so the
   # scp test skips any remaining host characters before requiring ``:`` and a
   # non-space path character. Anywhere else (``deploy@acme.com`` in prose)
   # the address is real and is reported.
   _SCP_REMOTE_TAIL_RE = re.compile(r"[a-zA-Z0-9.-]*:\S")
   ```

   b. Directly before `def _scan_pii(`, add:

   ```python
   def _is_scm_ssh_remote(line: str, match: re.Match[str]) -> bool:
       """Return True when *match* is the SCM user@host of an SSH remote."""
       local_part = match.group().split("@", 1)[0].lower()
       if local_part not in _SCM_USERNAMES:
           return False
       if line[: match.start()].lower().endswith("ssh://"):
           return True
       return _SCP_REMOTE_TAIL_RE.match(line, match.end()) is not None
   ```

   c. In `_scan_pii`, replace

   ```python
               for _m in _EMAIL_RE.finditer(line):
                   local_part = _m.group().split("@")[0].lower()
                   if local_part in _SCM_USERNAMES:
                       continue
   ```

   with

   ```python
               for _m in _EMAIL_RE.finditer(line):
                   if _is_scm_ssh_remote(line, _m):
                       continue
   ```

4. Run `.venv/bin/ruff format src/nfr_review/hygiene/collectors/privacy.py tests/test_hygiene_privacy.py`,
   then `.venv/bin/python -m pytest -n auto tests/test_hygiene_privacy.py`.
   Expected: all pass (10 new cases plus the existing ones).

5. Commit:

   ```
   git add src/nfr_review/hygiene/collectors/privacy.py tests/test_hygiene_privacy.py
   git commit -F - <<'EOF'
   fix(hygiene): suppress SCM usernames only in SSH remotes

   The privacy collector dropped any email whose local part was an SCM
   account name, whatever its domain, so github@acme-corp.com and
   deploy@acme.com in prose went unreported. Suppress them only as the user
   of an ssh:// URL or an scp-style user@host:path remote, and test both
   directions; the SSH false-positive fix had no test.

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S08
   Rows: PV1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

6. Check (`format`, `unit` scoped): `.venv/bin/ruff check src/ tests/` is clean
   and `.venv/bin/python -m pytest -n auto tests/ -k "privacy or hygiene"` passes.

---

## Task 2 — Slice gate and evidence

**Rows:** PV1
**Files:** create `docs/plans/pr255-remediation/evidence/M001-S08.md`
**Consumes:** the Task 1 commit.
**Produces:** the slice's evidence record.

### Steps

1. `format`: `pre-commit run --all-files` — expect every hook to pass. If a
   hook rewrites a file, re-stage it and amend it into the Task 1 commit, then
   re-run until clean.
2. `unit`: `python -m pytest -n auto -m "not regression" tests/` — expect 0 failed.
3. `gate`: `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`
   — expect all three legs to pass with no snapshot diff (the regression
   suite carries no hygiene output; see "Code facts").
4. Write `docs/plans/pr255-remediation/evidence/M001-S08.md` in the layout of
   `evidence/M001-S01.md`: heading `# Evidence — M001/S08`, section
   `## M001/S08 — Privacy SCM-username filter`, a bullet `PV1 →` the test class
   `TestScmUsernameFilter` that locks it, then the observed `format` / `unit` /
   `gate` results (pass/fail counts copied from the output) and the date.
   Record only identifiers that appear in that command output.
5. Commit:

   ```
   git add docs/plans/pr255-remediation/evidence/M001-S08.md
   git commit -F - <<'EOF'
   docs(plans): record M001/S08 evidence

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S08
   Rows: PV1

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   EOF
   ```

6. Check (`gate`): the step 3 run is green on the head commit.

---

## Self-review

- **DoD coverage:** DoD 1 → `test_scm_local_part_in_prose_is_reported`
  (`github@acme-corp.com`, `deploy@acme.com`, plus `ci@` and `gitlab@`);
  DoD 2 → `test_scm_user_in_ssh_remote_is_not_reported`
  (`git@github.com:org/repo.git`, `ssh://git@github.com/org/repo`, and
  `git+ssh://`, multi-label host, `hg@` variants); DoD 3 → both are in
  `TestScmUsernameFilter`, committed in Task 1.
- **Row coverage:** PV1 → Task 1; evidence in Task 2.
- **Placeholder scan:** no TBD/TODO; the only `<SHA>` is an instruction to copy
  a value from `git log` output in Task 2, not a value written by this plan.
- **Name consistency:** `_SCP_REMOTE_TAIL_RE`, `_is_scm_ssh_remote`,
  `_emails`, `TestScmUsernameFilter` are defined in Task 1; `_EMAIL_RE`,
  `_SCM_USERNAMES`, `_scan_pii`, `_write_file`, `PrivacyCollector` exist.
  The suppression rule was dry-run against all ten test lines while writing
  this plan and gives the asserted result for each.
