# M001/S02 — Rust collector correctness: implementation plan

**Slice:** M001/S02 — ledger `docs/plans/pr255-remediation/ledger.md`

## Task status

- [x] Task 1 — Lock-call arity and async-context boundary
- [x] Task 2 — Exact test-code detection, mutex `in_test`, bounded unwrap summary
- [x] Task 3 — `use`-declaration alias resolution for HTTP-client and spawn extractors
- [ ] Task 4 — Cargo.toml workspace inheritance, target-cfg tables, renames, `target/` pruning
- [ ] Task 5 — Complete Rust rule descriptions and regenerated `rules.json`

## Definition of Done

- [ ] An io `.write(..)`/`.read(..)` with arguments is not reported as a lock call
- [ ] A blocking call inside a closure (e.g. `spawn_blocking(move || …)`) in an async fn is not reported, and one inside an `async {}` block in a sync fn is
- [ ] Test-code suppression matches `#[test]`, `#[cfg(test)]` and a `mod tests` name exactly, so `mod attestation` is still scanned
- [ ] Imported paths (`use reqwest::Client; Client::new()`, imported `spawn`, `tokio::task::spawn`) are recognised
- [ ] Unwrap summaries are single-line and bounded in length
- [ ] `rust-mutex-lock-unwrap` does not report calls in test code
- [ ] Workspace-inherited, target-cfg and renamed Cargo dependencies resolve to the right crate, and nothing under `target/` is parsed
- [ ] The three truncated Rust rule descriptions read as complete sentences
- [ ] Each outcome above is locked by a named test case

## Validation

Tokens from `.jk/validations.yml`, run from the worktree root with the
project venv first on `PATH` (`source .venv/bin/activate`, so `python` is
`.venv/bin/python`):

- `format` — `pre-commit run --all-files`
- `unit` — `python -m pytest -n auto -m "not regression" tests/`
- `regression` — `python -m pytest -n auto -m regression --timeout=600 tests/regression`
- `gate` — `pre-commit run --all-files && python -m pytest -n auto -m "not regression" tests/ && python -m pytest -n auto -m regression --timeout=600 tests/regression`

## Conventions for every task

- Work in the worktree on branch `pr255-fixes`. All commands below are run
  from the worktree root.
- After editing any `.py` file, run `.venv/bin/ruff format <file>` on it
  before committing (project CLAUDE.md). Line length is 95.
- Tasks 1–4 change collector or rule output, so each owes `regression`. Run
  it; if snapshots differ, refresh them with
  `.venv/bin/python -m pytest -n auto -m regression --timeout=600 tests/regression --update-snapshots`,
  rerun `regression` without the flag to confirm it passes, inspect the diff
  as the task describes, and `git add tests/regression/snapshots/` in the
  **same** task commit — never in a follow-up commit.
- Every commit message ends with the trailers given in the task, followed by
  the session's attribution line.
- Collector tests in Tasks 1–3 use a helper added in Task 1 that writes a
  snippet to `tmp_path/lib.rs` and runs the real `RustAstCollector` (real
  tree-sitter parsing), matching the existing `tmp_path` edge-case tests.

---

## Task 1 — Lock-call arity and async-context boundary

**Rows:** R1 (sub-items: lock-method arity; closure/async-block boundary;
async-block sleep)

**Files**

- Modify `src/nfr_review/collectors/rust_ast.py`
- Modify `tests/test_rust_ast_collector.py`

**Consumes:** existing `_LOCK_METHODS`, `_extract_unwrap_expect_and_mutex`,
`_extract_async_blocking_calls`, `_enclosing_async_function`,
`_is_async_function_item`.
**Produces:** `_lock_method_name(call, source) -> str | None`,
`_enclosing_function_name(node, source) -> str`, a reworked
`_enclosing_async_function`, and the test helper `_payload_for_source`
(used again by Tasks 2 and 3).

### Steps

1. Write the failing tests. In `tests/test_rust_ast_collector.py` add
   `import textwrap` to the imports, then add this helper below
   `_payload_for`:

   ```python
   def _payload_for_source(tmp_path: Path, source: str):
       (tmp_path / "lib.rs").write_text(textwrap.dedent(source), encoding="utf-8")
       evidences = RustAstCollector().collect(tmp_path, config=None)
       assert len(evidences) == 1
       return evidences[0].payload
   ```

   Append these classes:

   ```python
   class TestLockCallArity:
       def test_io_write_with_args_is_not_a_lock_unwrap(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               use std::io::Write;
               fn emit(out: &mut Vec<u8>) {
                   out.write(b"x").unwrap();
               }
               """,
           )
           assert payload.mutex_lock_unwraps == []
           assert [(c.method, c.receiver) for c in payload.unwrap_expect_calls] == [
               ("unwrap", 'out.write(b"x")')
           ]

       def test_zero_arg_lock_unwrap_still_reported(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               fn bump(m: &std::sync::Mutex<u8>) {
                   *m.lock().unwrap() += 1;
               }
               """,
           )
           assert [c.lock_method for c in payload.mutex_lock_unwraps] == ["lock"]

       def test_io_read_write_with_args_not_sync_lock_in_async(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               async fn save(f: &mut std::fs::File, buf: &[u8]) {
                   f.write(buf).unwrap();
                   let _ = f.read(&mut [0u8; 4]);
               }
               async fn guard(m: &std::sync::Mutex<u8>) {
                   let _g = m.lock();
               }
               """,
           )
           assert [(c.function_name, c.call, c.line) for c in payload.async_blocking_calls] == [
               ("guard", "m.lock", 6)
           ]


   class TestAsyncContextBoundary:
       def test_blocking_call_in_closure_in_async_fn_not_reported(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               async fn handler() {
                   tokio::task::spawn_blocking(move || {
                       std::thread::sleep(std::time::Duration::from_secs(1));
                   });
               }
               """,
           )
           assert payload.async_blocking_calls == []

       def test_sleep_in_async_block_in_sync_fn_reported(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               fn start() {
                   let fut = async {
                       std::thread::sleep(std::time::Duration::from_secs(1));
                   };
                   drop(fut);
               }
               """,
           )
           assert [
               (c.function_name, c.call, c.kind, c.line) for c in payload.async_blocking_calls
           ] == [("start", "std::thread::sleep", "thread::sleep", 3)]

       def test_async_block_inside_closure_is_async_context(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               async fn fan_out(items: Vec<u8>) {
                   let _futs: Vec<_> = items
                       .into_iter()
                       .map(|_| async move {
                           std::thread::sleep(std::time::Duration::from_millis(1));
                       })
                       .collect();
               }
               """,
           )
           assert [(c.function_name, c.line) for c in payload.async_blocking_calls] == [
               ("fan_out", 5)
           ]
   ```

   If ruff format rewraps any of these lines, keep its output.

