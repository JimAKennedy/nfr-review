"""Python AST collector — parses .py files using tree-sitter and emits
per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="python-ast-file"):
    file_path: str — path relative to repo_path
    catch_blocks: list[dict] — each with:
        caught_type: str — e.g. 'Exception', '' for bare except
        rethrows: bool — handler contains raise
        has_logging: bool — handler contains logging/print call
        line: int — 1-based line number
        file: str — relative file path
    log_statements: list[dict] — each with:
        method: str — e.g. 'print'
        line: int — 1-based line number
        file: str — relative file path
    functions: list[dict] — each with:
        name: str
        line: int — 1-based
        is_async: bool
        decorators: list[str]
        default_args: list[dict] — each with:
            name: str
            default_type: str — 'list'/'dict'/'set' for mutable, 'other'
            line: int — 1-based
    imports: list[dict] — each with:
        module: str
        names: list[str]
        is_star: bool
        line: int — 1-based
    async_calls: list[dict] — each with:
        call: str — e.g. 'asyncio.create_task'
        line: int — 1-based
        stored: bool — whether return value is assigned
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tree_sitter import Node

from nfr_review.collectors.ast_common import BaseASTCollector, find_nodes, text
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.python_ast")

_LOGGING_CALL_NAMES = frozenset({"print"})
_LOGGING_ATTR_PREFIXES = frozenset({"sys.stdout.write", "sys.stderr.write"})

_ASYNC_FIRE_FORGET_CALLS = frozenset(
    {
        "asyncio.create_task",
        "asyncio.ensure_future",
        "loop.create_task",
    }
)


def _call_name(call_node: Node, source: bytes) -> str:
    """Extract the dotted call name from a call node's function child."""
    for child in call_node.children:
        if child.type == "identifier":
            return text(child, source)
        if child.type == "attribute":
            return _attribute_text(child, source)
    return ""


def _attribute_text(attr_node: Node, source: bytes) -> str:
    """Reconstruct dotted name from nested attribute nodes."""
    parts: list[str] = []
    node = attr_node
    while node.type == "attribute":
        for child in reversed(node.children):
            if child.type == "identifier":
                parts.append(text(child, source))
                break
        obj = node.children[0] if node.children else None
        if obj is None:
            break
        if obj.type == "identifier":
            parts.append(text(obj, source))
            break
        if obj.type == "attribute":
            node = obj
        else:
            break
    parts.reverse()
    return ".".join(parts)


def _has_logging_call(block_node: Node, source: bytes) -> bool:
    """Check if a block contains any logging/print call."""
    for call_node in find_nodes(block_node, "call"):
        name = _call_name(call_node, source)
        if name in _LOGGING_CALL_NAMES:
            return True
        if name in _LOGGING_ATTR_PREFIXES:
            return True
        parts = name.split(".")
        if len(parts) == 2 and parts[0] in ("logging", "logger", "log", "LOGGER", "LOG"):
            return True
    return False


