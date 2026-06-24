"""Tests for the 4 Dockerfile NFR rules — isolated from the collector via inline Evidence."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.rules.dockerfile_base_pinning import DockerfileBasePinningRule
from nfr_review.rules.dockerfile_multistage import DockerfileMultistageRule
from nfr_review.rules.dockerfile_secret_leakage import DockerfileSecretLeakageRule
from nfr_review.rules.dockerfile_user_directive import DockerfileUserDirectiveRule


def _make_evidence(payload: dict) -> Evidence:
    return Evidence(
        collector_name="dockerfile",
        collector_version="0.1.0",
        locator="Dockerfile",
        kind="dockerfile-analysis",
        payload=payload,
    )


# ── Base Pinning Rule ─────────────────────────────────────────────


class TestBasePinningRule:
    def test_fires_on_floating_latest(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "stages": [
                    {
                        "base_image": "python",
                        "base_tag": "latest",
                        "has_digest": False,
                        "line": 1,
                    },
                ],
            }
        )
        result = DockerfileBasePinningRule().evaluate([ev], context=None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert "floating tag" in result.findings[0].summary

    def test_fires_on_no_tag(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "stages": [
                    {"base_image": "ubuntu", "base_tag": None, "has_digest": False, "line": 1},
                ],
            }
        )
        result = DockerfileBasePinningRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_green_on_pinned_digest(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "stages": [
                    {
                        "base_image": "golang",
                        "base_tag": "1.22",
                        "has_digest": True,
                        "line": 1,
                    },
                ],
            }
        )
        result = DockerfileBasePinningRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_green_on_specific_version_tag(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "stages": [
                    {
                        "base_image": "python",
                        "base_tag": "3.11-slim",
                        "has_digest": False,
                        "line": 1,
                    },
                ],
            }
        )
        result = DockerfileBasePinningRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skips_scratch(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "stages": [
                    {
                        "base_image": "scratch",
                        "base_tag": None,
                        "has_digest": False,
                        "line": 1,
                    },
                ],
            }
        )
        result = DockerfileBasePinningRule().evaluate([ev], context=None)
        assert result.findings[0].rag == "green"

    def test_skips_when_no_dockerfile_evidence(self) -> None:
        ev = Evidence(
            collector_name="k8s-manifest",
            collector_version="1.0",
            locator="deploy.yaml",
            kind="k8s-resource",
            payload={},
        )
        result = DockerfileBasePinningRule().evaluate([ev], context=None)
        assert result.skipped
        assert "no dockerfile-analysis evidence" in (result.skip_reason or "")


# ── User Directive Rule ───────────────────────────────────────────


class TestUserDirectiveRule:
    def test_fires_when_no_user(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "has_user_directive": False,
            }
        )
        result = DockerfileUserDirectiveRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "high"
        assert "root" in result.findings[0].summary

    def test_green_when_user_set(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "has_user_directive": True,
            }
        )
        result = DockerfileUserDirectiveRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skips_when_no_dockerfile_evidence(self) -> None:
        ev = Evidence(
            collector_name="k8s-manifest",
            collector_version="1.0",
            locator="deploy.yaml",
            kind="k8s-resource",
            payload={},
        )
        result = DockerfileUserDirectiveRule().evaluate([ev], context=None)
        assert result.skipped


# ── Secret Leakage Rule ──────────────────────────────────────────


class TestSecretLeakageRule:
    def test_fires_on_copy_env_file(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "copy_add_commands": [
                    {
                        "instruction": "COPY",
                        "sources": [".env"],
                        "destination": "/app/",
                        "line": 5,
                    },
                ],
                "env_args": [],
            }
        )
        result = DockerfileSecretLeakageRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "critical"
        assert ".env" in result.findings[0].summary

    def test_fires_on_copy_pem_file(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "copy_add_commands": [
                    {
                        "instruction": "COPY",
                        "sources": ["server.pem"],
                        "destination": "/certs/",
                        "line": 3,
                    },
                ],
                "env_args": [],
            }
        )
        result = DockerfileSecretLeakageRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"

    def test_fires_on_arg_password(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "copy_add_commands": [],
                "env_args": [
                    {"instruction": "ARG", "name": "DB_PASSWORD", "line": 2},
                ],
            }
        )
        result = DockerfileSecretLeakageRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert "DB_PASSWORD" in result.findings[0].summary

    def test_fires_on_env_secret(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "copy_add_commands": [],
                "env_args": [
                    {"instruction": "ENV", "name": "API_SECRET", "line": 4},
                ],
            }
        )
        result = DockerfileSecretLeakageRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"

    def test_catches_both_copy_and_arg(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "copy_add_commands": [
                    {
                        "instruction": "COPY",
                        "sources": [".env"],
                        "destination": "/app/",
                        "line": 3,
                    },
                ],
                "env_args": [
                    {"instruction": "ARG", "name": "SECRET_KEY", "line": 1},
                ],
            }
        )
        result = DockerfileSecretLeakageRule().evaluate([ev], context=None)
        assert len(result.findings) == 2
        assert all(f.rag == "red" for f in result.findings)

    def test_green_when_no_secrets(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "copy_add_commands": [
                    {
                        "instruction": "COPY",
                        "sources": ["app.py"],
                        "destination": "/app/",
                        "line": 5,
                    },
                ],
                "env_args": [
                    {"instruction": "ENV", "name": "APP_PORT", "line": 2},
                ],
            }
        )
        result = DockerfileSecretLeakageRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skips_when_no_dockerfile_evidence(self) -> None:
        ev = Evidence(
            collector_name="k8s-manifest",
            collector_version="1.0",
            locator="deploy.yaml",
            kind="k8s-resource",
            payload={},
        )
        result = DockerfileSecretLeakageRule().evaluate([ev], context=None)
        assert result.skipped


# ── Multi-stage Rule ──────────────────────────────────────────────


class TestMultistageRule:
    def test_fires_on_single_stage_with_run(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "is_multistage": False,
                "run_commands": [
                    {"text": "RUN pip install -r requirements.txt", "line": 3},
                ],
            }
        )
        result = DockerfileMultistageRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "low"
        assert "single-stage" in result.findings[0].summary

    def test_green_on_multistage(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "is_multistage": True,
                "run_commands": [
                    {"text": "RUN go build", "line": 5},
                ],
            }
        )
        result = DockerfileMultistageRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_green_on_single_stage_no_run(self) -> None:
        ev = _make_evidence(
            {
                "file_path": "Dockerfile",
                "is_multistage": False,
                "run_commands": [],
            }
        )
        result = DockerfileMultistageRule().evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skips_when_no_dockerfile_evidence(self) -> None:
        ev = Evidence(
            collector_name="k8s-manifest",
            collector_version="1.0",
            locator="deploy.yaml",
            kind="k8s-resource",
            payload={},
        )
        result = DockerfileMultistageRule().evaluate([ev], context=None)
        assert result.skipped