2. Run them and see them fail:

   ```
   .venv/bin/python -m pytest tests/test_rust_ast_collector.py::TestLockCallArity tests/test_rust_ast_collector.py::TestAsyncContextBoundary -q
   ```

   Expected: `test_io_write_with_args_is_not_a_lock_unwrap` fails (a
   `write` entry in `mutex_lock_unwraps`),
   `test_io_read_write_with_args_not_sync_lock_in_async` fails (`f.write` and
   `f.read` reported), `test_blocking_call_in_closure_in_async_fn_not_reported`
   fails (sleep reported in `handler`), `test_sleep_in_async_block_in_sync_fn_reported`
   fails (empty list). `test_zero_arg_lock_unwrap_still_reported` and
   `test_async_block_inside_closure_is_async_context` pass already; they guard
   behaviour the change must keep.

3. Implement in `src/nfr_review/collectors/rust_ast.py`:

   1. Add, after `_is_inside_loop`:

      ```python
      def _lock_method_name(call: Node, source: bytes) -> str | None:
          """Return "lock"/"read"/"write" when *call* is a zero-argument
          ``.lock()``/``.read()``/``.write()`` method call, else None.

          io calls such as ``out.write(buf)`` or ``f.read(&mut b)`` take an
          argument; std ``Mutex``/``RwLock`` lock calls never do.
          """
          func = call.child_by_field_name("function")
          if func is None or func.type != "field_expression":
              return None
          field_node = func.child_by_field_name("field")
          if field_node is None or text(field_node, source) not in _LOCK_METHODS:
              return None
          args = call.child_by_field_name("arguments")
          if args is not None and args.named_child_count > 0:
              return None
          return text(field_node, source)
      ```

   2. In `_extract_unwrap_expect_and_mutex`, replace the block that inspects
      `receiver` (the `if receiver is not None and receiver.type ==
      "call_expression":` block with its nested `rfunc`/`rfield` checks) with:

      ```python
      if receiver is not None and receiver.type == "call_expression":
          lock_method = _lock_method_name(receiver, source)
          if lock_method is not None:
              mutex_calls.append(
                  RustMutexLockUnwrap(
                      lock_method=lock_method,
                      line=call.start_point[0] + 1,
                      file=rel_path,
                  )
              )
              continue
      ```

      A `.write(b"x").unwrap()` now falls through and is recorded as an
      ordinary unwrap call.

   3. In `_extract_async_blocking_calls`, replace the `elif func.type ==
      "field_expression":` branch's condition with
      `elif _lock_method_name(call, source) is not None:` and keep its body
      (the `awaited` check and the `sync-lock-no-await` append using
      `text(func, source)`) unchanged.

   4. Add `_enclosing_function_name` and rewrite `_enclosing_async_function`:

      ```python
      def _enclosing_function_name(node: Node, source: bytes) -> str:
          """Name of the nearest enclosing fn item, or "<async block>" at item level."""
          parent = node.parent
          while parent is not None:
              if parent.type == "function_item":
                  name_node = parent.child_by_field_name("name")
                  return text(name_node, source) if name_node is not None else "<anonymous>"
              parent = parent.parent
          return "<async block>"


      def _enclosing_async_function(node: Node, source: bytes) -> str | None:
          """Return the function name when *node* runs on an async executor.

          Walks outwards and stops at the first boundary:
          - ``async_block``: async context; returns the enclosing fn's name
            (sync or async), so ``async { thread::sleep(..) }`` in a sync fn
            is reported.
          - ``closure_expression``: returns None — the closure body may run
            elsewhere (``spawn_blocking(move || ..)``, a thread, an iterator).
          - ``function_item``: its name if it is ``async fn``, else None.
          """
          parent = node.parent
          while parent is not None:
              if parent.type == "async_block":
                  return _enclosing_function_name(parent, source)
              if parent.type == "closure_expression":
                  return None
              if parent.type == "function_item":
                  if not _is_async_function_item(parent):
                      return None
                  name_node = parent.child_by_field_name("name")
                  return text(name_node, source) if name_node is not None else "<anonymous>"
              parent = parent.parent
          return None
      ```

   5. Run `.venv/bin/ruff format src/nfr_review/collectors/rust_ast.py tests/test_rust_ast_collector.py`.

4. Run and see them pass, plus the whole Rust collector module:

   ```
   .venv/bin/python -m pytest tests/test_rust_ast_collector.py tests/test_rust_integration.py tests/test_rust_rules.py -q
   ```

   All pass (the `rust-sample-repo` fixtures use zero-argument lock calls).

5. Run `regression`. If snapshots differ, refresh as in the conventions,
   then confirm every changed snapshot line comes from the Rust AST collector:

   ```
   git diff -U0 -- 'tests/regression/snapshots/*.jsonl' | grep '^[-+]{' | grep -vc '"collector_name": "rust-ast"'
   ```

   prints `0`.

6. Commit:

   ```
   git add src/nfr_review/collectors/rust_ast.py tests/test_rust_ast_collector.py tests/regression/snapshots/
   git commit -m "fix(rust): require zero-arg lock calls and stop async context at closures

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S02
   Rows: R1"
   ```

**Check:** `regression` passes (and `format` via `pre-commit run --all-files`).

---

## Task 2 — Exact test-code detection, mutex `in_test`, bounded unwrap summary

**Rows:** R1 (sub-items: substring test matching; mutex rule ignores
`in_test`; unbounded unwrap summary)

**Files**

- Modify `src/nfr_review/collectors/rust_ast.py`
- Modify `src/nfr_review/collectors/payloads/rust_ast.py`
- Modify `src/nfr_review/rules/rust_mutex_lock_unwrap.py`
- Modify `src/nfr_review/rules/rust_unwrap_expect.py`
- Modify `tests/test_rust_ast_collector.py`
- Modify `tests/test_rust_rules.py`

**Consumes:** `_payload_for_source` (Task 1), `_lock_method_name` (Task 1),
existing `_ATTR_SIBLING_TYPES`, `_preceding_attrs_text`, `_is_inside_test`.
**Produces:** `_TEST_MOD_NAMES`, `_preceding_attributes(item_node) ->
list[Node]`, `_is_test_attribute(attr_item, source) -> bool`, rewritten
`_is_inside_test`; required field `RustMutexLockUnwrap.in_test: bool`;
`_short_receiver(receiver) -> str` and `_RECEIVER_MAX = 60` in
`rules/rust_unwrap_expect.py`. `_preceding_attrs_text` is deleted (its only
caller is `_is_inside_test`).

**Exact matching rules (documented in the `_is_inside_test` docstring):**

- An attribute is a test attribute when its path is exactly `test`, or its
  last `::` segment is exactly `test` (`#[tokio::test]`,
  `#[tokio::test(flavor = "multi_thread")]`, `#[async_std::test]`,
  `#[actix_rt::test]`), or it is `cfg` whose argument token tree is exactly
  `(test)` after removing whitespace. Not matched: `#[cfg(feature =
  "testing")]`, `#[cfg(all(test, ..))]`, `#[cfg(not(test))]`, `#[rstest]`,
  `#[test_case(..)]`.
