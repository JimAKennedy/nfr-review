"""Rule: PATCH-ARCH-004 — checks multi-replica Deployments/StatefulSets for PDB coverage."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_WORKLOAD_KINDS = {"Deployment", "StatefulSet"}


def _labels_overlap(pdb_match_labels: dict | None, workload_labels: dict | None) -> bool:
    """Return True if every key-value in pdb_match_labels is present in workload_labels."""
    if not pdb_match_labels or not workload_labels:
        return False
    return all(workload_labels.get(k) == v for k, v in pdb_match_labels.items())


class PdbCoverageRule:
    """Flag multi-replica Deployments/StatefulSets with no matching PodDisruptionBudget."""

    id = "PATCH-ARCH-004"
    band: Band = 1
    required_collectors: list[str] = ["k8s-manifest"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        k8s_resources = [
            e
            for e in evidence
            if e.collector_name == "k8s-manifest" and e.kind == "k8s-resource"
        ]
        if not k8s_resources:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no k8s-manifest evidence available",
            )

        pdb_evidence = [
            e for e in evidence if e.collector_name == "k8s-manifest" and e.kind == "k8s-pdb"
        ]

        findings: list[Finding] = []

        for ev in k8s_resources:
            resource_kind = ev.payload.get("kind", "")
            if resource_kind not in _WORKLOAD_KINDS:
                continue

            replicas = ev.payload.get("replicas")
            if replicas is None or replicas <= 1:
                # Singleton or unset — PDB is not the concern here (PATCH-ARCH-001 covers it).
                continue

            resource_name = ev.payload.get("name", "")
            namespace = ev.payload.get("namespace")
            file_path = ev.payload.get("file_path", ev.locator)
            workload_labels = ev.payload.get("labels")

            # Find PDBs that are namespace-compatible and whose matchLabels
            # are a subset of this workload's pod template labels.
            matching_pdb: str | None = None
            for pdb_ev in pdb_evidence:
                pdb_namespace = pdb_ev.payload.get("namespace")
                # Namespace must match (both None counts as same namespace).
                if pdb_namespace != namespace:
                    continue
                match_labels = pdb_ev.payload.get("match_labels")
                if _labels_overlap(match_labels, workload_labels):
                    matching_pdb = pdb_ev.payload.get("name", pdb_ev.locator)
                    break

            if matching_pdb is None:
                # Attempt a namespace-presence fallback when no label data is available.
                # If workload has no labels captured, fall back to namespace-scoped presence.
                if not workload_labels:
                    ns_pdbs = [
                        pdb_ev
                        for pdb_ev in pdb_evidence
                        if pdb_ev.payload.get("namespace") == namespace
                    ]
                    if ns_pdbs:
                        matching_pdb = ns_pdbs[0].payload.get("name", ns_pdbs[0].locator)

            if matching_pdb is None:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"{resource_kind} '{resource_name}' has {replicas} replicas"
                            " but no matching PodDisruptionBudget."
                        ),
                        recommendation=(
                            "Define a PodDisruptionBudget for this workload to protect"
                            " availability during voluntary disruptions such as node"
                            " drains and cluster upgrades. Set minAvailable or"
                            " maxUnavailable to ensure at least one pod remains"
                            " healthy at all times."
                        ),
                        evidence_locator=f"{file_path}:{resource_name}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.90,
                        pattern_tag="pdb-coverage",
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(
                            f"{resource_kind} '{resource_name}' is covered by"
                            f" PodDisruptionBudget '{matching_pdb}'."
                        ),
                        recommendation="No action required — PDB coverage is present.",
                        evidence_locator=f"{file_path}:{resource_name}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.90,
                        pattern_tag="pdb-coverage",
                    )
                )

        if not findings:
            # No multi-replica workloads to check.
            first = k8s_resources[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="No multi-replica Deployment/StatefulSet resources to check.",
                    recommendation="No action required.",
                    evidence_locator="all-workloads",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.90,
                    pattern_tag="pdb-coverage",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "PATCH-ARCH-004" not in rule_registry:
        rule_registry.register("PATCH-ARCH-004", PdbCoverageRule())


_register()

__all__ = ["PdbCoverageRule"]
