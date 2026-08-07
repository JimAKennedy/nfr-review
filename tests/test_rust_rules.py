"""Direct rule unit tests — construct Evidence/payload, call evaluate(), assert findings."""

from __future__ import annotations

from nfr_review.collectors.payloads.rust_ast import (
    RustAstFilePayload,
    RustAsyncBlockingCall,
    RustHttpClientBuild,
    RustMutexLockUnwrap,
    RustSpawnCall,
    RustUnwrapExpectCall,
)
from nfr_review.models import Evidence
from nfr_review.rules.rust_blocking_in_async import RustBlockingInAsyncRule
from nfr_review.rules.rust_http_no_timeout import RustHttpNoTimeoutRule
from nfr_review.rules.rust_mutex_lock_unwrap import RustMutexLockUnwrapRule
from nfr_review.rules.rust_unbounded_spawn_in_loop import RustUnboundedSpawnInLoopRule
from nfr_review.rules.rust_unwrap_expect import RustUnwrapExpectRule


def _empty_payload(**overrides) -> RustAstFilePayload:
    base = dict(
        file_path="lib.rs",
        structs=[],
        functions=[],
        unwrap_expect_calls=[],
        mutex_lock_unwraps=[],
        http_client_builds=[],
        async_blocking_calls=[],
        spawn_calls=[],
    )
    base.update(overrides)
    return RustAstFilePayload(**base)


def _evidence(payload: RustAstFilePayload) -> Evidence:
    return Evidence(
        collector_name="rust-ast",
        collector_version="0.1.0",
        locator=payload.file_path,
        kind="rust-ast-file",
        payload=payload,
    )


class TestRustUnwrapExpectRule:
    def test_flags_non_test_call(self) -> None:
        payload = _empty_payload(
            unwrap_expect_calls=[
                RustUnwrapExpectCall(
                    method="unwrap", receiver="x", line=5, file="lib.rs", in_test=False
                )
            ]
        )
        result = RustUnwrapExpectRule().evaluate([_evidence(payload)], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "lib.rs:5" in amber[0].evidence_locator

    def test_skips_test_call(self) -> None:
        payload = _empty_payload(
            unwrap_expect_calls=[
                RustUnwrapExpectCall(
                    method="unwrap", receiver="x", line=5, file="lib.rs", in_test=True
                )
            ]
        )
        result = RustUnwrapExpectRule().evaluate([_evidence(payload)], None)
        assert all(f.rag == "green" for f in result.findings)

    def test_all_clear_on_empty(self) -> None:
        result = RustUnwrapExpectRule().evaluate([_evidence(_empty_payload())], None)
        assert all(f.rag == "green" for f in result.findings)


class TestRustMutexLockUnwrapRule:
    def test_flags_lock_unwrap(self) -> None:
        payload = _empty_payload(
            mutex_lock_unwraps=[
                RustMutexLockUnwrap(lock_method="lock", line=10, file="lib.rs")
            ]
        )
        result = RustMutexLockUnwrapRule().evaluate([_evidence(payload)], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert amber[0].severity == "high"


class TestRustHttpNoTimeoutRule:
    def test_client_new_is_red(self) -> None:
        payload = _empty_payload(
            http_client_builds=[
                RustHttpClientBuild(
                    call="reqwest::Client::new", has_timeout=False, line=3, file="lib.rs"
                )
            ]
        )
        result = RustHttpNoTimeoutRule().evaluate([_evidence(payload)], None)
        red = [f for f in result.findings if f.rag == "red"]
        assert len(red) == 1

    def test_builder_without_timeout_is_amber(self) -> None:
        payload = _empty_payload(
            http_client_builds=[
                RustHttpClientBuild(
                    call="reqwest::Client::builder()...build()",
                    has_timeout=False,
                    line=3,
                    file="lib.rs",
                )
            ]
        )
        result = RustHttpNoTimeoutRule().evaluate([_evidence(payload)], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1

    def test_with_timeout_not_flagged(self) -> None:
        payload = _empty_payload(
            http_client_builds=[
                RustHttpClientBuild(
                    call="reqwest::Client::builder()...build()",
                    has_timeout=True,
                    line=3,
                    file="lib.rs",
                )
            ]
        )
        result = RustHttpNoTimeoutRule().evaluate([_evidence(payload)], None)
        assert all(f.rag == "green" for f in result.findings)


class TestRustBlockingInAsyncRule:
    def test_flags_blocking_call(self) -> None:
        payload = _empty_payload(
            async_blocking_calls=[
                RustAsyncBlockingCall(
                    function_name="fetch",
                    call="std::thread::sleep",
                    kind="thread::sleep",
                    line=4,
                    file="lib.rs",
                )
            ]
        )
        result = RustBlockingInAsyncRule().evaluate([_evidence(payload)], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "fetch" in amber[0].summary


class TestRustUnboundedSpawnInLoopRule:
    def test_flags_spawn_in_loop(self) -> None:
        payload = _empty_payload(
            spawn_calls=[RustSpawnCall(line=6, file="lib.rs", in_loop=True)]
        )
        result = RustUnboundedSpawnInLoopRule().evaluate([_evidence(payload)], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1

    def test_spawn_outside_loop_not_flagged(self) -> None:
        payload = _empty_payload(
            spawn_calls=[RustSpawnCall(line=6, file="lib.rs", in_loop=False)]
        )
        result = RustUnboundedSpawnInLoopRule().evaluate([_evidence(payload)], None)
        assert all(f.rag == "green" for f in result.findings)


class TestRequiredTechGating:
    """Every rust rule sets required_tech=["rust"] explicitly, per
    docs/adding-language-support.md's standard."""

    def test_all_five_rules_declare_required_tech(self) -> None:
        for rule_cls in (
            RustUnwrapExpectRule,
            RustMutexLockUnwrapRule,
            RustHttpNoTimeoutRule,
            RustBlockingInAsyncRule,
            RustUnboundedSpawnInLoopRule,
        ):
            assert rule_cls.required_tech == ["rust"]