- A `mod` is test code when it carries a test attribute or is named exactly
  `tests` or `test`. `mod attestation`, `mod contest` are scanned.
- An `fn` is test code when it carries a test attribute; its name never
  matters (`fn latest`, `fn test_helper` are scanned unless attributed).

### Steps

1. Write the failing tests. Append to `tests/test_rust_ast_collector.py`:

   ```python
   _TEST_DETECTION_SRC = """\
   mod attestation {
       pub fn verify(v: Option<u8>) -> u8 {
           v.unwrap()
       }
   }
   mod contest {
       pub fn score(v: Option<u8>) -> u8 {
           v.unwrap()
       }
   }
   #[cfg(feature = "testing")]
   fn latest(v: Option<u8>) -> u8 {
       v.unwrap()
   }
   #[cfg(test)]
   mod checks {
       fn a(v: Option<u8>) -> u8 {
           v.unwrap()
       }
   }
   mod tests {
       fn b(v: Option<u8>) -> u8 {
           v.unwrap()
       }
   }
   #[tokio::test(flavor = "multi_thread")]
   async fn it_works() {
       Some(1u8).unwrap();
   }
   #[test]
   fn plain() {
       Some(1u8).unwrap();
   }
   """


   def _in_test_by_line(tmp_path: Path) -> dict[int, bool]:
       payload = _payload_for_source(tmp_path, _TEST_DETECTION_SRC)
       return {c.line: c.in_test for c in payload.unwrap_expect_calls}


   class TestTestCodeDetection:
       def test_mod_attestation_is_scanned(self, tmp_path: Path) -> None:
           assert _in_test_by_line(tmp_path)[3] is False

       def test_mod_contest_is_scanned(self, tmp_path: Path) -> None:
           assert _in_test_by_line(tmp_path)[8] is False

       def test_fn_latest_with_cfg_feature_testing_is_scanned(self, tmp_path: Path) -> None:
           assert _in_test_by_line(tmp_path)[13] is False

       def test_cfg_test_mod_is_suppressed(self, tmp_path: Path) -> None:
           assert _in_test_by_line(tmp_path)[18] is True

       def test_mod_named_tests_is_suppressed(self, tmp_path: Path) -> None:
           assert _in_test_by_line(tmp_path)[23] is True

       def test_tokio_test_fn_is_suppressed(self, tmp_path: Path) -> None:
           assert _in_test_by_line(tmp_path)[28] is True

       def test_plain_test_fn_is_suppressed(self, tmp_path: Path) -> None:
           assert _in_test_by_line(tmp_path)[32] is True


   class TestMutexLockUnwrapInTest:
       def test_mutex_lock_unwrap_in_test_module_marked(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               use std::sync::Mutex;
               fn bump(m: &Mutex<u8>) {
                   *m.lock().unwrap() += 1;
               }
               #[cfg(test)]
               mod tests {
                   #[test]
                   fn bumps() {
                       let m = std::sync::Mutex::new(0u8);
                       let _g = m.lock().unwrap();
                   }
               }
               """,
           )
           assert [(c.line, c.in_test) for c in payload.mutex_lock_unwraps] == [
               (3, False),
               (10, True),
           ]
   ```

   In `tests/test_rust_rules.py`:

   1. In `TestRustMutexLockUnwrapRule.test_flags_lock_unwrap`, change the
      constructor to
      `RustMutexLockUnwrap(lock_method="lock", line=10, file="lib.rs", in_test=False)`.
   2. Add to `TestRustMutexLockUnwrapRule`:

      ```python
      def test_skips_test_call(self) -> None:
          payload = _empty_payload(
              mutex_lock_unwraps=[
                  RustMutexLockUnwrap(lock_method="lock", line=10, file="lib.rs", in_test=True)
              ]
          )
          result = RustMutexLockUnwrapRule().evaluate([_evidence(payload)], None)
          assert all(f.rag == "green" for f in result.findings)
      ```

   3. Add to `TestRustUnwrapExpectRule`:

      ```python
      def test_multiline_receiver_summary_is_single_line(self) -> None:
          payload = _empty_payload(
              unwrap_expect_calls=[
                  RustUnwrapExpectCall(
                      method="expect",
                      receiver="create_config()\n        .create_pool(NoTls)",
                      line=5,
                      file="lib.rs",
                      in_test=False,
                  )
              ]
          )
          result = RustUnwrapExpectRule().evaluate([_evidence(payload)], None)
          amber = [f for f in result.findings if f.rag == "amber"]
          assert amber[0].summary == (
              "create_config().create_pool(NoTls).expect() panics instead of propagating the error"
          )


      def test_long_receiver_summary_is_capped_at_60_chars(self) -> None:
          receiver = (
              "Response::builder()\n"
              '        .header("Access-Control-Allow-Origin", "*")\n'
              '        .header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")\n'
              "        .body(Body::empty())"
          )
          payload = _empty_payload(
              unwrap_expect_calls=[
                  RustUnwrapExpectCall(
                      method="unwrap", receiver=receiver, line=5, file="lib.rs", in_test=False
                  )
              ]
          )
          result = RustUnwrapExpectRule().evaluate([_evidence(payload)], None)
          summary = [f for f in result.findings if f.rag == "amber"][0].summary
          shown = 'Response::builder().header("Access-Control-Allow-Origin", "…'
          assert len(shown) == 60
          assert "\n" not in summary
          assert summary == f"{shown}.unwrap() panics instead of propagating the error"
      ```

2. Run them and see them fail:

   ```
   .venv/bin/python -m pytest tests/test_rust_ast_collector.py::TestTestCodeDetection tests/test_rust_ast_collector.py::TestMutexLockUnwrapInTest tests/test_rust_rules.py -q
   ```

   Expected failures: `test_mod_attestation_is_scanned`,
   `test_mod_contest_is_scanned`,
   `test_fn_latest_with_cfg_feature_testing_is_scanned` (all `True` today —
   substring match on `"test"`); `test_mutex_lock_unwrap_in_test_module_marked`
   (`AttributeError`: no `in_test`); `test_flags_lock_unwrap` and
   `test_skips_test_call` (pydantic `ValidationError`, extra field `in_test`
   forbidden); the two summary tests (newline / full receiver in summary).
   The four suppression tests pass already and guard behaviour.

