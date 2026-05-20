"""Node.js/TypeScript AST collector — parses .js/.ts/.jsx/.tsx files using
tree-sitter's TypeScript grammar (which parses plain JS as a superset).

Evidence payload contract (kind="nodejs-ast-file"):
    file_path: str — path relative to repo_path
    catch_blocks: list[dict] — each with:
        caught_type: str — always '' (JS has no typed catch clauses)
        rethrows: bool — block contains throw statement
        has_logging: bool — block contains console.log/warn/error call
        line: int — 1-based line number
        file: str — relative file path
    log_statements: list[dict] — each with:
        method: str — e.g. 'console.log', 'process.stdout.write'
        line: int — 1-based line number
        file: str — relative file path
    functions: list[dict] — each with:
        name: str
        line: int — 1-based
        is_async: bool
        kind: str — 'function' | 'arrow' | 'method'
    await_expressions: list[dict] — each with:
        expression: str — text of the awaited expression
        line: int — 1-based line number
        file: str — relative file path
    promise_chains: list[dict] — each with:
        expression: str — text of the .then() chain
        has_catch: bool — whether chain ends with .catch()
        line: int — 1-based line number
        file: str — relative file path
    sync_calls: list[dict] — each with:
        method: str — e.g. 'fs.readFileSync'
        line: int — 1-based line number
        file: str — relative file path
    callback_patterns: list[dict] — each with:
        function_name: str — the called function name
        callback_param: str — the error parameter name
        checks_error: bool — whether the callback body checks the error
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

logger = logging.getLogger("nfr_review.collectors.nodejs_ast")

_CONSOLE_METHODS = frozenset({"log", "warn", "error", "info"})

_SYNC_METHODS = frozenset(
    {
        "readFileSync",
        "writeFileSync",
        "appendFileSync",
        "execSync",
        "spawnSync",
    }
)

_ERROR_PARAM_NAMES = frozenset({"err", "error", "e"})


def _member_text(node: Node, source: bytes) -> tuple[str, str]:
    """Extract (object, property) from a member_expression."""
    obj = ""
    prop = ""
    for child in node.children:
        if child.type == "identifier":
            obj = text(child, source)
        elif child.type == "property_identifier":
            prop = text(child, source)
        elif child.type == "member_expression":
            inner_obj, inner_prop = _member_text(child, source)
            obj = f"{inner_obj}.{inner_prop}" if inner_obj else inner_prop
    return obj, prop


def _call_name(node: Node, source: bytes) -> str:
    """Extract dotted call name from a call_expression."""
    if node.type != "call_expression":
        return ""
    func = node.children[0] if node.children else None
    if func is None:
        return ""
    if func.type == "identifier":
        return text(func, source)
    if func.type == "member_expression":
        obj, prop = _member_text(func, source)
        return f"{obj}.{prop}" if obj else prop
    return ""


def _has_logging_call(block: Node, source: bytes) -> bool:
    """Check if a block contains console logging calls."""
    for call in find_nodes(block, "call_expression"):
        name = _call_name(call, source)
        parts = name.split(".")
        if len(parts) == 2 and parts[0] == "console" and parts[1] in _CONSOLE_METHODS:
            return True
    return False


def _extract_catch_blocks(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for catch in find_nodes(root, "catch_clause"):
        rethrows = len(find_nodes(catch, "throw_statement")) > 0

        block_node = None
        for child in catch.children:
            if child.type == "statement_block":
                block_node = child
                break
        has_logging = _has_logging_call(block_node, source) if block_node else False

        blocks.append(
            {
                "caught_type": "",
                "rethrows": rethrows,
                "has_logging": has_logging,
                "line": catch.start_point[0] + 1,
                "file": rel_path,
            }
        )
    return blocks


_PROCESS_LOG_NAMES = frozenset({"process.stdout.write", "process.stderr.write"})


def _extract_log_statements(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    stmts: list[dict[str, Any]] = []
    for call in find_nodes(root, "call_expression"):
        name = _call_name(call, source)
        is_log = False
        if name in _PROCESS_LOG_NAMES:
            is_log = True
        else:
            parts = name.split(".")
            if len(parts) == 2 and parts[0] == "console" and parts[1] in _CONSOLE_METHODS:
                is_log = True
        if is_log:
            stmts.append({"method": name, "line": call.start_point[0] + 1, "file": rel_path})
    return stmts


def _extract_functions(root: Node, source: bytes) -> list[dict[str, Any]]:
    functions: list[dict[str, Any]] = []

    for func in find_nodes(root, "function_declaration"):
        name = ""
        is_async = False
        for child in func.children:
            if child.type == "identifier":
                name = text(child, source)
            elif child.type == "async":
                is_async = True
        functions.append(
            {
                "name": name,
                "line": func.start_point[0] + 1,
                "is_async": is_async,
                "kind": "function",
            }
        )

    for method in find_nodes(root, "method_definition"):
        name = ""
        is_async = False
        for child in method.children:
            if child.type == "property_identifier":
                name = text(child, source)
            elif child.type == "async":
                is_async = True
        functions.append(
            {
                "name": name,
                "line": method.start_point[0] + 1,
                "is_async": is_async,
                "kind": "method",
            }
        )

    for arrow in find_nodes(root, "arrow_function"):
        is_async = any(c.type == "async" for c in arrow.children)
        name = ""
        parent = arrow.parent
        if parent is not None and parent.type == "variable_declarator":
            for child in parent.children:
                if child.type == "identifier":
                    name = text(child, source)
                    break
        functions.append(
            {
                "name": name,
                "line": arrow.start_point[0] + 1,
                "is_async": is_async,
                "kind": "arrow",
            }
        )

    return functions


def _extract_await_expressions(
    root: Node, source: bytes, rel_path: str
) -> list[dict[str, Any]]:
    awaits: list[dict[str, Any]] = []
    for await_node in find_nodes(root, "await_expression"):
        expr_text = ""
        for child in await_node.children:
            if child.type != "await":
                expr_text = text(child, source)
                break
        awaits.append(
            {
                "expression": expr_text,
                "line": await_node.start_point[0] + 1,
                "file": rel_path,
            }
        )
    return awaits


def _is_then_or_catch(node: Node, source: bytes) -> tuple[bool, str]:
    """Check if a call is .then() or .catch(). Returns (is_match, name)."""
    if node.type != "call_expression":
        return False, ""
    func = node.children[0] if node.children else None
    if func is None or func.type != "member_expression":
        return False, ""
    for child in func.children:
        if child.type == "property_identifier":
            prop = text(child, source)
            if prop in ("then", "catch"):
                return True, prop
    return False, ""


def _node_key(node: Node) -> tuple[int, int]:
    return (node.start_byte, node.end_byte)


def _extract_promise_chains(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    """Detect .then() chains and whether they have a .catch()."""
    chains: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()

    for call in find_nodes(root, "call_expression"):
        is_tc, method = _is_then_or_catch(call, source)
        if not is_tc or method != "then":
            continue
        if _node_key(call) in seen:
            continue

        outermost = call
        has_catch = False
        current = call.parent
        while current is not None:
            if current.type == "call_expression":
                is_tc2, method2 = _is_then_or_catch(current, source)
                if is_tc2:
                    outermost = current
                    if method2 == "catch":
                        has_catch = True
                else:
                    break
            elif current.type == "member_expression":
                current = current.parent
                continue
            else:
                break
            current = current.parent

        key = _node_key(outermost)
        if key in seen:
            continue
        seen.add(key)
        seen.add(_node_key(call))
        chains.append(
            {
                "expression": text(outermost, source),
                "has_catch": has_catch,
                "line": outermost.start_point[0] + 1,
                "file": rel_path,
            }
        )

    return chains


def _extract_sync_calls(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for call in find_nodes(root, "call_expression"):
        name = _call_name(call, source)
        parts = name.split(".")
        if len(parts) == 2 and parts[1] in _SYNC_METHODS:
            results.append(
                {
                    "method": name,
                    "line": call.start_point[0] + 1,
                    "file": rel_path,
                }
            )
    return results


def _get_first_param_name(params_node: Node, source: bytes) -> str:
    """Get the name of the first parameter from formal_parameters."""
    for child in params_node.children:
        if child.type == "required_parameter":
            for sub in child.children:
                if sub.type == "identifier":
                    return text(sub, source)
        elif child.type == "identifier":
            return text(child, source)
    return ""


def _checks_error_param(block: Node, param_name: str, source: bytes) -> bool:
    """Check if a block contains an if statement referencing the error param."""
    for if_stmt in find_nodes(block, "if_statement"):
        for child in if_stmt.children:
            if child.type == "parenthesized_expression":
                if param_name in text(child, source):
                    return True
    return False


_PROMISE_METHODS = frozenset({"then", "catch", "finally"})


def _extract_callback_patterns(
    root: Node, source: bytes, rel_path: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for call in find_nodes(root, "call_expression"):
        func_name = _call_name(call, source)
        if not func_name or func_name in _PROMISE_METHODS:
            continue

        args_node = None
        for child in call.children:
            if child.type == "arguments":
                args_node = child
                break
        if args_node is None:
            continue

        cb_nodes = [
            c
            for c in args_node.children
            if c.type in ("function_expression", "arrow_function")
        ]
        if not cb_nodes:
            continue

        cb = cb_nodes[-1]
        params_node = None
        for child in cb.children:
            if child.type == "formal_parameters":
                params_node = child
                break
            elif child.type == "identifier" and cb.type == "arrow_function":
                first_param = text(child, source)
                if first_param in _ERROR_PARAM_NAMES:
                    block = None
                    for c2 in cb.children:
                        if c2.type == "statement_block":
                            block = c2
                            break
                    checks = (
                        _checks_error_param(block, first_param, source) if block else False
                    )
                    results.append(
                        {
                            "function_name": func_name,
                            "callback_param": first_param,
                            "checks_error": checks,
                            "line": call.start_point[0] + 1,
                            "file": rel_path,
                        }
                    )
                params_node = None
                break

        if params_node is None:
            continue

        first_param = _get_first_param_name(params_node, source)
        if first_param not in _ERROR_PARAM_NAMES:
            continue

        block = None
        for child in cb.children:
            if child.type == "statement_block":
                block = child
                break

        checks = _checks_error_param(block, first_param, source) if block else False
        results.append(
            {
                "function_name": func_name,
                "callback_param": first_param,
                "checks_error": checks,
                "line": call.start_point[0] + 1,
                "file": rel_path,
            }
        )

    return results


class NodejsAstCollector(BaseASTCollector):
    name = "nodejs-ast"
    version = "0.1.0"
    language = "typescript"
    file_extensions = (".js", ".ts", ".jsx", ".tsx")
    evidence_kind = "nodejs-ast-file"

    def _parse_file(self, source: bytes, rel_path: str) -> dict[str, Any]:
        assert self._parser is not None
        tree = self._parser.parse(source)
        root = tree.root_node
        return {
            "catch_blocks": _extract_catch_blocks(root, source, rel_path),
            "log_statements": _extract_log_statements(root, source, rel_path),
            "functions": _extract_functions(root, source),
            "await_expressions": _extract_await_expressions(root, source, rel_path),
            "promise_chains": _extract_promise_chains(root, source, rel_path),
            "sync_calls": _extract_sync_calls(root, source, rel_path),
            "callback_patterns": _extract_callback_patterns(root, source, rel_path),
        }


def _register() -> None:
    if "nodejs-ast" not in collector_registry:
        collector_registry.register("nodejs-ast", NodejsAstCollector())


_register()

__all__ = ["NodejsAstCollector"]
