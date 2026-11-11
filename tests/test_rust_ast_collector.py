"""Tests for RustAstCollector — registration, extraction, edge cases."""

from __future__ import annotations

import textwrap
from pathlib import Path

from nfr_review.collectors.rust_ast import RustAstCollector
from nfr_review.registry import collector_registry

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rust-sample-repo"


def _payload_for(filename: str):
    collector = RustAstCollector()
    evidences = collector.collect(FIXTURE_DIR, config=None)
    for ev in evidences:
        if ev.payload.file_path == filename:
            return ev.payload
    raise AssertionError(f"no evidence for {filename}")


def _payload_for_source(tmp_path: Path, source: str):
    (tmp_path / "lib.rs").write_text(textwrap.dedent(source), encoding="utf-8")
    evidences = RustAstCollector().collect(tmp_path, config=None)
    assert len(evidences) == 1
    return evidences[0].payload


class TestRegistration:
    def test_registered_in_collector_registry(self) -> None:
        assert "rust-ast" in collector_registry

    def test_collector_name_and_kind(self) -> None:
        collector = RustAstCollector()
        assert collector.name == "rust-ast"
        assert collector.evidence_kind == "rust-ast-file"
        assert collector.file_extensions == (".rs",)


class TestCollectOnFixtures:
    def test_collects_every_rs_file(self) -> None:
        collector = RustAstCollector()
        evidences = collector.collect(FIXTURE_DIR, config=None)
        names = {ev.payload.file_path for ev in evidences}
        assert names == {
            "bad_unwrap.rs",
            "bad_mutex.rs",
            "bad_http.rs",
            "bad_async_blocking.rs",
            "bad_spawn.rs",
            "good_code.rs",
        }

    def test_evidence_kind(self) -> None:
        collector = RustAstCollector()
        evidences = collector.collect(FIXTURE_DIR, config=None)
        assert all(ev.kind == "rust-ast-file" for ev in evidences)
        assert all(ev.collector_name == "rust-ast" for ev in evidences)


class TestUnwrapExpectExtraction:
    def test_flags_unwrap_and_expect_outside_test(self) -> None:
        payload = _payload_for("bad_unwrap.rs")
        non_test = [c for c in payload.unwrap_expect_calls if not c.in_test]
        methods = {c.method for c in non_test}
        assert methods == {"unwrap", "expect"}
        assert len(non_test) == 2

    def test_test_module_unwrap_marked_in_test(self) -> None:
        payload = _payload_for("bad_unwrap.rs")
        in_test = [c for c in payload.unwrap_expect_calls if c.in_test]
        assert len(in_test) == 1

    def test_good_code_has_no_unwrap_expect(self) -> None:
        payload = _payload_for("good_code.rs")
        assert payload.unwrap_expect_calls == []


class TestMutexLockUnwrapExtraction:
    def test_flags_lock_read_write_unwrap(self) -> None:
        payload = _payload_for("bad_mutex.rs")
        methods = {c.lock_method for c in payload.mutex_lock_unwraps}
        assert methods == {"lock", "read", "write"}
        assert len(payload.mutex_lock_unwraps) == 3

    def test_excluded_from_general_unwrap_list(self) -> None:
        """.lock().unwrap() is classified as mutex-lock-unwrap, not double
        counted in unwrap_expect_calls."""
        payload = _payload_for("bad_mutex.rs")
        assert payload.unwrap_expect_calls == []

    def test_good_code_map_err_not_flagged(self) -> None:
        payload = _payload_for("good_code.rs")
        assert payload.mutex_lock_unwraps == []


class TestHttpClientBuildExtraction:
    def test_client_new_has_no_timeout(self) -> None:
        payload = _payload_for("bad_http.rs")
        client_new = [
            c for c in payload.http_client_builds if c.call == "reqwest::Client::new"
        ]
        assert len(client_new) == 1
        assert client_new[0].has_timeout is False

    def test_builder_without_timeout_detected(self) -> None:
        payload = _payload_for("bad_http.rs")
        builders = [c for c in payload.http_client_builds if "builder" in c.call]
        assert len(builders) == 1
        assert builders[0].has_timeout is False

    def test_good_code_builder_with_timeout(self) -> None:
        payload = _payload_for("good_code.rs")
        assert len(payload.http_client_builds) == 1
        assert payload.http_client_builds[0].has_timeout is True


class TestAsyncBlockingCallExtraction:
    def test_thread_sleep_and_fs_flagged(self) -> None:
        payload = _payload_for("bad_async_blocking.rs")
        kinds = {c.kind for c in payload.async_blocking_calls}
        assert kinds == {"thread::sleep", "fs"}

    def test_lock_without_await_flagged_inside_async(self) -> None:
        payload = _payload_for("bad_http.rs")
        assert payload.async_blocking_calls == []  # no sync locks in bad_http.rs

    def test_good_code_no_blocking_calls(self) -> None:
        payload = _payload_for("good_code.rs")
        assert payload.async_blocking_calls == []

    def test_non_async_fn_not_scanned(self) -> None:
        payload = _payload_for("bad_mutex.rs")
        # bump()/read_config()/write_config() are not async — no blocking-call
        # findings should come from a non-async function.
        assert payload.async_blocking_calls == []


class TestSpawnCallExtraction:
    def test_spawn_in_loop_flagged(self) -> None:
        payload = _payload_for("bad_spawn.rs")
        in_loop = [c for c in payload.spawn_calls if c.in_loop]
        assert len(in_loop) == 1

    def test_spawn_outside_loop_not_flagged(self) -> None:
        payload = _payload_for("bad_spawn.rs")
        not_in_loop = [c for c in payload.spawn_calls if not c.in_loop]
        assert len(not_in_loop) == 1

    def test_good_code_spawn_not_in_loop(self) -> None:
        payload = _payload_for("good_code.rs")
        assert len(payload.spawn_calls) == 1
        assert payload.spawn_calls[0].in_loop is False


class TestGoodCode:
    def test_produces_no_evidence_of_any_footgun(self) -> None:
        payload = _payload_for("good_code.rs")
        assert payload.unwrap_expect_calls == []
        assert payload.mutex_lock_unwraps == []
        assert payload.async_blocking_calls == []
        assert all(c.has_timeout for c in payload.http_client_builds)
        assert all(not c.in_loop for c in payload.spawn_calls)


class TestEdgeCases:
    def test_empty_repo_returns_no_evidence(self, tmp_path: Path) -> None:
        collector = RustAstCollector()
        evidences = collector.collect(tmp_path, config=None)
        assert evidences == []

    def test_unparseable_file_does_not_crash_collection(self, tmp_path: Path) -> None:
        (tmp_path / "broken.rs").write_text("fn broken( {{{ not rust")
        collector = RustAstCollector()
        evidences = collector.collect(tmp_path, config=None)
        # tree-sitter is error-tolerant; collection should not raise.
        assert isinstance(evidences, list)

    def test_struct_and_trait_extraction_shape(self) -> None:
        collector = RustAstCollector()
        evidences = collector.collect(
            Path(__file__).parent / "fixtures" / "rust-class-diagram", config=None
        )
        payload = evidences[0].payload
        by_name = {s.name: s for s in payload.structs}
        assert "Circle" in by_name
        assert "Shape" in by_name
        assert by_name["Shape"].is_interface is True
        assert by_name["Circle"].is_interface is False
        assert "Shape" in [b.name for b in by_name["Circle"].base_classes]


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