3. Implement:

   1. `src/nfr_review/collectors/payloads/rust_ast.py`: add `in_test: bool`
      as the last field of `RustMutexLockUnwrap` (required, mirroring
      `RustUnwrapExpectCall.in_test`).

   2. `src/nfr_review/collectors/rust_ast.py`:
      - Add `_TEST_MOD_NAMES = frozenset({"test", "tests"})` next to the other
        module constants.
      - Replace `_preceding_attrs_text` with:

        ```python
        def _preceding_attributes(item_node: Node) -> list[Node]:
            """``attribute_item`` siblings directly above *item_node* (comments skipped)."""
            attrs: list[Node] = []
            sib = item_node.prev_sibling
            while sib is not None and sib.type in _ATTR_SIBLING_TYPES:
                if sib.type == "attribute_item":
                    attrs.append(sib)
                sib = sib.prev_sibling
            return attrs


        def _is_test_attribute(attr_item: Node, source: bytes) -> bool:
            attr = next((c for c in attr_item.named_children if c.type == "attribute"), None)
            if attr is None or not attr.named_children:
                return False
            path = text(attr.named_children[0], source)
            if path == "cfg":
                args = attr.child_by_field_name("arguments")
                return args is not None and "".join(text(args, source).split()) == "(test)"
            return path.rsplit("::", 1)[-1] == "test"
        ```

      - Replace `_is_inside_test` with (docstring states the matching rules
        listed above):

        ```python
        def _is_inside_test(node: Node, source: bytes) -> bool:
            parent = node.parent
            while parent is not None:
                if parent.type in ("function_item", "mod_item"):
                    if any(_is_test_attribute(a, source) for a in _preceding_attributes(parent)):
                        return True
                    if parent.type == "mod_item":
                        name_node = parent.child_by_field_name("name")
                        if name_node is not None and text(name_node, source) in _TEST_MOD_NAMES:
                            return True
                parent = parent.parent
            return False
        ```

      - In `_extract_unwrap_expect_and_mutex`, add
        `in_test=_is_inside_test(call, source),` to the `RustMutexLockUnwrap(...)`
        constructor added in Task 1.

   3. `src/nfr_review/rules/rust_mutex_lock_unwrap.py`: at the top of the
      `for call in payload.mutex_lock_unwraps:` loop add
      `if call.in_test:` / `continue`; change the class docstring and
      `all_clear_summary` to `"No .lock()/.read()/.write().unwrap() calls
      detected outside test code."`.

   4. `src/nfr_review/rules/rust_unwrap_expect.py`: add `import re`, then at
      module level:

      ```python
      _RECEIVER_MAX = 60


      def _short_receiver(receiver: str) -> str:
          """One-line receiver text for the summary, at most _RECEIVER_MAX chars.

          Line breaks and the indentation around them are dropped (Rust method
          chains break before the ``.``), other whitespace runs become one space,
          and anything longer than the cap ends in an ellipsis.
          """
          one_line = re.sub(r"\s+", " ", re.sub(r"\s*\n\s*", "", receiver)).strip()
          if len(one_line) <= _RECEIVER_MAX:
              return one_line
          return one_line[: _RECEIVER_MAX - 1] + "…"
      ```

      and change the summary to
      `f"{_short_receiver(call.receiver)}.{call.method}() panics instead of propagating the error"`
      (wrapped to 95 columns by ruff format). The payload `receiver` keeps the
      full text.

   5. Run `.venv/bin/ruff format` on all six changed `.py` files.

4. Run and see them pass:

   ```
   .venv/bin/python -m pytest tests/test_rust_ast_collector.py tests/test_rust_rules.py tests/test_rust_integration.py -q
   ```

   `test_test_module_unwrap_marked_in_test` (fixture `bad_unwrap.rs`,
   `#[cfg(test)] mod tests` + `#[test]`) still passes.

5. Run `regression`. The `awesome-compose` and `opentelemetry-demo`
   `rust-unwrap-expect` summaries change (multi-line receivers become one
   line; long ones end in `…`), and findings may disappear or appear where
   the old substring test-matching was wrong. Refresh as in the conventions,
   then confirm:

   ```
   git diff -U0 -- 'tests/regression/snapshots/*.jsonl' | grep '^[-+]{' | grep -vc '"collector_name": "rust-ast"'
   ```

   prints `0`, and no `+` line's `summary` contains `\n`:

   ```
   git diff -U0 -- 'tests/regression/snapshots/*.jsonl' | grep '^+{' | grep '"rule_id": "rust-unwrap-expect"' | grep -c '\\n'
   ```

   prints `0`.

6. Commit:

   ```
   git add src/nfr_review/collectors/rust_ast.py src/nfr_review/collectors/payloads/rust_ast.py src/nfr_review/rules/rust_mutex_lock_unwrap.py src/nfr_review/rules/rust_unwrap_expect.py tests/test_rust_ast_collector.py tests/test_rust_rules.py tests/regression/snapshots/
   git commit -m "fix(rust): exact test-code matching, mutex in_test, bounded unwrap summary

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S02
   Rows: R1"
   ```

**Check:** `regression` passes (and `format`).

---

## Task 3 — `use`-declaration alias resolution

**Rows:** R1 (sub-item: imported paths)

**Files**

- Modify `src/nfr_review/collectors/rust_ast.py`
- Modify `tests/test_rust_ast_collector.py`

**Consumes:** `_payload_for_source` (Task 1); existing
`_extract_http_client_builds`, `_extract_spawn_calls`, `RustAstCollector._parse_file`.
**Produces:** `_collect_use_aliases(node, prefix, source, aliases) -> None`,
`_build_use_aliases(root, source) -> dict[str, str]`,
`_resolve_path(path, aliases) -> str`, `_chain_root_callee(node: Node | None) -> Node | None`,
`_SPAWN_PATHS`; new keyword-only parameter `aliases: dict[str, str]` on
`_extract_http_client_builds` and `_extract_spawn_calls`.

The extractors look for these full paths: `reqwest::Client::new`
(HTTP, `call="reqwest::Client::new"`), a `.build()` chain rooted at
`reqwest::Client::builder` (HTTP, `call="reqwest::Client::builder()...build()"`),
and `tokio::spawn` (spawn). After this task spawn also accepts
`tokio::task::spawn`.

### Steps

1. Write the failing tests. Append to `tests/test_rust_ast_collector.py`:

   ```python
   class TestImportedPaths:
       def test_imported_client_new(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               use reqwest::Client;
               fn build() {
                   let _c = Client::new();
               }
               """,
           )
           assert [(b.call, b.has_timeout, b.line) for b in payload.http_client_builds] == [
               ("reqwest::Client::new", False, 3)
           ]

       def test_imported_client_builder_without_timeout(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               use reqwest::Client;
               fn build() {
                   let _c = Client::builder().build();
               }
               """,
           )
           assert [(b.call, b.has_timeout) for b in payload.http_client_builds] == [
               ("reqwest::Client::builder()...build()", False)
           ]

       def test_renamed_crate_alias(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               use reqwest as rq;
               fn build() {
                   let _c = rq::Client::new();
               }
               """,
           )
           assert [b.call for b in payload.http_client_builds] == ["reqwest::Client::new"]

       def test_imported_spawn_in_loop(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               use tokio::spawn;
               async fn run(n: u32) {
                   for i in 0..n {
                       spawn(async move { i });
                   }
               }
               """,
           )
           assert [(c.line, c.in_loop) for c in payload.spawn_calls] == [(4, True)]

       def test_fully_qualified_tokio_task_spawn(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               async fn run(n: u32) {
                   for i in 0..n {
                       tokio::task::spawn(async move { i });
                   }
               }
               """,
           )
           assert [(c.line, c.in_loop) for c in payload.spawn_calls] == [(3, True)]

       def test_grouped_use_with_rename_and_module_import(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               use tokio::{task, task::spawn as go};
               async fn run(n: u32) {
                   for i in 0..n {
                       go(async move { i });
                       task::spawn(async move { i });
                   }
               }
               """,
           )
           assert [(c.line, c.in_loop) for c in payload.spawn_calls] == [(4, True), (5, True)]

       def test_unimported_local_spawn_not_reported(self, tmp_path: Path) -> None:
           payload = _payload_for_source(
               tmp_path,
               """\
               fn spawn<F: FnOnce()>(f: F) {
                   f()
               }
               fn run() {
                   for _ in 0..3 {
                       spawn(|| ());
                   }
               }
               """,
           )
           assert payload.spawn_calls == []
   ```

