# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""MetricExtractor implementations for bounded context and integration style signals."""

from __future__ import annotations

from nfr_review.design_change.extractors import extractor_registry
from nfr_review.design_change.models import MetricCategory, NumericMetric, SetMetric
from nfr_review.models import Evidence

_DEPS_KINDS = frozenset(
    {
        "java-deps",
        "python-deps",
        "go-deps",
        "nodejs-deps",
        "csharp-deps",
    }
)

_MESSAGING_DEP_PATTERNS: dict[str, str] = {
    "kafka": "messaging:kafka",
    "rabbitmq": "messaging:rabbitmq",
    "amqp": "messaging:amqp",
    "activemq": "messaging:activemq",
    "spring-cloud-stream": "messaging:spring-cloud-stream",
    "aws-sqs": "messaging:sqs",
    "pubsub": "messaging:pubsub",
    "azure-servicebus": "messaging:servicebus",
    "nats": "messaging:nats",
    "pulsar": "messaging:pulsar",
}


def _extract_bounded_contexts(package_names: set[str]) -> set[str]:
    """Identify bounded contexts from fully-qualified package names.

    Finds the longest common prefix across all package names, then
    extracts the segment immediately after that prefix for each package.
    Each distinct segment represents a candidate bounded context.
    """
    if not package_names:
        return set()

    segments_list = [p.split(".") for p in package_names]
    min_len = min(len(s) for s in segments_list)

    prefix_len = 0
    for i in range(min_len):
        values = {s[i] for s in segments_list}
        if len(values) == 1:
            prefix_len = i + 1
        else:
            break

    contexts: set[str] = set()
    for segments in segments_list:
        if len(segments) > prefix_len:
            contexts.add(segments[prefix_len])
    return contexts


class BoundedContextExtractor:
    """Extracts bounded context count and names from JDepend package evidence."""

    @property
    def category(self) -> str:
        return "bounded_context"

    def extract(self, evidence: list[Evidence]) -> MetricCategory:
        packages_evidence = [e for e in evidence if e.kind == "jdepend-packages"]
        if not packages_evidence:
            return MetricCategory(category=self.category)

        package_names: set[str] = set()
        for ev in packages_evidence:
            for pkg in ev.payload.packages:
                if pkg.name:
                    package_names.add(pkg.name)

        if not package_names:
            return MetricCategory(category=self.category)

        contexts = _extract_bounded_contexts(package_names)
        if not contexts:
            return MetricCategory(category=self.category)

        return MetricCategory(
            category=self.category,
            numeric_metrics={
                "bounded_context_count": NumericMetric(
                    name="bounded_context_count",
                    value=float(len(contexts)),
                ),
            },
            set_metrics={
                "bounded_contexts": SetMetric(
                    name="bounded_contexts",
                    items=sorted(contexts),
                ),
            },
        )


class IntegrationStyleExtractor:
    """Extracts integration style labels from multiple evidence sources.

    Detects HTTP (Go AST http_calls), gRPC (proto services),
    service mesh (virtual services), and messaging (dependency names).
    """

    @property
    def category(self) -> str:
        return "integration_style"

    def extract(self, evidence: list[Evidence]) -> MetricCategory:
        styles: set[str] = set()
        point_count = 0

        for ev in evidence:
            if ev.kind == "go-ast-file":
                http_calls = getattr(ev.payload, "http_calls", [])
                if http_calls:
                    styles.add("http:direct")
                    point_count += len(http_calls)

            elif ev.kind == "proto-analysis":
                for svc in ev.payload.services:
                    if svc.methods:
                        styles.add("grpc")
                        point_count += len(svc.methods)

            elif ev.kind == "service-mesh-virtual-service":
                styles.add("service-mesh")
                point_count += ev.payload.total_routes

            elif ev.kind in _DEPS_KINDS:
                for dep in ev.payload.dependencies:
                    name_lower = dep.name.lower()
                    for keyword, label in _MESSAGING_DEP_PATTERNS.items():
                        if keyword in name_lower:
                            styles.add(label)
                            point_count += 1
                            break

        if not styles:
            return MetricCategory(category=self.category)

        return MetricCategory(
            category=self.category,
            numeric_metrics={
                "integration_point_count": NumericMetric(
                    name="integration_point_count",
                    value=float(point_count),
                ),
            },
            set_metrics={
                "integration_styles": SetMetric(
                    name="integration_styles",
                    items=sorted(styles),
                ),
            },
        )


def _register() -> None:
    instances: list[BoundedContextExtractor | IntegrationStyleExtractor] = [
        BoundedContextExtractor(),
        IntegrationStyleExtractor(),
    ]
    for ext in instances:
        if ext.category not in extractor_registry:
            extractor_registry.register(ext.category, ext)


_register()

__all__ = ["BoundedContextExtractor", "IntegrationStyleExtractor"]
