# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the java-ast collector.

Covers Java AST analysis including classes, interfaces, methods, fields,
catch blocks, thread pools, and log statements.
"""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "JavaAstFilePayload",
    "JavaBaseClass",
    "JavaCatchBlock",
    "JavaClass",
    "JavaField",
    "JavaLogStatement",
    "JavaMethod",
    "JavaParameter",
    "JavaThreadPool",
]


class JavaParameter(BasePayload):
    name: str
    type: str


class JavaBaseClass(BasePayload):
    name: str
    access: str


class JavaField(BasePayload):
    name: str
    type: str
    access: str
    line: int


class JavaMethod(BasePayload):
    name: str
    annotations: list[str]
    return_type: str
    access: str
    is_virtual: bool
    is_pure_virtual: bool
    line: int
    parameters: list[JavaParameter]
    mapping_paths: list[str]


class JavaClass(BasePayload):
    name: str
    line: int
    annotations: list[str]
    is_abstract: bool
    is_interface: bool
    base_classes: list[JavaBaseClass]
    fields: list[JavaField]
    methods: list[JavaMethod]
    namespace: str
    outer_class: str


class JavaCatchBlock(BasePayload):
    caught_type: str
    rethrows: bool
    line: int


class JavaThreadPool(BasePayload):
    class_name: str
    line: int
    has_bounded_queue: bool
    has_rejection_policy: bool


class JavaLogStatement(BasePayload):
    method: str
    arguments_text: str
    line: int


class JavaAstFilePayload(BasePayload):
    file_path: str
    package: str
    classes: list[JavaClass]
    methods: list[JavaMethod]
    catch_blocks: list[JavaCatchBlock]
    imports: list[str]
    thread_pool_constructions: list[JavaThreadPool]
    log_statements: list[JavaLogStatement]