2. Run them and see them fail:

   ```
   .venv/bin/python -m pytest tests/test_rust_ast_collector.py::TestImportedPaths -q
   ```

   Expected: all fail except `test_unimported_local_spawn_not_reported`
   (passes today and guards against over-matching).

3. Implement in `src/nfr_review/collectors/rust_ast.py`:

   1. Add `_SPAWN_PATHS = frozenset({"tokio::spawn", "tokio::task::spawn"})`.
   2. Add:

      ```python
      def _collect_use_aliases(
          node: Node, prefix: str, source: bytes, aliases: dict[str, str]
      ) -> None:
          """Record local-name -> full-path entries for one ``use`` tree node."""
          kind = node.type
          if kind == "identifier":
              name = text(node, source)
              aliases[name] = prefix + name
          elif kind == "scoped_identifier":
              full = prefix + text(node, source)
              aliases[full.rsplit("::", 1)[-1]] = full
          elif kind == "use_as_clause":
              path = node.child_by_field_name("path")
              alias = node.child_by_field_name("alias")
              if path is not None and alias is not None:
                  aliases[text(alias, source)] = prefix + text(path, source)
          elif kind == "scoped_use_list":
              path = node.child_by_field_name("path")
              inner = prefix + (text(path, source) + "::" if path is not None else "")
              use_list = node.child_by_field_name("list")
              if use_list is not None:
                  _collect_use_aliases(use_list, inner, source, aliases)
          elif kind == "use_list":
              for child in node.named_children:
                  _collect_use_aliases(child, prefix, source, aliases)
          elif kind == "self" and prefix:
              full = prefix.removesuffix("::")
              aliases[full.rsplit("::", 1)[-1]] = full
          # use_wildcard (`use a::*`) binds no single name and is ignored.


      def _build_use_aliases(root: Node, source: bytes) -> dict[str, str]:
          """File-wide map of names bound by ``use`` declarations to full paths.

          Covers ``use a::B``, ``use a::{b, c::D}``, ``use a::b as c``,
          ``use a::{self}``. Scope is the whole file (a ``use`` inside a fn or
          mod applies file-wide) — an accepted approximation for a lint.
          """
          aliases: dict[str, str] = {}
          for decl in find_nodes(root, "use_declaration"):
              argument = decl.child_by_field_name("argument")
              if argument is not None:
                  _collect_use_aliases(argument, "", source, aliases)
          return aliases


      def _resolve_path(path: str, aliases: dict[str, str]) -> str:
          """Expand the first ``::`` segment of *path* through *aliases*."""
          path = path.removeprefix("::")
          head, sep, rest = path.partition("::")
          if head in aliases:
              path = aliases[head] + sep + rest
          return path.removeprefix("::")


      def _chain_root_callee(node: Node | None) -> Node | None:
          """For a method chain ``X::f().a().b()``, return the ``X::f`` node."""
          while node is not None:
              if node.type == "call_expression":
                  func = node.child_by_field_name("function")
                  if func is None:
                      return None
                  if func.type != "field_expression":
                      return func
                  node = func.child_by_field_name("value")
              elif node.type == "field_expression":
                  node = node.child_by_field_name("value")
              else:
                  return None
          return None
      ```

   3. Change `_extract_http_client_builds(root, source, rel_path)` to
      `_extract_http_client_builds(root, source, rel_path, *, aliases: dict[str, str])`:
      - For the `Client::new` case: accept `func.type in ("scoped_identifier",
        "identifier")` and test
        `_resolve_path(text(func, source), aliases) == "reqwest::Client::new"`;
        the appended `RustHttpClientBuild` is unchanged.
      - For the builder case (field `build`): replace the
        `"reqwest::Client::builder" in full_text` test with
        `root_fn = _chain_root_callee(call)` and require
        `root_fn is not None and root_fn.type in ("scoped_identifier", "identifier")
        and _resolve_path(text(root_fn, source), aliases) == "reqwest::Client::builder"`.
        `has_timeout=".timeout(" in text(call, source)` and the `call` label are
        unchanged.
   4. Change `_extract_spawn_calls(root, source, rel_path)` to
      `_extract_spawn_calls(root, source, rel_path, *, aliases: dict[str, str])`:
      accept `func.type in ("scoped_identifier", "identifier")` and require
      `_resolve_path(text(func, source), aliases) in _SPAWN_PATHS`.
   5. In `RustAstCollector._parse_file`, compute
      `aliases = _build_use_aliases(root, source)` after `root = tree.root_node`
      and pass `aliases=aliases` to both extractors.
   6. Run `.venv/bin/ruff format src/nfr_review/collectors/rust_ast.py tests/test_rust_ast_collector.py`.

4. Run and see them pass, with the existing HTTP/spawn fixture tests:

   ```
   .venv/bin/python -m pytest tests/test_rust_ast_collector.py tests/test_rust_integration.py tests/test_rust_class_diagram.py -q
   ```

5. Run `regression`. New `rust-http-no-timeout` / `rust-unbounded-spawn-in-loop`
   findings may appear in corpora that import `reqwest::Client` or `spawn`.
   Refresh as in the conventions, then confirm the `rust-ast` collector check
   from Task 1 step 5 prints `0`.

6. Commit:

   ```
   git add src/nfr_review/collectors/rust_ast.py tests/test_rust_ast_collector.py tests/regression/snapshots/
   git commit -m "fix(rust): resolve use-imported paths for http-client and spawn detection

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S02
   Rows: R1"
   ```

**Check:** `regression` passes (and `format`).

---

## Task 4 — Cargo.toml resolution and `target/` pruning

**Rows:** R2

**Files**

- Modify `src/nfr_review/collectors/rust_deps.py`
- Modify `tests/test_rust_deps_collector.py`

