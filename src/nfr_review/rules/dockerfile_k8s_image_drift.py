# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: dockerfile-k8s-image-drift — detects when the image tag in a
Dockerfile FROM doesn't match the image tag used in K8s container specs."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


def _parse_image(image: str) -> tuple[str, str | None]:
    """Parse an image string into (name, tag).

    Handles "repo/name:tag", "name:tag", and "name" (no tag).
    Digest references (@sha256:...) are treated as the tag.
    """
    if "@" in image:
        name, digest = image.split("@", 1)
        return name.strip(), digest.strip()
    if ":" in image:
        name, tag = image.rsplit(":", 1)
        return name.strip(), tag.strip()
    return image.strip(), None


def _image_base_name(image: str) -> str:
    """Return just the repository/name portion, stripped of tag and digest."""
    name, _ = _parse_image(image)
    return name


def _images_same_service(df_image: str, k8s_image: str) -> bool:
    """Heuristic: are these two images likely building the same service?

    We consider them the same service when the base name of the final
    Dockerfile stage matches the base name of the K8s image (ignoring
    registry prefixes and tags).
    """
    df_base = _image_base_name(df_image).split("/")[-1]
    k8s_base = _image_base_name(k8s_image).split("/")[-1]
    return df_base == k8s_base


class DockerfileK8sImageDriftRule:
    """Flag mismatches between Dockerfile base image tags and K8s container image tags."""

    id = "dockerfile-k8s-image-drift"
    band: Band = 1
    required_collectors: list[str] = ["dockerfile", "k8s-manifest"]
    required_tech: list[str] = ["dockerfile", "kubernetes"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        df_evidence = [
            e
            for e in evidence
            if e.collector_name == "dockerfile" and e.kind == "dockerfile-analysis"
        ]
        k8s_evidence = [
            e
            for e in evidence
            if e.collector_name == "k8s-manifest" and e.kind == "k8s-resource"
        ]

        if not df_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no dockerfile evidence available",
            )
        if not k8s_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no k8s-manifest evidence available",
            )

        # Collect final-stage images from all Dockerfiles
        # The final stage is the last entry in the stages list
        df_final_images: list[tuple[str, str, str]] = []  # (file_path, base_image, base_tag)
        for ev in df_evidence:
            stages = ev.payload.get("stages", [])
            if not stages:
                continue
            final_stage = stages[-1]
            base_image = final_stage.get("base_image", "")
            base_tag = final_stage.get("base_tag")
            file_path = ev.payload.get("file_path", ev.locator)
            if base_image:
                df_final_images.append((file_path, base_image, base_tag))

        findings: list[Finding] = []
        for ev in k8s_evidence:
            resource_name = ev.payload.get("name", "")
            k8s_file = ev.payload.get("file_path", ev.locator)

            for container in ev.payload.get("containers", []):
                container_name = container.get("name", "")
                k8s_image = container.get("image", "")
                if not k8s_image:
                    continue

                k8s_name, k8s_tag = _parse_image(k8s_image)

                for df_path, df_base_image, df_base_tag in df_final_images:
                    if not _images_same_service(df_base_image, k8s_image):
                        continue

                    # Same service detected — compare tags
                    if df_base_tag is None or k8s_tag is None:
                        continue  # can't compare without both tags

                    if df_base_tag != k8s_tag:
                        findings.append(
                            Finding(
                                rule_id=self.id,
                                rag="amber",
                                severity="medium",
                                summary=(
                                    f"Image tag drift: Dockerfile '{df_path}' uses"
                                    f" '{df_base_image}:{df_base_tag}' but K8s container"
                                    f" '{container_name}' in '{resource_name}' uses"
                                    f" '{k8s_image}'."
                                ),
                                recommendation=(
                                    "Align the image tags between the Dockerfile and the K8s"
                                    " deployment manifest to ensure the same artifact is built"
                                    " and deployed."
                                ),
                                evidence_locator=(
                                    f"{k8s_file}:{resource_name}:{container_name}"
                                ),
                                collector_name=ev.collector_name,
                                collector_version=ev.collector_version,
                                confidence=0.8,
                                pattern_tag="dockerfile-k8s-image-drift",
                            )
                        )

        if not findings:
            first_k8s = k8s_evidence[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="No Dockerfile / K8s image tag drift detected.",
                    recommendation="No action required — image tags are consistent.",
                    evidence_locator="all-artifacts",
                    collector_name=first_k8s.collector_name,
                    collector_version=first_k8s.collector_version,
                    confidence=0.8,
                    pattern_tag="dockerfile-k8s-image-drift",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "dockerfile-k8s-image-drift" not in rule_registry:
        rule_registry.register("dockerfile-k8s-image-drift", DockerfileK8sImageDriftRule())


_register()

__all__ = ["DockerfileK8sImageDriftRule"]
