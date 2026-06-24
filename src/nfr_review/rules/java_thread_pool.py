# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: thread-pool-misconfiguration -- unbounded thread pools without rejection policy."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.java_ast import JavaAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class ThreadPoolMisconfigurationRule(FieldRule[JavaAstFilePayload]):
    """Flag ThreadPoolExecutor instances without bounded queue or rejection policy."""

    id = "thread-pool-misconfiguration"
    collector_name = "java-ast"
    evidence_kind = "java-ast-file"
    payload_type = JavaAstFilePayload
    pattern_tag = "thread-pool-config"
    default_confidence = 0.8
    all_clear_summary = "No misconfigured thread pools detected."
    all_clear_recommendation = "No action required."

    def check(self, payload: JavaAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for pool in payload.thread_pool_constructions:
            if not pool.has_bounded_queue or not pool.has_rejection_policy:
                issues: list[str] = []
                if not pool.has_bounded_queue:
                    issues.append("unbounded queue")
                if not pool.has_rejection_policy:
                    issues.append("no rejection policy")
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary=f"{pool.class_name} has {', '.join(issues)}",
                    recommendation=(
                        "Use a bounded queue (e.g."
                        " ArrayBlockingQueue) and set a"
                        " RejectedExecutionHandler."
                    ),
                    locator=f"{payload.file_path}:{pool.line}",
                )


__all__ = ["ThreadPoolMisconfigurationRule"]
