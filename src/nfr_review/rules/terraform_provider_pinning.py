"""Rule: terraform-provider-pinning — flags providers without version constraints."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class TerraformProviderPinningRule:
    """Flag Terraform providers that lack version constraints."""

    id = "terraform-provider-pinning"
    band: Band = 1
    required_collectors: list[str] = ["terraform"]
    required_tech: list[str] = ["terraform"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        tf_evidence = [
            e
            for e in evidence
            if e.collector_name == "terraform" and e.kind == "terraform-analysis"
        ]
        if not tf_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no terraform-analysis evidence available",
            )

        provider_versions: dict[str, str | None] = {}

        for ev in tf_evidence:
            for pb in ev.payload.get("provider_blocks", []):
                name = pb.get("name", "")
                if not name:
                    continue
                version = pb.get("version")
                if name not in provider_versions or version is not None:
                    provider_versions[name] = version

            for tb in ev.payload.get("terraform_blocks", []):
                for rp in tb.get("required_providers", []):
                    name = rp.get("name", "")
                    if not name:
                        continue
                    vc = rp.get("version_constraint")
                    if name not in provider_versions or vc:
                        provider_versions[name] = vc

        findings: list[Finding] = []
        first = tf_evidence[0]

        for name, version in sorted(provider_versions.items()):
            if not version:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Provider '{name}' has no version constraint."
                            " Upgrades may introduce breaking changes."
                        ),
                        recommendation=(
                            f"Pin provider '{name}' to a version range in"
                            ' required_providers (e.g. "~> 5.0") to prevent'
                            " unexpected breaking changes."
                        ),
                        evidence_locator=f"provider:{name}",
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.9,
                        pattern_tag="terraform-provider-pinning",
                    )
                )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="All Terraform providers have version constraints.",
                    recommendation="No action required.",
                    evidence_locator="all-tf-files",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.9,
                    pattern_tag="terraform-provider-pinning",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "terraform-provider-pinning" not in rule_registry:
        rule_registry.register("terraform-provider-pinning", TerraformProviderPinningRule())


_register()

__all__ = ["TerraformProviderPinningRule"]