**Consumes:** existing `_DEP_TABLES`, `_dep_version`, `_enrich`,
`should_exclude_path`, `compile_exclude_patterns`; `ALWAYS_SKIP_DIRS` from
`nfr_review.path_filter`.
**Produces:** `_find_cargo_tomls(repo_path) -> list[Path]`,
`_load_cargo_toml(path) -> dict[str, Any] | None`,
`_iter_dep_tables(data) -> Iterator[dict[str, Any]]`,
`_workspace_dependencies(manifest, repo_path, loaded) -> dict[str, Any]`,
`_resolve_dep(key, spec, workspace_deps) -> tuple[str, str] | None`,
`_cargo_deps(data, workspace_deps) -> list[tuple[str, str]]`. `_parse_cargo_toml`
is deleted; its only caller is `RustDepsCollector.collect`. (The
same-named function in `src/nfr_review/hygiene/collectors/documentation.py`
is a separate, unrelated helper and is not touched.)

**Resolution rules:**

- `key = { workspace = true, .. }` takes its spec from `[workspace.dependencies].key`
  of the nearest ancestor manifest (the member's own directory first, then
  upward, stopping at `repo_path`) that has a `[workspace]` table. Missing
  entry → skipped. `package.workspace = "path"` overrides are not followed.
- The root's `[workspace.dependencies]` entries are not reported on their own;
  they are reported through each member that inherits them (`source_file` is
  the member manifest).
- Dependency tables read: `dependencies`, `dev-dependencies`,
  `build-dependencies` at top level and under every `[target.<spec>]`.
- `package = "real"` (in the member spec or the inherited workspace spec)
  makes the reported name `real`; the TOML key is only a local alias.
- Discovery walks with `os.walk`, pruning `ALWAYS_SKIP_DIRS | {"target"}`
  before descending, so nothing under any `target/` directory is read.

### Steps

1. Write the failing tests. In `tests/test_rust_deps_collector.py` add
   `import pytest` to the imports, then append:

   ```python
   def _read_text_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, Any]]:
       """Record (path, encoding) for every Path.read_text call."""
       seen: list[tuple[Path, Any]] = []
       original = Path.read_text

       def spy(self: Path, *args: Any, **kwargs: Any) -> str:
           seen.append((self, kwargs.get("encoding", args[0] if args else None)))
           return original(self, *args, **kwargs)

       monkeypatch.setattr(Path, "read_text", spy)
       return seen


   class TestCargoResolution:
       @patch("nfr_review.collectors.rust_deps.DepsDevClient")
       def test_workspace_inherited_dependency_resolves_from_root(
           self, mock_cls: MagicMock, tmp_path: Path
       ) -> None:
           (tmp_path / "Cargo.toml").write_text(
               '[workspace]\nmembers = ["crates/app"]\n\n'
               "[workspace.dependencies]\n"
               'serde = { version = "1.0.190", features = ["derive"] }\n'
               'json = { package = "serde_json", version = "1.0.108" }\n'
           )
           member = tmp_path / "crates" / "app"
           member.mkdir(parents=True)
           (member / "Cargo.toml").write_text(
               '[package]\nname = "app"\nversion = "0.1.0"\n\n'
               "[dependencies]\n"
               "serde = { workspace = true }\n"
               "json = { workspace = true }\n"
           )
           mock_cls.return_value.get_package_versions = _mock_get_versions()
           evidences = RustDepsCollector().collect(tmp_path, None)
           by_name = {d["name"]: d for d in evidences[0].payload["dependencies"]}
           assert set(by_name) == {"serde", "serde_json"}
           assert by_name["serde"]["declared_version"] == "1.0.190"
           assert by_name["serde_json"]["declared_version"] == "1.0.108"
           assert by_name["serde"]["source_file"] == "crates/app/Cargo.toml"

       @patch("nfr_review.collectors.rust_deps.DepsDevClient")
       def test_target_cfg_dependency_tables_parsed(
           self, mock_cls: MagicMock, tmp_path: Path
       ) -> None:
           (tmp_path / "Cargo.toml").write_text(
               '[package]\nname = "x"\nversion = "0.1.0"\n\n'
               "[target.'cfg(unix)'.dependencies]\n"
               'nix = "0.27"\n\n'
               "[target.'cfg(windows)'.dev-dependencies]\n"
               'winapi = { version = "0.3" }\n'
           )
           mock_cls.return_value.get_package_versions = _mock_get_versions()
           evidences = RustDepsCollector().collect(tmp_path, None)
           by_name = {d["name"]: d for d in evidences[0].payload["dependencies"]}
           assert by_name["nix"]["declared_version"] == "0.27"
           assert by_name["winapi"]["declared_version"] == "0.3"

       @patch("nfr_review.collectors.rust_deps.DepsDevClient")
       def test_package_rename_resolves_to_real_crate(
           self, mock_cls: MagicMock, tmp_path: Path
       ) -> None:
           (tmp_path / "Cargo.toml").write_text(
               '[package]\nname = "x"\nversion = "0.1.0"\n\n'
               "[dependencies]\n"
               'http1 = { package = "hyper", version = "0.14" }\n'
           )
           mock_cls.return_value.get_package_versions = _mock_get_versions()
           evidences = RustDepsCollector().collect(tmp_path, None)
           names = [d["name"] for d in evidences[0].payload["dependencies"]]
           assert names == ["hyper"]
           looked_up = [
               c[0][1] for c in mock_cls.return_value.get_package_versions.call_args_list
           ]
           assert looked_up == ["hyper"]

       @patch("nfr_review.collectors.rust_deps.DepsDevClient")
       def test_target_dir_is_never_read(
           self, mock_cls: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           (tmp_path / "Cargo.toml").write_text(
               '[package]\nname = "x"\nversion = "0.1.0"\n\n[dependencies]\nlog = "0.4"\n'
           )
           decoy = tmp_path / "target" / "package" / "vendored-0.1.0"
           decoy.mkdir(parents=True)
           (decoy / "Cargo.toml").write_text(
               '[package]\nname = "vendored"\nversion = "0.1.0"\n\n'
               '[dependencies]\nbogus-crate = "1"\n'
           )
           seen = _read_text_spy(monkeypatch)
           mock_cls.return_value.get_package_versions = _mock_get_versions()
           evidences = RustDepsCollector().collect(tmp_path, None)
           assert [d["name"] for d in evidences[0].payload["dependencies"]] == ["log"]
           assert evidences[0].payload["manifest_files_found"] == ["Cargo.toml"]
           read = [p.relative_to(tmp_path).parts for p, _ in seen]
           assert all("target" not in parts for parts in read)

       @patch("nfr_review.collectors.rust_deps.DepsDevClient")
       def test_manifest_read_as_utf8(
           self, mock_cls: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           (tmp_path / "Cargo.toml").write_text(
               '[package]\nname = "x"\nversion = "0.1.0"\ndescription = "café ✓"\n\n'
               '[dependencies]\nlog = "0.4"\n',
               encoding="utf-8",
           )
           seen = _read_text_spy(monkeypatch)
           mock_cls.return_value.get_package_versions = _mock_get_versions()
           RustDepsCollector().collect(tmp_path, None)
           cargo_reads = [enc for p, enc in seen if p.name == "Cargo.toml"]
           assert cargo_reads == ["utf-8"]
   ```

   `_mock_get_versions` returns a `MagicMock`, so `call_args_list` is
   available on it in `test_package_rename_resolves_to_real_crate`.

