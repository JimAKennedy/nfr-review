# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the cpp-ast collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "CppAstFilePayload",
    "CppBaseClass",
    "CppCatchBlock",
    "CppClassInfo",
    "CppDeleteExpression",
    "CppField",
    "CppFunction",
    "CppInclude",
    "CppMallocCall",
    "CppMethod",
    "CppNewExpression",
    "CppParameter",
    "CppRawPointer",
    "CppSmartPointer",
    "CppTypeAlias",
]


class CppParameter(BasePayload):
    name: str
    type: str


class CppBaseClass(BasePayload):
    name: str
    access: str


class CppField(BasePayload):
    name: str
    type: str
    access: str
    line: int


class CppMethod(BasePayload):
    name: str
    return_type: str
    access: str
    is_virtual: bool
    is_pure_virtual: bool
    line: int
    parameters: list[CppParameter]


class CppClassInfo(BasePayload):
    name: str
    line: int
    has_destructor: bool
    is_struct: bool
    base_classes: list[CppBaseClass]
    methods: list[CppMethod]
    fields: list[CppField]
    is_abstract: bool
    namespace: str
    friends: list[str]
    outer_class: str


class CppFunction(BasePayload):
    name: str
    return_type: str
    line: int
    is_noexcept: bool


class CppTypeAlias(BasePayload):
    alias: str
    target: str
    line: int
    kind: str


class CppInclude(BasePayload):
    path: str
    is_system: bool
    line: int


class CppNewExpression(BasePayload):
    line: int
    file: str
    expression: str
    parent_call: str
    line_comment: str


class CppDeleteExpression(BasePayload):
    line: int
    file: str
    expression: str


class CppSmartPointer(BasePayload):
    kind: str
    line: int
    file: str


class CppRawPointer(BasePayload):
    name: str
    line: int
    file: str


class CppMallocCall(BasePayload):
    call: str
    line: int
    file: str


class CppCatchBlock(BasePayload):
    caught_type: str
    rethrows: bool
    line: int
    file: str


class CppAstFilePayload(BasePayload):
    file_path: str
    functions: list[CppFunction]
    classes: list[CppClassInfo]
    namespaces: list[str]
    type_aliases: list[CppTypeAlias]
    includes: list[CppInclude]
    new_expressions: list[CppNewExpression]
    delete_expressions: list[CppDeleteExpression]
    smart_pointers: list[CppSmartPointer]
    raw_pointers: list[CppRawPointer]
    malloc_calls: list[CppMallocCall]
    catch_blocks: list[CppCatchBlock]
    has_pragma_once: bool
    has_include_guard: bool
    log_statements: list[dict] = []
