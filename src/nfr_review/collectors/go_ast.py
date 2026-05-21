# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Go AST collector — parses .go files using tree-sitter and emits
per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="go-ast-file"):
    file_path: str — path relative to repo_path
    catch_blocks: list[dict] — each with:
        caught_type: str — always "" (Go recover is a bare catch-all)
        rethrows: bool — deferred function body contains panic() after recover
        line: int — 1-based line number of the recover() call
        file: str — relative file path
    log_statements: list[dict] — each with:
        method: str — e.g. "fmt.Println", "log.Printf"
        line: int — 1-based line number
        file: str — relative file path
    functions: list[dict] — each with:
        name: str
        line: int — 1-based
        receiver: str — receiver type or "" for plain functions
    error_assignments: list[dict] — each with:
        call: str — function/method name
        error_ignored: bool — True when _ appears in error position
        line: int — 1-based line number
        file: str — relative file path
    goroutine_launches: list[dict] — each with:
        expression: str — text of the go expression
        line: int — 1-based line number
        file: str — relative file path
    http_calls: list[dict] — each with:
        call: str — e.g. "http.Get", "http.Client"
        has_timeout: bool — only meaningful for Client literals
        line: int — 1-based line number
        file: str — relative file path
    defer_statements: list[dict] — each with:
        expression: str — text of the deferred expression
        in_loop: bool — True if inside a for statement
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

logger = logging.getLogger("nfr_review.collectors.go_ast")

_FMT_STDOUT_METHODS = frozenset({"Print", "Println", "Printf"})
_LOG_METHODS = frozenset(
    {"Print", "Println", "Printf", "Fatal", "Fatalf", "Fatalln", "Panic", "Panicf", "Panicln"}
)
_HTTP_DEFAULT_CLIENT_CALLS = frozenset({"Get", "Post", "Head", "PostForm"})

_ERROR_PATTERN_CALLS = frozenset(
    {
        "http.Get",
        "http.Post",
        "http.Head",
        "http.PostForm",
        "os.Open",
        "os.Create",
        "os.Remove",
        "os.Stat",
        "ioutil.ReadFile",
        "ioutil.ReadAll",
        "json.Marshal",
        "json.Unmarshal",
        "fmt.Fprintf",
        "fmt.Errorf",
        "strconv.Atoi",
    }
)


def _call_text(node: Node, source: bytes) -> str:
    """Extract the dotted call name from a call_expression's function child."""
    if node.type != "call_expression":
        return ""
    func = node.children[0] if node.children else None
    if func is None:
        return ""
    if func.type == "identifier":
        return text(func, source)
    if func.type == "selector_expression":
        return _selector_text(func, source)
    return ""


def _selector_text(node: Node, source: bytes) -> str:
    """Reconstruct dotted name from a selector_expression (e.g. http.Get)."""
    parts: list[str] = []
    for child in node.children:
        if child.type in (
            "identifier",
            "field_identifier",
            "package_identifier",
            "type_identifier",
        ):
            parts.append(text(child, source))
    return ".".join(parts)


def _is_inside_for(node: Node) -> bool:
    """Check if node has a for_statement ancestor."""
    parent = node.parent
    while parent is not None:
        if parent.type == "for_statement":
            return True
        parent = parent.parent
    return False


def _find_deferred_func_body(defer_node: Node) -> Node | None:
    """Find the func_literal block inside a defer statement, if any."""
    for call in find_nodes(defer_node, "call_expression"):
        for child in call.children:
            if child.type == "func_literal":
                for sub in child.children:
                    if sub.type == "block":
                        return sub
    return None


def _has_panic_call(block: Node, source: bytes) -> bool:
    """Check if a block contains a panic() call."""
    for call in find_nodes(block, "call_expression"):
        ct = _call_text(call, source)
        if ct == "panic":
            return True
    return False


