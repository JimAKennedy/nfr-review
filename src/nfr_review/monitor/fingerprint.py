# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Interaction fingerprint model and extraction from OTel trace spans.

An InteractionFingerprint captures a unique type of service-to-service
interaction observed in traces.  Fingerprints are deterministic: the same
input spans always produce the same set of fingerprints.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nfr_review.collectors.payloads.otel_trace import OtelTraceSpan

Protocol = Literal["http", "grpc", "db", "messaging", "rpc", "internal", "unknown"]

_SPAN_KIND_CLIENT = 3
_SPAN_KIND_PRODUCER = 4


def _detect_protocol(attrs: dict[str, str]) -> Protocol:
    """Detect interaction protocol from span attributes."""
    if "db.system" in attrs:
        return "db"
    if "messaging.system" in attrs:
        return "messaging"
    if "rpc.system" in attrs:
        rpc_sys = attrs["rpc.system"]
        if rpc_sys == "grpc":
            return "grpc"
        return "rpc"
    if "http.method" in attrs or "http.request.method" in attrs:
        return "http"
    return "unknown"


def _compute_hash(caller: str, callee: str, operation: str, kind: int, protocol: str) -> str:
    """Deterministic SHA256 fingerprint hash."""
    canonical = f"{caller}\0{callee}\0{operation}\0{kind}\0{protocol}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class InteractionFingerprint(BaseModel):
    """A unique service-to-service interaction pattern."""

    model_config = ConfigDict(frozen=True)

    caller_service: str
    callee_service: str
    operation: str
    span_kind: int
    protocol: Protocol
    fingerprint_hash: str = Field(default="")

    def model_post_init(self, __context: object) -> None:
        if not self.fingerprint_hash:
            object.__setattr__(
                self,
                "fingerprint_hash",
                _compute_hash(
                    self.caller_service,
                    self.callee_service,
                    self.operation,
                    self.span_kind,
                    self.protocol,
                ),
            )


def _resolve_callee(span: OtelTraceSpan) -> str:
    """Resolve the callee service name from span attributes."""
    attrs = span.attributes
    if "peer.service" in attrs:
        return attrs["peer.service"]
    if "db.system" in attrs:
        db_name = attrs.get("db.name", "")
        return f"{attrs['db.system']}:{db_name}" if db_name else attrs["db.system"]
    if "messaging.system" in attrs:
        dest = attrs.get("messaging.destination.name", "")
        return f"{attrs['messaging.system']}:{dest}" if dest else attrs["messaging.system"]
    if "net.peer.name" in attrs:
        return attrs["net.peer.name"]
    if "server.address" in attrs:
        return attrs["server.address"]
    return ""


def extract_fingerprints(
    spans: list[OtelTraceSpan],
) -> set[InteractionFingerprint]:
    """Extract unique interaction fingerprints from a list of spans.

    Identifies two types of interactions:
    1. Cross-service edges: parent and child spans with different service_names
    2. Leaf client calls: CLIENT/PRODUCER spans calling external resources
       (databases, message brokers) where the callee isn't another instrumented
       service in the trace
    """
    span_index: dict[str, OtelTraceSpan] = {}
    for span in spans:
        if span.span_id:
            span_index[span.span_id] = span

    fingerprints: set[InteractionFingerprint] = set()
    cross_service_child_ids: set[str] = set()

    for span in spans:
        if not span.parent_span_id:
            continue
        parent = span_index.get(span.parent_span_id)
        if not parent:
            continue
        if (
            parent.service_name
            and span.service_name
            and parent.service_name != span.service_name
        ):
            protocol = _detect_protocol(span.attributes)
            fp = InteractionFingerprint(
                caller_service=parent.service_name,
                callee_service=span.service_name,
                operation=span.name,
                span_kind=span.kind,
                protocol=protocol,
            )
            fingerprints.add(fp)
            cross_service_child_ids.add(span.span_id)

    for span in spans:
        if span.span_id in cross_service_child_ids:
            continue
        if span.kind not in (_SPAN_KIND_CLIENT, _SPAN_KIND_PRODUCER):
            continue
        callee = _resolve_callee(span)
        if not callee or not span.service_name:
            continue
        protocol = _detect_protocol(span.attributes)
        fp = InteractionFingerprint(
            caller_service=span.service_name,
            callee_service=callee,
            operation=span.name,
            span_kind=span.kind,
            protocol=protocol,
        )
        fingerprints.add(fp)

    return fingerprints


__all__ = [
    "InteractionFingerprint",
    "Protocol",
    "extract_fingerprints",
]
