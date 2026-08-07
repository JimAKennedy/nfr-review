# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the rust-ast collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "RustAsyncBlockingCall",
    "RustAstFilePayload",
    "RustBaseClass",
    "RustField",
    "RustFunction",
    "RustHttpClientBuild",
    "RustMethod",
    "RustMutexLockUnwrap",
    "RustParameter",
    "RustSpawnCall",
    "RustStruct",
    "RustUnwrapExpectCall",
]


class RustParameter(BasePayload):
    name: str
    type: str


class RustBaseClass(BasePayload):
    name: str
    access: str


class RustField(BasePayload):
    name: str
    type: str
    access: str
    line: int


class RustMethod(BasePayload):
    name: str
    return_type: str
    access: str
    is_virtual: bool
    is_pure_virtual: bool
    line: int
    parameters: list[RustParameter]


class RustStruct(BasePayload):
    """A struct, enum, or trait — modeled uniformly for class-diagram enrichment."""

    name: str
    line: int
    is_struct: bool
    is_abstract: bool
    is_interface: bool
    base_classes: list[RustBaseClass]
    fields: list[RustField]
    methods: list[RustMethod]
    namespace: str
    outer_class: str


class RustFunction(BasePayload):
    name: str
    line: int
    is_async: bool


class RustUnwrapExpectCall(BasePayload):
    method: str
    receiver: str
    line: int
    file: str
    in_test: bool


class RustMutexLockUnwrap(BasePayload):
    lock_method: str
    line: int
    file: str


class RustHttpClientBuild(BasePayload):
    call: str
    has_timeout: bool
    line: int
    file: str


class RustAsyncBlockingCall(BasePayload):
    function_name: str
    call: str
    kind: str
    line: int
    file: str


class RustSpawnCall(BasePayload):
    line: int
    file: str
    in_loop: bool


class RustAstFilePayload(BasePayload):
    file_path: str
    structs: list[RustStruct]
    functions: list[RustFunction]
    unwrap_expect_calls: list[RustUnwrapExpectCall]
    mutex_lock_unwraps: list[RustMutexLockUnwrap]
    http_client_builds: list[RustHttpClientBuild]
    async_blocking_calls: list[RustAsyncBlockingCall]
    spawn_calls: list[RustSpawnCall]