2. Run them and see them fail:

   ```
   .venv/bin/python -m pytest tests/test_rust_deps_collector.py::TestCargoResolution -q
   ```

   Expected: workspace test fails (no evidence → `IndexError`, the member's
   specs have no `version`), target-cfg test fails (`IndexError`), rename test
   fails (`["http1"]`), target-dir test fails (`bogus-crate` reported and a
   `target` path read), utf-8 test fails (`[None]`).

3. Implement in `src/nfr_review/collectors/rust_deps.py`:

   1. Imports: add `import os`, `from collections.abc import Iterator`, and
      `ALWAYS_SKIP_DIRS` to the existing `nfr_review.path_filter` import. Add
      `_PRUNE_DIRS = ALWAYS_SKIP_DIRS | {"target"}`.
   2. Add:

      ```python
      def _find_cargo_tomls(repo_path: Path) -> list[Path]:
          """Every Cargo.toml under *repo_path*, never descending into build output."""
          found: list[Path] = []
          for dirpath, dirnames, filenames in os.walk(repo_path):
              dirnames[:] = [d for d in dirnames if d not in _PRUNE_DIRS]
              if "Cargo.toml" in filenames:
                  found.append(Path(dirpath) / "Cargo.toml")
          return sorted(found)


      def _load_cargo_toml(path: Path) -> dict[str, Any] | None:
          try:
              return tomllib.loads(path.read_text(encoding="utf-8"))
          except Exception:  # noqa: BLE001
              logger.debug("Failed to parse %s", path)
              return None


      def _iter_dep_tables(data: dict[str, Any]) -> Iterator[dict[str, Any]]:
          """Top-level dependency tables, then the same tables under each [target.<spec>]."""
          sections: list[Any] = [data]
          target = data.get("target")
          if isinstance(target, dict):
              sections.extend(target.values())
          for section in sections:
              if not isinstance(section, dict):
                  continue
              for table_name in _DEP_TABLES:
                  table = section.get(table_name)
                  if isinstance(table, dict):
                      yield table


      def _workspace_dependencies(
          manifest: Path, repo_path: Path, loaded: dict[Path, dict[str, Any] | None]
      ) -> dict[str, Any]:
          """[workspace.dependencies] of the nearest ancestor workspace manifest."""
          directory = manifest.parent
          while True:
              data = loaded.get(directory / "Cargo.toml")
              if data is not None:
                  workspace = data.get("workspace")
                  if isinstance(workspace, dict):
                      deps = workspace.get("dependencies", {})
                      return deps if isinstance(deps, dict) else {}
              if directory == repo_path or directory.parent == directory:
                  return {}
              directory = directory.parent


      def _resolve_dep(
          key: str, spec: Any, workspace_deps: dict[str, Any]
      ) -> tuple[str, str] | None:
          """(crate name, declared version) for one dependency entry, or None
          for git/path-only deps and unresolvable workspace references."""
          if isinstance(spec, dict) and spec.get("workspace") is True:
              spec = workspace_deps.get(key)
          version = _dep_version(spec)
          if version is None:
              return None
          package = spec.get("package") if isinstance(spec, dict) else None
          return (package if isinstance(package, str) else key), version


      def _cargo_deps(data: dict[str, Any], workspace_deps: dict[str, Any]) -> list[tuple[str, str]]:
          deps: list[tuple[str, str]] = []
          for table in _iter_dep_tables(data):
              for key, spec in table.items():
                  resolved = _resolve_dep(key, spec, workspace_deps)
                  if resolved is not None:
                      deps.append(resolved)
          return deps
      ```

      Delete `_parse_cargo_toml`.
   3. In `RustDepsCollector.collect`, replace the
      `for cargo_path in sorted(repo_path.rglob("Cargo.toml")):` loop with:

      ```python
      manifests = _find_cargo_tomls(repo_path)
      loaded = {path: _load_cargo_toml(path) for path in manifests}
      for cargo_path in manifests:
          rel = cargo_path.relative_to(repo_path).as_posix()
          if should_exclude_path(
              rel, exclude_test_paths=exclude_test, exclude_patterns=exclude_pats
          ):
              continue
          data = loaded[cargo_path]
          if data is None:
              continue
          parsed = _cargo_deps(data, _workspace_dependencies(cargo_path, repo_path, loaded))
          if not parsed:
              continue
          manifest_files.append(rel)
          raw_deps.extend((rel, name, version) for name, version in parsed)
      ```

      Excluded manifests are still loaded so a member can inherit from an
      excluded workspace root; they are never reported.
   4. Update the module docstring to: "Rust dependency collector — parses
      Cargo.toml dependency tables (including `[target.<cfg>]` tables,
      workspace-inherited and renamed dependencies), enriches each dependency
      with version metadata from deps.dev. Build output under `target/` is
      never read."
   5. Run `.venv/bin/ruff format src/nfr_review/collectors/rust_deps.py tests/test_rust_deps_collector.py`.

4. Run and see them pass, with the rest of the module:

   ```
   .venv/bin/python -m pytest tests/test_rust_deps_collector.py tests/test_rust_integration.py -q
   ```

5. Run `regression`. Corpora with Cargo workspaces or renamed deps may gain
   dependency findings. Refresh as in the conventions, then confirm every
   changed snapshot line comes from the deps collector:

   ```
   git diff -U0 -- 'tests/regression/snapshots/*.jsonl' | grep '^[-+]{' | grep -vc '"collector_name": "rust-deps"'
   ```

   prints `0`.

6. Commit:

   ```
   git add src/nfr_review/collectors/rust_deps.py tests/test_rust_deps_collector.py tests/regression/snapshots/
   git commit -m "fix(rust-deps): resolve workspace, target-cfg and renamed deps; skip target/

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S02
   Rows: R2"
   ```

**Check:** `regression` passes (and `format`).

---

## Task 5 — Complete Rust rule descriptions and regenerated `rules.json`

**Rows:** R3

**Files**

- Modify `src/nfr_review/rule_metadata.py`
- Modify `tests/test_rule_metadata.py`
- Regenerate `site/src/data/rules.json`

**Consumes:** `RULE_METADATA` entries `rust-unwrap-expect`,
`rust-blocking-in-async`, `rust-unbounded-spawn-in-loop`; the
`list-rules --format json` command used by `.github/workflows/deploy-site.yml`
(step "Generate rules.json") and by commit `67cfc95`.
**Produces:** complete descriptions, `test_rust_rule_descriptions_are_complete_sentences`,
regenerated `site/src/data/rules.json`.

The test is scoped to `rust-*` rules: eight non-Rust descriptions on `main`
also end in a dangling word (e.g. `python-broad-except-silent` "…logging or.")
and are outside this slice.

### Steps

