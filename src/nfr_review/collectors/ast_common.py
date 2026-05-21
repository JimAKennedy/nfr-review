# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
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
from typing import TYPE_CHECKING, Any

import tree_sitter

if TYPE_CHECKING:
    from tree_sitter import Node, Parser

from nfr_review.models import Evidence
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path

logger = logging.getLogger("nfr_review.collectors.ast_common")

_GRAMMAR_LOADERS: dict[str, tuple[str, str]] = {
    "java": ("tree_sitter_java", "language"),
    "python": ("tree_sitter_python", "language"),
    "go": ("tree_sitter_go", "language"),
    "hcl": ("tree_sitter_hcl", "language"),
    "dockerfile": ("tree_sitter_dockerfile", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "csharp": ("tree_sitter_c_sharp", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
}


def make_parser(language: str) -> tree_sitter.Parser:
    """Create a tree-sitter Parser for *language* using individual grammar packages."""
    if language not in _GRAMMAR_LOADERS:
        raise ValueError(f"Unsupported tree-sitter language: {language!r}")
    module_name, func_name = _GRAMMAR_LOADERS[language]
    import importlib

    mod = importlib.import_module(module_name)
    lang_ptr = getattr(mod, func_name)()
    lang = tree_sitter.Language(lang_ptr)
    return tree_sitter.Parser(lang)


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
        self._parser: Parser | None = None  # type: ignore[assignment]

    def _get_parser(self) -> Parser | None:
        """Return the tree-sitter parser, creating it on first use.

        Returns ``None`` if the grammar package is not installed.
        """
        if self._parser is None:
            try:
                self._parser = make_parser(self.language)  # type: ignore[assignment]
            except (ImportError, ModuleNotFoundError):
                logger.warning(
                    "tree-sitter grammar for %s not installed — %s collector disabled",
                    self.language,
                    self.name,
                )
                return None
        return self._parser

    @abstractmethod
    def _parse_file(self, source: bytes, rel_path: str) -> dict[str, Any]:
        """Parse *source* and return the evidence payload dict.

        *rel_path* is the file path relative to the repo root (useful for
        logging / diagnostics).  The returned dict is stored as-is in
        ``Evidence.payload``; ``file_path`` is added by the caller.
        """
        ...

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        if self._get_parser() is None:
            return []
        exclude_pats = compile_exclude_patterns(getattr(config, "exclude_paths", []))
        exclude_test = getattr(config, "exclude_test_paths", True)
        evidence: list[Evidence] = []
        for ext in self.file_extensions:
            for src_file in sorted(repo_path.rglob(f"*{ext}")):
                rel = src_file.relative_to(repo_path)
                if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
                    continue
                if should_exclude_path(
                    str(rel),
                    exclude_test_paths=exclude_test,
                    exclude_patterns=exclude_pats or None,
                ):
                    continue
                try:
                    source = src_file.read_bytes()
                except OSError as exc:
                    logger.debug("Cannot read %s: %s", rel, exc)
                    continue
                try:
                    payload = self._parse_file(source, str(rel))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Parse error in %s: %s", rel, exc)
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


__all__ = ["BaseASTCollector", "find_nodes", "make_parser", "text"]
