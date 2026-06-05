# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the python-ast collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "PythonAstFilePayload",
    "PythonAsyncCall",
    "PythonBaseClass",
    "PythonCatchBlock",
    "PythonClassInfo",
    "PythonDefaultArg",
    "PythonField",
    "PythonFunction",
    "PythonImport",
    "PythonLogStatement",
    "PythonMethod",
    "PythonParameter",
]


class PythonParameter(BasePayload):
    name: str
    type: str


class PythonBaseClass(BasePayload):
    name: str
    access: str


class PythonField(BasePayload):
    name: str
    type: str
    access: str
    line: int


class PythonMethod(BasePayload):
    name: str
    return_type: str
    access: str
    is_virtual: bool
    is_pure_virtual: bool
    line: int
    parameters: list[PythonParameter]
    decorators: list[str]


class PythonClassInfo(BasePayload):
    name: str
    line: int
    is_abstract: bool
    is_interface: bool
    base_classes: list[PythonBaseClass]
    fields: list[PythonField]
    methods: list[PythonMethod]
    namespace: str
    outer_class: str


class PythonCatchBlock(BasePayload):
    caught_type: str
    rethrows: bool
    has_logging: bool
    line: int
    file: str


class PythonLogStatement(BasePayload):
    method: str
    line: int
    file: str


class PythonDefaultArg(BasePayload):
    name: str
    default_type: str
    line: int


class PythonFunction(BasePayload):
    name: str
    line: int
    is_async: bool
    decorators: list[str]
    default_args: list[PythonDefaultArg]


class PythonImport(BasePayload):
    module: str
    names: list[str]
    is_star: bool
    line: int


class PythonAsyncCall(BasePayload):
    call: str
    line: int
    stored: bool


class PythonAstFilePayload(BasePayload):
    file_path: str
    module_path: str
    classes: list[PythonClassInfo]
    catch_blocks: list[PythonCatchBlock]
    log_statements: list[PythonLogStatement]
    functions: list[PythonFunction]
    imports: list[PythonImport]
    async_calls: list[PythonAsyncCall]
