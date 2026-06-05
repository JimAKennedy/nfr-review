# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the nodejs-ast collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "NodejsAstFilePayload",
    "NodejsAwaitExpression",
    "NodejsCallbackPattern",
    "NodejsCatchBlock",
    "NodejsFunction",
    "NodejsLogStatement",
    "NodejsPromiseChain",
    "NodejsSyncCall",
]


class NodejsCatchBlock(BasePayload):
    caught_type: str
    rethrows: bool
    has_logging: bool
    line: int
    file: str


class NodejsLogStatement(BasePayload):
    method: str
    line: int
    file: str


class NodejsFunction(BasePayload):
    name: str
    line: int
    is_async: bool
    kind: str


class NodejsAwaitExpression(BasePayload):
    expression: str
    line: int
    file: str


class NodejsPromiseChain(BasePayload):
    expression: str
    has_catch: bool
    line: int
    file: str


class NodejsSyncCall(BasePayload):
    method: str
    line: int
    file: str


class NodejsCallbackPattern(BasePayload):
    function_name: str
    callback_param: str
    checks_error: bool
    line: int
    file: str


class NodejsAstFilePayload(BasePayload):
    file_path: str
    catch_blocks: list[NodejsCatchBlock]
    log_statements: list[NodejsLogStatement]
    functions: list[NodejsFunction]
    await_expressions: list[NodejsAwaitExpression]
    promise_chains: list[NodejsPromiseChain]
    sync_calls: list[NodejsSyncCall]
    callback_patterns: list[NodejsCallbackPattern]
