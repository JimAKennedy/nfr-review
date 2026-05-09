"""Dockerfile collector — parses Dockerfiles using tree-sitter and emits
per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="dockerfile-analysis"):
    file_path: str — path relative to repo_path
    stages: list[dict] — each with:
        name: str | None — stage alias (from AS <name>)
        base_image: str — image name
        base_tag: str | None — image tag (e.g. "3.11", "latest")
        has_digest: bool — whether the image uses a digest pin
        line: int — 1-based line number
    user_directives: list[dict] — each with:
        user: str — user name or UID
        line: int — 1-based line number
    has_user_directive: bool
    run_commands: list[dict] — each with:
        text: str — full RUN command text
        line: int — 1-based line number
    copy_add_commands: list[dict] — each with:
        instruction: str — "COPY" or "ADD"
        sources: list[str] — source paths
        destination: str — destination path
        line: int — 1-based line number
    env_args: list[dict] — each with:
        instruction: str — "ARG" or "ENV"
        name: str — variable name
        line: int — 1-based line number
    stage_count: int
    is_multistage: bool — stage_count > 1
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tree_sitter_language_pack import get_parser

if TYPE_CHECKING:
    from tree_sitter import Node, Parser

from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.dockerfile")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_DOCKERFILE_NAMES = frozenset({"Dockerfile", "dockerfile"})


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _find_nodes(node: Node, target_type: str) -> list[Node]:
    results: list[Node] = []
    if node.type == target_type:
        results.append(node)
    for child in node.children:
        results.extend(_find_nodes(child, target_type))
    return results


def _extract_stages(root: Node, source: bytes) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    for from_node in _find_nodes(root, "from_instruction"):
        base_image = ""
        base_tag: str | None = None
        has_digest = False
        alias: str | None = None

        for child in from_node.children:
            if child.type == "image_spec":
                for spec_child in child.children:
                    if spec_child.type == "image_name":
                        base_image = _text(spec_child, source)
                    elif spec_child.type == "image_tag":
                        tag_text = _text(spec_child, source)
                        base_tag = tag_text.lstrip(":")
                    elif spec_child.type == "image_digest":
                        has_digest = True
            elif child.type == "image_alias":
                alias = _text(child, source)

        stages.append(
            {
                "name": alias,
                "base_image": base_image,
                "base_tag": base_tag,
                "has_digest": has_digest,
                "line": from_node.start_point[0] + 1,
            }
        )
    return stages


def _extract_user_directives(root: Node, source: bytes) -> list[dict[str, Any]]:
    directives: list[dict[str, Any]] = []
    for user_node in _find_nodes(root, "user_instruction"):
        user_val = ""
        for child in user_node.children:
            if child.type == "unquoted_string":
                user_val = _text(child, source)
                break
        directives.append({"user": user_val, "line": user_node.start_point[0] + 1})
    return directives


def _extract_run_commands(root: Node, source: bytes) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for run_node in _find_nodes(root, "run_instruction"):
        text = _text(run_node, source)
        commands.append({"text": text, "line": run_node.start_point[0] + 1})
    return commands


def _extract_copy_add(root: Node, source: bytes) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for instr_type in ("copy_instruction", "add_instruction"):
        for node in _find_nodes(root, instr_type):
            instruction = "COPY" if instr_type == "copy_instruction" else "ADD"
            paths: list[str] = []
            for child in node.children:
                if child.type == "path":
                    paths.append(_text(child, source))

            sources = paths[:-1] if len(paths) > 1 else []
            destination = paths[-1] if paths else ""

            commands.append(
                {
                    "instruction": instruction,
                    "sources": sources,
                    "destination": destination,
                    "line": node.start_point[0] + 1,
                }
            )
    return commands


def _extract_env_args(root: Node, source: bytes) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for arg_node in _find_nodes(root, "arg_instruction"):
        name = ""
        for child in arg_node.children:
            if child.type == "unquoted_string":
                name = _text(child, source)
                break
        entries.append(
            {"instruction": "ARG", "name": name, "line": arg_node.start_point[0] + 1}
        )
    for env_node in _find_nodes(root, "env_instruction"):
        for child in env_node.children:
            if child.type == "env_pair":
                name = ""
                for sub in child.children:
                    if sub.type == "unquoted_string":
                        name = _text(sub, source)
                        break
                entries.append(
                    {
                        "instruction": "ENV",
                        "name": name,
                        "line": env_node.start_point[0] + 1,
                    }
                )
    return entries


def _parse_dockerfile(parser: Parser, source: bytes) -> dict[str, Any]:
    tree = parser.parse(source)
    root = tree.root_node

    stages = _extract_stages(root, source)
    user_directives = _extract_user_directives(root, source)
    run_commands = _extract_run_commands(root, source)
    copy_add_commands = _extract_copy_add(root, source)
    env_args = _extract_env_args(root, source)
    stage_count = len(stages)

    return {
        "stages": stages,
        "user_directives": user_directives,
        "has_user_directive": len(user_directives) > 0,
        "run_commands": run_commands,
        "copy_add_commands": copy_add_commands,
        "env_args": env_args,
        "stage_count": stage_count,
        "is_multistage": stage_count > 1,
    }


def _iter_dockerfiles(repo_path: Path) -> list[Path]:
    """Find all Dockerfiles in the repo using the same patterns as detect.py."""
    found: list[Path] = []

    for path in sorted(repo_path.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_path)
        if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
            continue
        if path.name in _DOCKERFILE_NAMES or path.name.endswith(".Dockerfile"):
            found.append(path)

    return found


class DockerfileCollector:
    name = "dockerfile"
    version = "0.1.0"

    def __init__(self) -> None:
        self._parser = get_parser("dockerfile")

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        for dockerfile in _iter_dockerfiles(repo_path):
            rel = dockerfile.relative_to(repo_path)
            try:
                source = dockerfile.read_bytes()
            except OSError as exc:
                logger.warning("Cannot read %s: %s", rel, exc)
                continue
            try:
                payload = _parse_dockerfile(self._parser, source)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                logger.warning("Parse error in %s: %s", rel, exc)
                continue
            payload["file_path"] = str(rel)
            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=str(rel),
                    kind="dockerfile-analysis",
                    payload=payload,
                )
            )
        return evidence


def _register() -> None:
    if "dockerfile" not in collector_registry:
        collector_registry.register("dockerfile", DockerfileCollector())


_register()

__all__ = ["DockerfileCollector"]
