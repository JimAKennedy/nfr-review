# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the proto collector.

Covers proto file analysis including messages, services, enums, fields,
reserved ranges, and RPC methods.
"""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "ProtoAnalysisPayload",
    "ProtoEnum",
    "ProtoEnumValue",
    "ProtoField",
    "ProtoMessage",
    "ProtoReservedRange",
    "ProtoRpcMethod",
    "ProtoService",
]


class ProtoField(BasePayload):
    name: str
    number: int
    type: str
    label: str
    line: int


class ProtoReservedRange(BasePayload):
    start: int
    end: int


class ProtoMessage(BasePayload):
    name: str
    line: int
    has_comment: bool
    fields: list[ProtoField]
    reserved_numbers: list[int]
    reserved_ranges: list[ProtoReservedRange]


class ProtoRpcMethod(BasePayload):
    name: str
    request_type: str
    response_type: str
    line: int
    has_comment: bool


class ProtoService(BasePayload):
    name: str
    line: int
    has_comment: bool
    methods: list[ProtoRpcMethod]


class ProtoEnumValue(BasePayload):
    name: str
    number: int


class ProtoEnum(BasePayload):
    name: str
    line: int
    enum_values: list[ProtoEnumValue]


class ProtoAnalysisPayload(BasePayload):
    file_path: str
    syntax: str | None = None
    package: str | None = None
    imports: list[str]
    messages: list[ProtoMessage]
    services: list[ProtoService]
    enums: list[ProtoEnum]
