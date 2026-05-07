"""Shared types for cross-language AST rules (D021 ANY-match semantics)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LanguageRuleConfig:
    """Maps a language to its AST collector, evidence kind, and tech key."""

    language: str
    collector_name: str
    evidence_kind: str
    tech_key: str


JAVA = LanguageRuleConfig("java", "java-ast", "java-ast-file", "java")
PYTHON = LanguageRuleConfig("python", "python-ast", "python-ast-file", "python")

ALL_LANGUAGES: list[LanguageRuleConfig] = [JAVA, PYTHON]

__all__ = ["LanguageRuleConfig", "JAVA", "PYTHON", "ALL_LANGUAGES"]
