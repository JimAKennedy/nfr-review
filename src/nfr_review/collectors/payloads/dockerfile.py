# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the Dockerfile collector."""

from __future__ import annotations

from nfr_review.models import BasePayload


class DockerStage(BasePayload):
    """One stage in a multi-stage Dockerfile."""

    name: str | None = None
    base_image: str
    base_tag: str | None = None
    has_digest: bool = False
    line: int


class DockerUserDirective(BasePayload):
    """A USER directive in a Dockerfile."""

    user: str
    line: int


class DockerRunCommand(BasePayload):
    """A RUN command in a Dockerfile."""

    text: str
    line: int


class DockerCopyAddCommand(BasePayload):
    """A COPY or ADD command in a Dockerfile."""

    instruction: str
    sources: list[str]
    destination: str
    line: int


class DockerEnvArg(BasePayload):
    """An ENV or ARG directive in a Dockerfile."""

    instruction: str
    name: str
    line: int


class DockerfileAnalysisPayload(BasePayload):
    """Payload for kind='dockerfile-analysis' evidence."""

    file_path: str
    stages: list[DockerStage]
    user_directives: list[DockerUserDirective]
    has_user_directive: bool
    run_commands: list[DockerRunCommand]
    copy_add_commands: list[DockerCopyAddCommand]
    env_args: list[DockerEnvArg]
    stage_count: int
    is_multistage: bool


__all__ = [
    "DockerStage",
    "DockerUserDirective",
    "DockerRunCommand",
    "DockerCopyAddCommand",
    "DockerEnvArg",
    "DockerfileAnalysisPayload",
]
