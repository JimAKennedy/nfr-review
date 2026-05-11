"""Protobuf collector — parses .proto files via regex and emits per-file
Evidence with structured payload for downstream NFR rules.

Tree-sitter-language-pack lacks a protobuf grammar (D019), so this collector
uses regex extraction.  Proto3 syntax is regular enough for reliable field,
message, service, and comment extraction.

Evidence payload contract (kind="proto-analysis"):
    file_path: str — path relative to repo_path
    syntax: str | None — "proto2" or "proto3"
    package: str | None — package declaration
    imports: list[str] — imported paths
    messages: list[dict] — each with:
        name: str
        line: int — 1-based
        has_comment: bool — whether a comment precedes the message
        fields: list[dict] — each with:
            name: str
            number: int
            type: str
            label: str — "repeated", "optional", "map", or ""
            line: int — 1-based
        reserved_numbers: list[int] — reserved field numbers
        reserved_ranges: list[dict] — each with start: int, end: int
    services: list[dict] — each with:
        name: str
        line: int — 1-based
        has_comment: bool
        methods: list[dict] — each with:
            name: str
            request_type: str
            response_type: str
            line: int — 1-based
            has_comment: bool
    enums: list[dict] — each with:
        name: str
        line: int — 1-based
        values: list[dict] — each with name: str, number: int
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.proto")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_RE_SYNTAX = re.compile(r'^syntax\s*=\s*"(proto[23])"\s*;', re.MULTILINE)
_RE_PACKAGE = re.compile(r"^package\s+([\w.]+)\s*;", re.MULTILINE)
_RE_IMPORT = re.compile(r'^import\s+"([^"]+)"\s*;', re.MULTILINE)

_RE_MESSAGE = re.compile(r"^((?:\s*//[^\n]*\n)*)message\s+(\w+)\s*\{", re.MULTILINE)
_RE_SERVICE = re.compile(r"^((?:\s*//[^\n]*\n)*)service\s+(\w+)\s*\{", re.MULTILINE)
_RE_ENUM = re.compile(r"^enum\s+(\w+)\s*\{", re.MULTILINE)

_RE_FIELD = re.compile(
    r"^\s*(repeated|optional|map<[^>]+>)?\s*([\w.]+)\s+(\w+)\s*=\s*(\d+)\s*;",
    re.MULTILINE,
)
_RE_RESERVED_NUMS = re.compile(r"^\s*reserved\s+([\d\s,to]+)\s*;", re.MULTILINE)

_RE_RPC = re.compile(
    r"((?:\s*//[^\n]*\n)*)\s*rpc\s+(\w+)\s*\(\s*([\w.]+)\s*\)\s*returns\s*\(\s*([\w.]+)\s*\)",
    re.MULTILINE,
)

_RE_ENUM_VALUE = re.compile(r"^\s*(\w+)\s*=\s*(-?\d+)\s*;", re.MULTILINE)


def _extract_block(source: str, start: int) -> str:
    """Extract the brace-delimited block starting at position *start*."""
    brace = source.find("{", start)
    if brace == -1:
        return ""
    depth = 1
    pos = brace + 1
    end = len(source)
    while pos < end and depth > 0:
        ch = source[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        pos += 1
    return source[brace + 1 : pos - 1]


def _line_number(source: str, pos: int) -> int:
    return source[:pos].count("\n") + 1


def _parse_reserved(block: str) -> tuple[list[int], list[dict[str, int]]]:
    numbers: list[int] = []
    ranges: list[dict[str, int]] = []
    for m in _RE_RESERVED_NUMS.finditer(block):
        for part in m.group(1).split(","):
            part = part.strip()
            if "to" in part:
                lo, hi = part.split("to")
                lo_i, hi_i = int(lo.strip()), int(hi.strip())
                ranges.append({"start": lo_i, "end": hi_i})
                numbers.extend(range(lo_i, hi_i + 1))
            elif part:
                numbers.append(int(part))
    return numbers, ranges


def _parse_fields(block: str, block_offset: int, source: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for m in _RE_FIELD.finditer(block):
        label_raw = (m.group(1) or "").strip()
        if label_raw.startswith("map"):
            label = "map"
        else:
            label = label_raw
        fields.append(
            {
                "name": m.group(3),
                "number": int(m.group(4)),
                "type": m.group(2),
                "label": label,
                "line": _line_number(source, block_offset + m.start()),
            }
        )
    return fields


def _parse_messages(source: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for m in _RE_MESSAGE.finditer(source):
        comment_block = m.group(1)
        name = m.group(2)
        block = _extract_block(source, m.start())
        block_offset = source.find("{", m.start()) + 1
        fields = _parse_fields(block, block_offset, source)
        reserved_numbers, reserved_ranges = _parse_reserved(block)
        messages.append(
            {
                "name": name,
                "line": _line_number(source, m.start() + len(comment_block)),
                "has_comment": bool(comment_block.strip()),
                "fields": fields,
                "reserved_numbers": reserved_numbers,
                "reserved_ranges": reserved_ranges,
            }
        )
    return messages


def _parse_services(source: str) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    for m in _RE_SERVICE.finditer(source):
        comment_block = m.group(1)
        name = m.group(2)
        block = _extract_block(source, m.start())
        block_offset = source.find("{", m.start()) + 1
        methods: list[dict[str, Any]] = []
        for rpc_m in _RE_RPC.finditer(block):
            rpc_comment = rpc_m.group(1)
            methods.append(
                {
                    "name": rpc_m.group(2),
                    "request_type": rpc_m.group(3),
                    "response_type": rpc_m.group(4),
                    "line": _line_number(source, block_offset + rpc_m.start()),
                    "has_comment": bool(rpc_comment.strip()),
                }
            )
        services.append(
            {
                "name": name,
                "line": _line_number(source, m.start() + len(comment_block)),
                "has_comment": bool(comment_block.strip()),
                "methods": methods,
            }
        )
    return services


def _parse_enums(source: str) -> list[dict[str, Any]]:
    enums: list[dict[str, Any]] = []
    for m in _RE_ENUM.finditer(source):
        name = m.group(1)
        block = _extract_block(source, m.start())
        values: list[dict[str, Any]] = []
        for vm in _RE_ENUM_VALUE.finditer(block):
            values.append({"name": vm.group(1), "number": int(vm.group(2))})
        enums.append(
            {
                "name": name,
                "line": _line_number(source, m.start()),
                "values": values,
            }
        )
    return enums


def _parse_proto(source: str) -> dict[str, Any]:
    syntax_m = _RE_SYNTAX.search(source)
    package_m = _RE_PACKAGE.search(source)
    imports = [m.group(1) for m in _RE_IMPORT.finditer(source)]
    return {
        "syntax": syntax_m.group(1) if syntax_m else None,
        "package": package_m.group(1) if package_m else None,
        "imports": imports,
        "messages": _parse_messages(source),
        "services": _parse_services(source),
        "enums": _parse_enums(source),
    }


def _iter_proto_files(repo_path: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(repo_path.rglob("*.proto")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_path)
        if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
            continue
        found.append(path)
    return found


class ProtoCollector:
    name = "proto"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        for proto_file in _iter_proto_files(repo_path):
            rel = proto_file.relative_to(repo_path)
            try:
                source = proto_file.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.debug("Cannot read %s: %s", rel, exc)
                continue
            try:
                payload = _parse_proto(source)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Parse error in %s: %s", rel, exc)
                continue
            payload["file_path"] = str(rel)
            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=str(rel),
                    kind="proto-analysis",
                    payload=payload,
                )
            )
        return evidence


def _register() -> None:
    if "proto" not in collector_registry:
        collector_registry.register("proto", ProtoCollector())


_register()

__all__ = ["ProtoCollector"]
