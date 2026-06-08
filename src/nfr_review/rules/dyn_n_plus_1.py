# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""dyn-n-plus-1: detect N+1 query patterns from otel-trace evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Literal

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

DEFAULT_THRESHOLD = 5


class DynNPlus1Rule:
    """Detect N+1 query patterns by counting child DB spans per request span."""

    id = "dyn-n-plus-1"
    band: Band = 3
    required_collectors: list[str] = ["otel-trace"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        trace_ev = [
            e for e in evidence if e.collector_name == "otel-trace" and e.kind == "otel-trace"
        ]
        if not trace_ev:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no otel-trace evidence available",
            )

        spans_by_id: dict[str, dict[str, Any]] = {}
        children: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for ev in trace_ev:
            for span in ev.payload.get("spans", []):
                sid = span.get("span_id", "")
                if sid:
                    spans_by_id[sid] = span
                pid = span.get("parent_span_id", "")
                if pid:
                    children[pid].append(span)

        first = trace_ev[0]
        findings: list[Finding] = []

        server_spans = [s for s in spans_by_id.values() if s.get("kind") == 2]
        if not server_spans:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no server spans found in trace data",
            )

        for server_span in server_spans:
            sid = server_span.get("span_id", "")
            db_children = _collect_db_descendants(sid, children)
            if len(db_children) < DEFAULT_THRESHOLD:
                continue

            stmt_counts: Counter[str] = Counter()
            for db_span in db_children:
                key = _db_identity(db_span)
                stmt_counts[key] += 1

            for stmt_key, count in stmt_counts.items():
                if count < DEFAULT_THRESHOLD:
                    continue

                route = server_span.get("attributes", {}).get(
                    "http.route", server_span.get("name", "unknown")
                )

                rag: Literal["red", "amber"] = "red" if count > 20 else "amber"
                severity: Literal["high", "medium"] = "high" if count > 20 else "medium"

                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag=rag,
                        severity=severity,
                        summary=(
                            f"N+1 query pattern: {count} identical DB calls "
                            f"({stmt_key!r}) under request span "
                            f"'{route}' (threshold={DEFAULT_THRESHOLD})."
                        ),
                        recommendation=(
                            f"Replace the {count} individual queries with a "
                            "batch query or JOIN. This is a classic N+1 pattern "
                            "where the ORM fetches related records one at a time."
                        ),
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.9,
                        pattern_tag=f"dyn-n-plus-1:{route}",
                    )
                )

        if not findings:
            total_server = len(server_spans)
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        f"No N+1 query patterns detected across {total_server} "
                        f"request span(s) (threshold={DEFAULT_THRESHOLD})."
                    ),
                    recommendation="No action required.",
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.85,
                    pattern_tag="dyn-n-plus-1-clean",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _collect_db_descendants(
    parent_id: str, children: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    stack = list(children.get(parent_id, []))
    while stack:
        span = stack.pop()
        attrs = span.get("attributes", {})
        if attrs.get("db.system"):
            result.append(span)
        sid = span.get("span_id", "")
        if sid:
            stack.extend(children.get(sid, []))
    return result


def _db_identity(span: dict[str, Any]) -> str:
    attrs = span.get("attributes", {})
    stmt = attrs.get("db.statement", "")
    if stmt:
        return stmt
    return span.get("name", "unknown-db-op")


def _register() -> None:
    if "dyn-n-plus-1" not in rule_registry:
        rule_registry.register("dyn-n-plus-1", DynNPlus1Rule())


_register()

__all__ = ["DynNPlus1Rule"]
