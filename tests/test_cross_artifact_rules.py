"""Cross-artifact design coherence rules integration tests.

Tests dockerfile-k8s-user-conflict and dockerfile-k8s-image-drift rules
through Engine with isolated registries and fixture directories.
"""

from __future__ import annotations

from pathlib import Path

from nfr_review.collectors.dockerfile import DockerfileCollector
from nfr_review.collectors.k8s_manifest import K8sManifestCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.dockerfile_k8s_image_drift import DockerfileK8sImageDriftRule
from nfr_review.rules.dockerfile_k8s_user_conflict import DockerfileK8sUserConflictRule

FIXTURES = Path(__file__).parent / "fixtures"
CONFLICT_REPO = FIXTURES / "cross-artifact-conflict"
CLEAN_REPO = FIXTURES / "cross-artifact-clean"

CROSS_ARTIFACT_RULE_IDS = {
    "dockerfile-k8s-user-conflict",
    "dockerfile-k8s-image-drift",
}


def _cross_artifact_registries() -> tuple[Registry, Registry]:
    """Build isolated registries with only the cross-artifact collectors and rules."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("dockerfile", DockerfileCollector())
    cregistry.register("k8s-manifest", K8sManifestCollector())

    rregistry.register("dockerfile-k8s-user-conflict", DockerfileK8sUserConflictRule())
    rregistry.register("dockerfile-k8s-image-drift", DockerfileK8sImageDriftRule())

    return cregistry, rregistry


class TestUserConflictRuleFires:
    """dockerfile-k8s-user-conflict fires red when runAsUser: 0 overrides Dockerfile USER."""

    def _run(self) -> RunResult:
        cregistry, rregistry = _cross_artifact_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"dockerfile": True, "kubernetes": True})
        return engine.run(target=CONFLICT_REPO, config=cfg)

    def test_rule_runs(self) -> None:
        result = self._run()
        assert "dockerfile-k8s-user-conflict" in result.run_metadata.rules_run

    def test_conflict_fires_red(self) -> None:
        result = self._run()
        red_findings = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-k8s-user-conflict" and f.rag == "red"
        ]
        assert len(red_findings) >= 1

    def test_conflict_mentions_runasuser(self) -> None:
        result = self._run()
        red_findings = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-k8s-user-conflict" and f.rag == "red"
        ]
        assert any("runAsUser" in f.summary or "0" in f.summary for f in red_findings)

    def test_conflict_no_green(self) -> None:
        result = self._run()
        green_findings = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-k8s-user-conflict" and f.rag == "green"
        ]
        assert len(green_findings) == 0


class TestUserConflictRuleClean:
    """dockerfile-k8s-user-conflict is green when K8s uses runAsUser: 1000."""

    def _run(self) -> RunResult:
        cregistry, rregistry = _cross_artifact_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"dockerfile": True, "kubernetes": True})
        return engine.run(target=CLEAN_REPO, config=cfg)

    def test_rule_runs(self) -> None:
        result = self._run()
        assert "dockerfile-k8s-user-conflict" in result.run_metadata.rules_run

    def test_no_red_findings(self) -> None:
        result = self._run()
        red_findings = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-k8s-user-conflict" and f.rag == "red"
        ]
        assert len(red_findings) == 0

    def test_green_finding_present(self) -> None:
        result = self._run()
        green_findings = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-k8s-user-conflict" and f.rag == "green"
        ]
        assert len(green_findings) >= 1


class TestImageDriftRuleFires:
    """dockerfile-k8s-image-drift fires amber when image tags mismatch for same service."""

    def _run_with_drift(self, tmp_path: Path) -> RunResult:
        """Set up a fixture with same image name but different tags in Dockerfile and K8s."""
        (tmp_path / "Dockerfile").write_text(
            'FROM myapp:3.11-slim\nUSER nonroot\nCMD ["python", "app.py"]\n'
        )
        (tmp_path / "deployment.yaml").write_text(
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: myapp\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "        - name: myapp\n"
            "          image: myapp:3.12-slim\n"
            "          securityContext:\n"
            "            runAsNonRoot: true\n"
        )
        cregistry, rregistry = _cross_artifact_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"dockerfile": True, "kubernetes": True})
        return engine.run(target=tmp_path, config=cfg)

    def test_image_drift_fires_amber(self, tmp_path: Path) -> None:
        result = self._run_with_drift(tmp_path)
        amber_findings = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-k8s-image-drift" and f.rag == "amber"
        ]
        assert len(amber_findings) >= 1

    def test_image_drift_mentions_tags(self, tmp_path: Path) -> None:
        result = self._run_with_drift(tmp_path)
        amber_findings = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-k8s-image-drift" and f.rag == "amber"
        ]
        assert any("3.11" in f.summary and "3.12" in f.summary for f in amber_findings)


class TestImageDriftRuleClean:
    """dockerfile-k8s-image-drift is green when fixture tags don't match same service."""

    def _run(self) -> RunResult:
        # The conflict fixture uses python:3.11-slim in Dockerfile and myapp:3.12-slim
        # in K8s — different service names, so image drift should NOT fire.
        cregistry, rregistry = _cross_artifact_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"dockerfile": True, "kubernetes": True})
        return engine.run(target=CONFLICT_REPO, config=cfg)

    def test_rule_runs(self) -> None:
        result = self._run()
        assert "dockerfile-k8s-image-drift" in result.run_metadata.rules_run

    def test_no_amber_for_different_service_names(self) -> None:
        result = self._run()
        amber_findings = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-k8s-image-drift" and f.rag == "amber"
        ]
        assert len(amber_findings) == 0

    def test_clean_fixture_no_drift(self) -> None:
        cregistry, rregistry = _cross_artifact_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"dockerfile": True, "kubernetes": True})
        result = engine.run(target=CLEAN_REPO, config=cfg)
        amber_findings = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-k8s-image-drift" and f.rag == "amber"
        ]
        assert len(amber_findings) == 0


class TestTechGating:
    """Cross-artifact rules are skipped when tech is not declared."""

    def test_skipped_without_dockerfile_tech(self) -> None:
        cregistry, rregistry = _cross_artifact_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"kubernetes": True})
        result = engine.run(target=CONFLICT_REPO, config=cfg)
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        assert "dockerfile-k8s-user-conflict" in skipped
        assert "dockerfile-k8s-image-drift" in skipped

    def test_skipped_without_kubernetes_tech(self) -> None:
        cregistry, rregistry = _cross_artifact_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"dockerfile": True})
        result = engine.run(target=CONFLICT_REPO, config=cfg)
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        assert "dockerfile-k8s-user-conflict" in skipped
        assert "dockerfile-k8s-image-drift" in skipped

    def test_both_rules_run_with_both_techs(self) -> None:
        cregistry, rregistry = _cross_artifact_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"dockerfile": True, "kubernetes": True})
        result = engine.run(target=CONFLICT_REPO, config=cfg)
        run_set = set(result.run_metadata.rules_run)
        assert CROSS_ARTIFACT_RULE_IDS <= run_set
