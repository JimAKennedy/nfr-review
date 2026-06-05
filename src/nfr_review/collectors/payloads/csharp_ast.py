# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the csharp-ast collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "CSharpAstFilePayload",
    "CSharpAwaitExpression",
    "CSharpBlockingCall",
    "CSharpCatchBlock",
    "CSharpLogStatement",
    "CSharpMethod",
    "CSharpObjectCreation",
]


class CSharpCatchBlock(BasePayload):
    caught_type: str
    rethrows: bool
    has_logging: bool
    line: int
    file: str


class CSharpLogStatement(BasePayload):
    method: str
    line: int
    file: str


class CSharpMethod(BasePayload):
    name: str
    line: int
    is_async: bool
    return_type: str
    modifiers: list[str]


class CSharpAwaitExpression(BasePayload):
    expression: str
    has_configure_await: bool
    line: int
    file: str


class CSharpObjectCreation(BasePayload):
    type_name: str
    in_using: bool
    line: int
    file: str


class CSharpBlockingCall(BasePayload):
    expression: str
    call_type: str
    line: int
    file: str


class CSharpAstFilePayload(BasePayload):
    file_path: str
    catch_blocks: list[CSharpCatchBlock]
    log_statements: list[CSharpLogStatement]
    methods: list[CSharpMethod]
    await_expressions: list[CSharpAwaitExpression]
    object_creations: list[CSharpObjectCreation]
    blocking_calls: list[CSharpBlockingCall]