def _extract_catch_blocks(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for exc_clause in find_nodes(root, "except_clause"):
        caught_type = ""
        for child in exc_clause.children:
            if child.type == "as_pattern":
                for sub in child.children:
                    if sub.type == "identifier":
                        caught_type = text(sub, source)
                        break
                break
            if child.type == "identifier":
                caught_type = text(child, source)
                break

        rethrows = len(find_nodes(exc_clause, "raise_statement")) > 0

        block_node = None
        for child in exc_clause.children:
            if child.type == "block":
                block_node = child
                break
        has_logging = _has_logging_call(block_node, source) if block_node else False

        blocks.append(
            {
                "caught_type": caught_type,
                "rethrows": rethrows,
                "has_logging": has_logging,
                "line": exc_clause.start_point[0] + 1,
                "file": rel_path,
            }
        )
    return blocks


def _extract_log_statements(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    stmts: list[dict[str, Any]] = []
    for call_node in find_nodes(root, "call"):
        name = _call_name(call_node, source)
        if name in _LOGGING_CALL_NAMES or name in _LOGGING_ATTR_PREFIXES:
            stmts.append(
                {
                    "method": name,
                    "line": call_node.start_point[0] + 1,
                    "file": rel_path,
                }
            )
    return stmts


def _classify_default(value_node: Node, source: bytes) -> str:
    if value_node.type == "list":
        return "list"
    if value_node.type == "dictionary":
        return "dict"
    if value_node.type == "set":
        return "set"
    if value_node.type == "call":
        func_name = _call_name(value_node, source)
        if func_name in ("list", "dict", "set"):
            return func_name
    return "other"


def _extract_decorators(node: Node, source: bytes) -> list[str]:
    decorators: list[str] = []
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type == "decorator":
                for sub in child.children:
                    if sub.type == "identifier":
                        decorators.append(text(sub, source))
                        break
                    if sub.type == "attribute":
                        decorators.append(_attribute_text(sub, source))
                        break
                    if sub.type == "call":
                        decorators.append(_call_name(sub, source))
                        break
    return decorators


def _extract_functions(root: Node, source: bytes) -> list[dict[str, Any]]:
    funcs: list[dict[str, Any]] = []

    def _process_func(func_node: Node, decorators: list[str]) -> None:
        name = ""
        is_async = False
        default_args: list[dict[str, Any]] = []

        for child in func_node.children:
            if child.type == "identifier" and not name:
                name = text(child, source)
            elif child.type == "async":
                is_async = True
            elif child.type == "parameters":
                for param in child.children:
                    if param.type == "default_parameter":
                        param_name = ""
                        for sub in param.children:
                            if sub.type == "identifier" and not param_name:
                                param_name = text(sub, source)
                            elif sub.type not in ("=", "identifier"):
                                dtype = _classify_default(sub, source)
                                default_args.append(
                                    {
                                        "name": param_name,
                                        "default_type": dtype,
                                        "line": param.start_point[0] + 1,
                                    }
                                )
                                break

        funcs.append(
            {
                "name": name,
                "line": func_node.start_point[0] + 1,
                "is_async": is_async,
                "decorators": decorators,
                "default_args": default_args,
            }
        )

    for node in root.children:
        if node.type == "function_definition":
            _process_func(node, [])
        elif node.type == "decorated_definition":
            decorators = _extract_decorators(node, source)
            for child in node.children:
                if child.type == "function_definition":
                    _process_func(child, decorators)

    for class_node in find_nodes(root, "class_definition"):
        for child in class_node.children:
            if child.type == "block":
                for member in child.children:
                    if member.type == "function_definition":
                        _process_func(member, [])
                    elif member.type == "decorated_definition":
                        decorators = _extract_decorators(member, source)
                        for sub in member.children:
                            if sub.type == "function_definition":
                                _process_func(sub, decorators)

    return funcs


def _extract_imports(root: Node, source: bytes) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []
    for node in root.children:
        if node.type == "import_from_statement":
            module = ""
            names: list[str] = []
            is_star = False
            for child in node.children:
                if child.type == "dotted_name":
                    if not module:
                        module = text(child, source)
                    else:
                        names.append(text(child, source))
                elif child.type == "wildcard_import":
                    is_star = True
            imports.append(
                {
                    "module": module,
                    "names": names,
                    "is_star": is_star,
                    "line": node.start_point[0] + 1,
                }
            )
        elif node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    imports.append(
                        {
                            "module": text(child, source),
                            "names": [],
                            "is_star": False,
                            "line": node.start_point[0] + 1,
                        }
                    )
    return imports


def _is_stored(call_node: Node) -> bool:
    """Check whether the call's return value is stored in a variable."""
    parent = call_node.parent
    if parent is None:
        return False
    if parent.type == "assignment":
        return True
    if parent.type == "augmented_assignment":
        return True
    return False


def _extract_async_calls(root: Node, source: bytes) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for call_node in find_nodes(root, "call"):
        name = _call_name(call_node, source)
        if name in _ASYNC_FIRE_FORGET_CALLS:
            calls.append(
                {
                    "call": name,
                    "line": call_node.start_point[0] + 1,
                    "stored": _is_stored(call_node),
                }
            )
    return calls


class PythonAstCollector(BaseASTCollector):
    name = "python-ast"
    version = "0.1.0"
    language = "python"
    file_extensions = (".py",)
    evidence_kind = "python-ast-file"

    def _parse_file(self, source: bytes, rel_path: str) -> dict[str, Any]:
        tree = self._parser.parse(source)
        root = tree.root_node
        return {
            "catch_blocks": _extract_catch_blocks(root, source, rel_path),
            "log_statements": _extract_log_statements(root, source, rel_path),
            "functions": _extract_functions(root, source),
            "imports": _extract_imports(root, source),
            "async_calls": _extract_async_calls(root, source),
        }


def _register() -> None:
    if "python-ast" not in collector_registry:
        collector_registry.register("python-ast", PythonAstCollector())


_register()

__all__ = ["PythonAstCollector"]
