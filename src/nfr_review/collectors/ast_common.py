"""Shared infrastructure for language-specific AST collectors.

BaseASTCollector handles file discovery (by extension), hidden-directory
skipping, tree-sitter parser initialisation via ``get_parser()``, and
Evidence construction.  Subclasses override ``_parse_file()`` to extract
a language-specific payload dict from the parsed AST.

The standard payload contract requires at least:
    - catch_blocks  (list[dict])  — or the language-neutral equivalent
    - log_statements (list[dict])
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from tree_sitter_language_pack import get_parser

if TYPE_CHECKING:
    from tree_sitter import Node, Parser

from nfr_review.models import Evidence

logger = logging.getLogger("nfr_review.collectors.ast_common")

_HIDDEN_DIRS = frozenset(
    {".git", ".svn", ".hg", ".idea", ".vscode", "node_modules", "__pycache__", ".mypy_cache"}
)


def text(node: Node, source: bytes) -> str:
    """Extract the source text spanned by *node*."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def find_nodes(node: Node, target_type: str) -> list[Node]:
    """Recursively collect all descendants (inclusive) matching *target_type*."""
    results: list[Node] = []
    if node.type == target_type:
        results.append(node)
    for child in node.children:
        results.extend(find_nodes(child, target_type))
    return results


class BaseASTCollector(ABC):
    """Base class for tree-sitter-backed AST collectors.

    Subclasses must set ``name``, ``version``, ``language``,
    ``file_extensions``, and ``evidence_kind`` as class or instance
    attributes, and implement ``_parse_file()``.
    """

    name: str
    version: str
    language: str
    file_extensions: tuple[str, ...]
    evidence_kind: str

    def __init__(self) -> None:
        self._parser: Parser = get_parser(cast(Any, self.language))  # type: ignore[assignment]

    @abstractmethod
    def _parse_file(self, source: bytes, rel_path: str) -> dict[str, Any]:
        """Parse *source* and return the evidence payload dict.

        *rel_path* is the file path relative to the repo root (useful for
        logging / diagnostics).  The returned dict is stored as-is in
        ``Evidence.payload``; ``file_path`` is added by the caller.
        """
        ...

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        for ext in self.file_extensions:
            for src_file in sorted(repo_path.rglob(f"*{ext}")):
                rel = src_file.relative_to(repo_path)
                if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
                    continue
                try:
                    source = src_file.read_bytes()
                except OSError as exc:
                    logger.warning("Cannot read %s: %s", rel, exc)
                    continue
                try:
                    payload = self._parse_file(source, str(rel))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Parse error in %s: %s", rel, exc)
                    continue
                payload["file_path"] = str(rel)
                evidence.append(
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=str(rel),
                        kind=self.evidence_kind,
                        payload=payload,
                    )
                )
        return evidence


__all__ = ["BaseASTCollector", "find_nodes", "text"]