1. Write the failing test. Append to `tests/test_rule_metadata.py`:

   ```python
   _DANGLING_WORDS = frozenset(
       {
           "a",
           "an",
           "and",
           "as",
           "at",
           "by",
           "for",
           "from",
           "in",
           "inside",
           "instead",
           "into",
           "of",
           "on",
           "or",
           "than",
           "that",
           "the",
           "to",
           "via",
           "which",
           "with",
           "without",
       }
   )


   def test_rust_rule_descriptions_are_complete_sentences() -> None:
       """Rust rule descriptions must not be cut off mid-sentence."""
       rust = {k: m for k, m in RULE_METADATA.items() if k.startswith("rust-")}
       assert len(rust) == 5
       for rule_id, meta in rust.items():
           assert meta.description.endswith("."), rule_id
           last_word = meta.description.rstrip(".").split()[-1].lower()
           assert last_word not in _DANGLING_WORDS, (
               f"{rule_id}: description ends in dangling word {last_word!r}"
           )
   ```

   (ruff format may reflow the frozenset to one element per line; keep its
   output.)

2. Run it and see it fail:

   ```
   .venv/bin/python -m pytest tests/test_rule_metadata.py::test_rust_rule_descriptions_are_complete_sentences -q
   ```

   Fails on the first of `rust-unwrap-expect` ("of"),
   `rust-blocking-in-async` ("inside"), `rust-unbounded-spawn-in-loop` ("the").

3. Implement in `src/nfr_review/rule_metadata.py` — replace the three
   description strings:
   - `rust-unwrap-expect`: `"Flags .unwrap()/.expect() calls outside test code that panic instead of propagating the error."`
   - `rust-blocking-in-async`: `"Flags blocking calls (thread::sleep, std::fs, a sync lock with no .await) inside async code, where they block the executor thread."`
   - `rust-unbounded-spawn-in-loop`: `"Flags tokio::spawn calls inside a loop with nothing joining or bounding the spawned tasks."`

   Split each across adjacent string literals so lines stay within 95
   columns, then run
   `.venv/bin/ruff format src/nfr_review/rule_metadata.py tests/test_rule_metadata.py`.

4. Run and see it pass, with the module:

   ```
   .venv/bin/python -m pytest tests/test_rule_metadata.py -q
   ```

5. Regenerate the site data and check the diff:

   ```
   .venv/bin/python -m nfr_review.cli list-rules --format json > site/src/data/rules.json
   git diff --stat -- site/src/data/rules.json
   git diff -U0 -- site/src/data/rules.json | grep '^[-+] ' | grep -vc '"description"'
   ```

   The stat shows only `site/src/data/rules.json` with 3 lines changed each
   way, and the last command prints `0` (only `description` lines changed;
   the command reproduced the committed file byte-for-byte before this
   task).

6. Commit:

   ```
   git add src/nfr_review/rule_metadata.py tests/test_rule_metadata.py site/src/data/rules.json
   git commit -m "docs(rules): complete the truncated Rust rule descriptions

   Plan: docs/plans/pr255-remediation/ledger.md
   Slice: M001/S02
   Rows: R3"
   ```

**Check:** `unit` passes (and `format`). Then run the slice's `gate` on the
branch head.

---

## Self-review

**DoD coverage**

| DoD item | Task | Named test(s) |
|---|---|---|
| io `.write(..)`/`.read(..)` with args not a lock call | 1 | `TestLockCallArity::test_io_write_with_args_is_not_a_lock_unwrap`, `::test_io_read_write_with_args_not_sync_lock_in_async` |
| closure in async fn not reported; `async {}` in sync fn reported | 1 | `TestAsyncContextBoundary::test_blocking_call_in_closure_in_async_fn_not_reported`, `::test_sleep_in_async_block_in_sync_fn_reported` |
| exact `#[test]`/`#[cfg(test)]`/`mod tests`; `mod attestation` scanned | 2 | `TestTestCodeDetection::*` (7 cases) |
| imported paths recognised | 3 | `TestImportedPaths::test_imported_client_new`, `::test_imported_spawn_in_loop`, `::test_fully_qualified_tokio_task_spawn`, plus builder/alias/grouped cases |
| unwrap summaries single-line and bounded | 2 | `TestRustUnwrapExpectRule::test_multiline_receiver_summary_is_single_line`, `::test_long_receiver_summary_is_capped_at_60_chars` |
| mutex rule skips test code | 2 | `TestMutexLockUnwrapInTest::test_mutex_lock_unwrap_in_test_module_marked`, `TestRustMutexLockUnwrapRule::test_skips_test_call` |
| workspace / target-cfg / renamed deps; nothing under `target/` parsed | 4 | `TestCargoResolution::*` (5 cases incl. utf-8 read) |
| three Rust descriptions complete | 5 | `test_rust_rule_descriptions_are_complete_sentences` |
| each outcome locked by a named test | 1–5 | the table above |

**Row coverage**

- R1 → Tasks 1, 2, 3. Verification ("one case per sub-item … feeding the
  snippet from the input") is produced by Task 1 step 1 (arity:
  `out.write(b"x").unwrap()`; closure: `spawn_blocking(move || …)`;
  async-block sleep), Task 2 step 1 (`mod attestation`, `latest`; unbounded
  summary; mutex `in_test`) and Task 3 step 1 (`use reqwest::Client;
  Client::new()`, imported `spawn`, `tokio::task::spawn`).
- R2 → Task 4. Verification (workspace fixture, `[target.'cfg(..)'.dependencies]`
  table, `package =` rename, `target/` decoy) is produced by Task 4 step 1.
- R3 → Task 5. Verification (dangling-word test; `rules.json` regenerated) is
  produced by Task 5 steps 1 and 5.

**Placeholder scan:** no deferred or unspecified steps; every helper named is either existing
(`_is_inside_loop`, `_is_async_function_item`, `_extract_unwrap_expect_and_mutex`,
`_extract_http_client_builds`, `_extract_async_blocking_calls`,
`_extract_spawn_calls`, `_dep_version`, `_enrich`, `should_exclude_path`,
`compile_exclude_patterns`, `ALWAYS_SKIP_DIRS`, `find_nodes`, `text`,
`_mock_get_versions`, `_empty_payload`, `_evidence`) or defined in a task
(`_payload_for_source`, `_lock_method_name`, `_enclosing_function_name`,
`_TEST_MOD_NAMES`, `_preceding_attributes`, `_is_test_attribute`,
`_short_receiver`, `_RECEIVER_MAX`, `_SPAWN_PATHS`, `_collect_use_aliases`,
`_build_use_aliases`, `_resolve_path`, `_chain_root_callee`, `_PRUNE_DIRS`,
`_find_cargo_tomls`, `_load_cargo_toml`, `_iter_dep_tables`,
`_workspace_dependencies`, `_resolve_dep`, `_cargo_deps`, `_read_text_spy`,
`_TEST_DETECTION_SRC`, `_in_test_by_line`, `_DANGLING_WORDS`).

**Out of scope, noted:** the existing
`test_nested_cargo_toml_in_workspace_member` assertion's
`.replace("\\", "/")` belongs to W2 (M001/S05) and is left untouched here.