def _extract_catch_blocks(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for recover_call in find_nodes(root, "call_expression"):
        if _call_text(recover_call, source) != "recover":
            continue
        defer_node = _find_enclosing_defer(recover_call)
        if defer_node is None:
            continue
        rethrows = False
        body = _find_deferred_func_body(defer_node)
        if body is not None:
            rethrows = _has_panic_call(body, source)
        blocks.append(
            {
                "caught_type": "",
                "rethrows": rethrows,
                "line": recover_call.start_point[0] + 1,
                "file": rel_path,
            }
        )
    return blocks


def _find_enclosing_defer(node: Node) -> Node | None:
    """Walk up to find an enclosing defer_statement."""
    parent = node.parent
    while parent is not None:
        if parent.type == "defer_statement":
            return parent
        parent = parent.parent
    return None


def _extract_log_statements(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    stmts: list[dict[str, Any]] = []
    for call in find_nodes(root, "call_expression"):
        name = _call_text(call, source)
        parts = name.split(".")
        if len(parts) == 2:
            pkg, method = parts
            if pkg == "fmt" and method in _FMT_STDOUT_METHODS:
                stmts.append(
                    {"method": name, "line": call.start_point[0] + 1, "file": rel_path}
                )
            elif pkg == "log" and method in _LOG_METHODS:
                stmts.append(
                    {"method": name, "line": call.start_point[0] + 1, "file": rel_path}
                )
    return stmts


def _extract_receiver_type(method_node: Node, source: bytes) -> str:
    """Extract receiver type from method_declaration's first parameter_list."""
    param_lists = [c for c in method_node.children if c.type == "parameter_list"]
    if not param_lists:
        return ""
    receiver_list = param_lists[0]
    for param in receiver_list.children:
        if param.type == "parameter_declaration":
            for child in param.children:
                if child.type == "pointer_type":
                    for sub in child.children:
                        if sub.type == "type_identifier":
                            return "*" + text(sub, source)
                elif child.type == "type_identifier":
                    return text(child, source)
    return ""


def _extract_functions(root: Node, source: bytes) -> list[dict[str, Any]]:
    funcs: list[dict[str, Any]] = []
    for node in find_nodes(root, "function_declaration"):
        name = ""
        for child in node.children:
            if child.type == "identifier":
                name = text(child, source)
                break
        funcs.append({"name": name, "line": node.start_point[0] + 1, "receiver": ""})

    for node in find_nodes(root, "method_declaration"):
        name = ""
        for child in node.children:
            if child.type == "field_identifier":
                name = text(child, source)
                break
        receiver = _extract_receiver_type(node, source)
        funcs.append({"name": name, "line": node.start_point[0] + 1, "receiver": receiver})

    return funcs


def _extract_error_assignments(
    root: Node, source: bytes, rel_path: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for node in find_nodes(root, "short_var_declaration"):
        lhs = None
        rhs = None
        for child in node.children:
            if child.type == "expression_list":
                if lhs is None:
                    lhs = child
                else:
                    rhs = child
        if lhs is None or rhs is None:
            continue
        identifiers = [c for c in lhs.children if c.type == "identifier"]
        if not identifiers:
            continue
        last_id = identifiers[-1]
        if text(last_id, source) != "_":
            continue
        calls = find_nodes(rhs, "call_expression")
        if not calls:
            continue
        call_name = _call_text(calls[0], source)
        results.append(
            {
                "call": call_name,
                "error_ignored": True,
                "line": node.start_point[0] + 1,
                "file": rel_path,
            }
        )

    for node in find_nodes(root, "assignment_statement"):
        lhs = None
        rhs = None
        for child in node.children:
            if child.type == "expression_list":
                if lhs is None:
                    lhs = child
                else:
                    rhs = child
        if lhs is None or rhs is None:
            continue
        identifiers = [c for c in lhs.children if c.type == "identifier"]
        if not identifiers:
            continue
        last_id = identifiers[-1]
        if text(last_id, source) != "_":
            continue
        calls = find_nodes(rhs, "call_expression")
        if not calls:
            continue
        call_name = _call_text(calls[0], source)
        results.append(
            {
                "call": call_name,
                "error_ignored": True,
                "line": node.start_point[0] + 1,
                "file": rel_path,
            }
        )

    for stmt in find_nodes(root, "expression_statement"):
        calls = find_nodes(stmt, "call_expression")
        if not calls:
            continue
        call_name = _call_text(calls[0], source)
        if call_name in _ERROR_PATTERN_CALLS:
            results.append(
                {
                    "call": call_name,
                    "error_ignored": True,
                    "line": stmt.start_point[0] + 1,
                    "file": rel_path,
                }
            )

    return results


def _extract_goroutine_launches(
    root: Node, source: bytes, rel_path: str
) -> list[dict[str, Any]]:
    launches: list[dict[str, Any]] = []
    for go_stmt in find_nodes(root, "go_statement"):
        expr_parts = [c for c in go_stmt.children if c.type != "go"]
        expr_text = " ".join(text(p, source) for p in expr_parts).strip()
        launches.append(
            {
                "expression": expr_text,
                "line": go_stmt.start_point[0] + 1,
                "file": rel_path,
            }
        )
    return launches


def _extract_http_calls(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for call in find_nodes(root, "call_expression"):
        name = _call_text(call, source)
        parts = name.split(".")
        if len(parts) == 2 and parts[0] == "http" and parts[1] in _HTTP_DEFAULT_CLIENT_CALLS:
            results.append(
                {
                    "call": name,
                    "has_timeout": False,
                    "line": call.start_point[0] + 1,
                    "file": rel_path,
                }
            )

    for lit in find_nodes(root, "composite_literal"):
        qt = None
        lv = None
        for child in lit.children:
            if child.type == "qualified_type":
                qt = child
            elif child.type == "literal_value":
                lv = child
        if qt is None:
            continue
        type_text = _selector_text(qt, source) if qt else ""
        if type_text != "http.Client":
            continue
        has_timeout = False
        if lv is not None:
            for elem in find_nodes(lv, "keyed_element"):
                for child in elem.children:
                    if child.type == "literal_element":
                        for sub in child.children:
                            if sub.type == "identifier" and text(sub, source) == "Timeout":
                                has_timeout = True
                                break
        results.append(
            {
                "call": "http.Client",
                "has_timeout": has_timeout,
                "line": lit.start_point[0] + 1,
                "file": rel_path,
            }
        )

    return results


def _extract_defer_statements(
    root: Node, source: bytes, rel_path: str
) -> list[dict[str, Any]]:
    defers: list[dict[str, Any]] = []
    for defer_node in find_nodes(root, "defer_statement"):
        expr_parts = [c for c in defer_node.children if c.type != "defer"]
        expr_text = " ".join(text(p, source) for p in expr_parts).strip()
        in_loop = _is_inside_for(defer_node)
        defers.append(
            {
                "expression": expr_text,
                "in_loop": in_loop,
                "line": defer_node.start_point[0] + 1,
                "file": rel_path,
            }
        )
    return defers


class GoAstCollector(BaseASTCollector):
    name = "go-ast"
    version = "0.1.0"
    language = "go"
    file_extensions = (".go",)
    evidence_kind = "go-ast-file"

    def _parse_file(self, source: bytes, rel_path: str) -> dict[str, Any]:
        assert self._parser is not None
        tree = self._parser.parse(source)
        root = tree.root_node
        return {
            "catch_blocks": _extract_catch_blocks(root, source, rel_path),
            "log_statements": _extract_log_statements(root, source, rel_path),
            "functions": _extract_functions(root, source),
            "error_assignments": _extract_error_assignments(root, source, rel_path),
            "goroutine_launches": _extract_goroutine_launches(root, source, rel_path),
            "http_calls": _extract_http_calls(root, source, rel_path),
            "defer_statements": _extract_defer_statements(root, source, rel_path),
        }


def _register() -> None:
    if "go-ast" not in collector_registry:
        collector_registry.register("go-ast", GoAstCollector())


_register()

__all__ = ["GoAstCollector"]
