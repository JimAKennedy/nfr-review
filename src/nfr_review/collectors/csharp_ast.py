"""C# AST collector — parses .cs files using tree-sitter and emits
per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="csharp-ast-file"):
    file_path: str — path relative to repo_path
    catch_blocks: list[dict] — each with:
        caught_type: str — e.g. 'Exception', '' for bare catch
        rethrows: bool — block contains throw statement
        has_logging: bool — block contains Console/Debug logging call
        line: int — 1-based line number
        file: str — relative file path
    log_statements: list[dict] — each with:
        method: str — e.g. 'Console.WriteLine', 'Debug.WriteLine'
        line: int — 1-based line number
        file: str — relative file path
    methods: list[dict] — each with:
        name: str
        line: int — 1-based
        is_async: bool
        return_type: str — e.g. 'Task', 'void', 'int'
        modifiers: list[str] — e.g. ['public', 'async']
    await_expressions: list[dict] — each with:
        expression: str — text of the awaited expression
        has_configure_await: bool
        line: int — 1-based line number
        file: str — relative file path
    object_creations: list[dict] — each with:
        type_name: str — e.g. 'FileStream', 'SqlConnection'
        in_using: bool — True if wrapped in a using statement/declaration
        line: int — 1-based line number
        file: str — relative file path
    blocking_calls: list[dict] — each with:
        expression: str — text of the blocking call
        call_type: str — '.Result', '.Wait', '.GetAwaiter'
        line: int — 1-based line number
        file: str — relative file path
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tree_sitter import Node

from nfr_review.collectors.ast_common import BaseASTCollector, find_nodes, text
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.csharp_ast")

_CONSOLE_METHODS = frozenset({"WriteLine", "Write"})
_DEBUG_METHODS = frozenset({"WriteLine"})

_BLOCKING_MEMBER_NAMES = frozenset({"Result", "GetAwaiter"})


def _member_access_text(node: Node, source: bytes) -> str:
    """Reconstruct dotted name from a member_access_expression."""
    parts: list[str] = []
    current: Node | None = node
    while current is not None and current.type == "member_access_expression":
        for child in reversed(current.children):
            if child.type == "identifier":
                parts.append(text(child, source))
                break
        left = current.children[0] if current.children else None
        if left is not None and left.type == "member_access_expression":
            current = left
        elif left is not None and left.type == "identifier":
            parts.append(text(left, source))
            break
        else:
            break
    parts.reverse()
    return ".".join(parts)


def _invocation_name(node: Node, source: bytes) -> str:
    """Extract the dotted call name from an invocation_expression."""
    if node.type != "invocation_expression":
        return ""
    func = node.children[0] if node.children else None
    if func is None:
        return ""
    if func.type == "identifier":
        return text(func, source)
    if func.type == "member_access_expression":
        return _member_access_text(func, source)
    return ""


def _has_logging_call(block: Node, source: bytes) -> bool:
    """Check if a block contains Console/Debug logging calls."""
    for inv in find_nodes(block, "invocation_expression"):
        name = _invocation_name(inv, source)
        parts = name.split(".")
        if len(parts) == 2:
            if parts[0] == "Console" and parts[1] in _CONSOLE_METHODS:
                return True
            if parts[0] == "Debug" and parts[1] in _DEBUG_METHODS:
                return True
    return False


def _extract_catch_blocks(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for catch in find_nodes(root, "catch_clause"):
        caught_type = ""
        for child in catch.children:
            if child.type == "catch_declaration":
                for sub in child.children:
                    if sub.type == "identifier":
                        caught_type = text(sub, source)
                        break
                break

        rethrows = len(find_nodes(catch, "throw_statement")) > 0

        block_node = None
        for child in catch.children:
            if child.type == "block":
                block_node = child
                break
        has_logging = _has_logging_call(block_node, source) if block_node else False

        blocks.append(
            {
                "caught_type": caught_type,
                "rethrows": rethrows,
                "has_logging": has_logging,
                "line": catch.start_point[0] + 1,
                "file": rel_path,
            }
        )
    return blocks


def _extract_log_statements(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    stmts: list[dict[str, Any]] = []
    for inv in find_nodes(root, "invocation_expression"):
        name = _invocation_name(inv, source)
        parts = name.split(".")
        if len(parts) != 2:
            continue
        is_log = False
        if parts[0] == "Console" and parts[1] in _CONSOLE_METHODS:
            is_log = True
        elif parts[0] == "Debug" and parts[1] in _DEBUG_METHODS:
            is_log = True
        if is_log:
            stmts.append({"method": name, "line": inv.start_point[0] + 1, "file": rel_path})
    return stmts


def _extract_methods(root: Node, source: bytes) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    for method in find_nodes(root, "method_declaration"):
        name = ""
        return_type = ""
        modifiers: list[str] = []
        is_async = False

        children = method.children
        param_idx = next((i for i, c in enumerate(children) if c.type == "parameter_list"), -1)

        for i, child in enumerate(children):
            if child.type == "modifier":
                mod_text = text(child, source)
                modifiers.append(mod_text)
                if mod_text == "async":
                    is_async = True
            elif child.type == "identifier":
                if param_idx > 0 and i == param_idx - 1:
                    name = text(child, source)
                elif not return_type:
                    return_type = text(child, source)
            elif (
                child.type
                in (
                    "predefined_type",
                    "generic_name",
                    "qualified_name",
                    "nullable_type",
                    "array_type",
                )
                and not return_type
            ):
                return_type = text(child, source)

        methods.append(
            {
                "name": name,
                "line": method.start_point[0] + 1,
                "is_async": is_async,
                "return_type": return_type,
                "modifiers": modifiers,
            }
        )
    return methods


def _extract_await_expressions(
    root: Node, source: bytes, rel_path: str
) -> list[dict[str, Any]]:
    awaits: list[dict[str, Any]] = []
    for await_node in find_nodes(root, "await_expression"):
        expr_text = ""
        has_configure_await = False
        for child in await_node.children:
            if child.type != "await":
                expr_text = text(child, source)
                if "ConfigureAwait" in expr_text:
                    has_configure_await = True
                break

        awaits.append(
            {
                "expression": expr_text,
                "has_configure_await": has_configure_await,
                "line": await_node.start_point[0] + 1,
                "file": rel_path,
            }
        )
    return awaits


def _is_in_using(node: Node) -> bool:
    """Check if an object_creation_expression is inside a using statement or declaration."""
    parent = node.parent
    while parent is not None:
        if parent.type == "using_statement":
            return True
        if parent.type == "local_declaration_statement":
            return any(c.type == "using" for c in parent.children)
        parent = parent.parent
    return False


def _extract_object_creations(
    root: Node, source: bytes, rel_path: str
) -> list[dict[str, Any]]:
    creations: list[dict[str, Any]] = []
    for oce in find_nodes(root, "object_creation_expression"):
        type_name = ""
        for child in oce.children:
            if child.type == "identifier":
                type_name = text(child, source)
                break
            if child.type == "qualified_name":
                type_name = text(child, source)
                break
            if child.type == "generic_name":
                type_name = text(child, source)
                break

        in_using = _is_in_using(oce)
        creations.append(
            {
                "type_name": type_name,
                "in_using": in_using,
                "line": oce.start_point[0] + 1,
                "file": rel_path,
            }
        )
    return creations


def _rightmost_member(node: Node, source: bytes) -> str:
    """Get the rightmost identifier from a member_access_expression."""
    if node.type != "member_access_expression":
        return ""
    for child in reversed(node.children):
        if child.type == "identifier":
            return text(child, source)
    return ""


def _extract_blocking_calls(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    """Detect .Result, .Wait(), and .GetAwaiter().GetResult() patterns."""
    results: list[dict[str, Any]] = []

    for mae in find_nodes(root, "member_access_expression"):
        member_name = _rightmost_member(mae, source)

        if member_name == "Result":
            parent = mae.parent
            if parent is not None and parent.type == "invocation_expression":
                continue
            results.append(
                {
                    "expression": text(mae, source),
                    "call_type": ".Result",
                    "line": mae.start_point[0] + 1,
                    "file": rel_path,
                }
            )

    for inv in find_nodes(root, "invocation_expression"):
        func = inv.children[0] if inv.children else None
        if func is None or func.type != "member_access_expression":
            continue
        member_name = _rightmost_member(func, source)
        if member_name == "Wait":
            results.append(
                {
                    "expression": text(inv, source),
                    "call_type": ".Wait",
                    "line": inv.start_point[0] + 1,
                    "file": rel_path,
                }
            )
        elif member_name == "GetResult":
            results.append(
                {
                    "expression": text(inv, source),
                    "call_type": ".GetAwaiter",
                    "line": inv.start_point[0] + 1,
                    "file": rel_path,
                }
            )

    return results


class CSharpAstCollector(BaseASTCollector):
    name = "csharp-ast"
    version = "0.1.0"
    language = "csharp"
    file_extensions = (".cs",)
    evidence_kind = "csharp-ast-file"

    def _parse_file(self, source: bytes, rel_path: str) -> dict[str, Any]:
        tree = self._parser.parse(source)
        root = tree.root_node
        return {
            "catch_blocks": _extract_catch_blocks(root, source, rel_path),
            "log_statements": _extract_log_statements(root, source, rel_path),
            "methods": _extract_methods(root, source),
            "await_expressions": _extract_await_expressions(root, source, rel_path),
            "object_creations": _extract_object_creations(root, source, rel_path),
            "blocking_calls": _extract_blocking_calls(root, source, rel_path),
        }


def _register() -> None:
    if "csharp-ast" not in collector_registry:
        collector_registry.register("csharp-ast", CSharpAstCollector())


_register()

__all__ = ["CSharpAstCollector"]
