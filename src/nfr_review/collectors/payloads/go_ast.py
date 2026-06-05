# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the go-ast collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "GoAstFilePayload",
    "GoBaseClass",
    "GoCatchBlock",
    "GoDeferStatement",
    "GoErrorAssignment",
    "GoField",
    "GoFunction",
    "GoGoroutineLaunch",
    "GoHttpCall",
    "GoLogStatement",
    "GoMethod",
    "GoParameter",
    "GoStruct",
]


class GoParameter(BasePayload):
    name: str
    type: str


class GoBaseClass(BasePayload):
    name: str
    access: str


class GoField(BasePayload):
    name: str
    type: str
    access: str
    line: int


class GoMethod(BasePayload):
    name: str
    return_type: str
    access: str
    is_virtual: bool
    is_pure_virtual: bool
    line: int
    parameters: list[GoParameter]


class GoStruct(BasePayload):
    name: str
    line: int
    is_struct: bool
    is_abstract: bool
    is_interface: bool
    base_classes: list[GoBaseClass]
    fields: list[GoField]
    methods: list[GoMethod]
    namespace: str
    outer_class: str


class GoCatchBlock(BasePayload):
    caught_type: str
    rethrows: bool
    line: int
    file: str


class GoLogStatement(BasePayload):
    method: str
    line: int
    file: str


class GoFunction(BasePayload):
    name: str
    line: int
    receiver: str


class GoErrorAssignment(BasePayload):
    call: str
    error_ignored: bool
    line: int
    file: str


class GoGoroutineLaunch(BasePayload):
    expression: str
    line: int
    file: str


class GoHttpCall(BasePayload):
    call: str
    has_timeout: bool
    line: int
    file: str


class GoDeferStatement(BasePayload):
    expression: str
    in_loop: bool
    line: int
    file: str


class GoAstFilePayload(BasePayload):
    file_path: str
    package: str
    structs: list[GoStruct]
    catch_blocks: list[GoCatchBlock]
    log_statements: list[GoLogStatement]
    functions: list[GoFunction]
    error_assignments: list[GoErrorAssignment]
    goroutine_launches: list[GoGoroutineLaunch]
    http_calls: list[GoHttpCall]
    defer_statements: list[GoDeferStatement]
