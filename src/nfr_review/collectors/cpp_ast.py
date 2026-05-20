"""C++ AST collector — parses .cpp/.cc/.cxx/.h/.hpp/.hxx files using
tree-sitter-cpp and emits per-file Evidence with structured payload for
downstream CPP-* rules.

Evidence payload contract (kind="cpp-ast-file"):
    file_path: str — path relative to repo_path
    functions: list[dict] — each with:
        name: str
        return_type: str
        line: int — 1-based line number
        is_noexcept: bool
    classes: list[dict] — each with:
        name: str
        line: int — 1-based line number
        has_destructor: bool
    namespaces: list[str] — namespace names found
    includes: list[dict] — each with:
        path: str — included file path
        is_system: bool — True for <...>, False for "..."
        line: int — 1-based line number
    new_expressions: list[dict] — each with:
        line: int
        file: str
        expression: str — new type or new[]
    delete_expressions: list[dict] — each with:
        line: int
        file: str
        expression: str
    smart_pointers: list[dict] — each with:
        kind: str — "unique_ptr", "shared_ptr", "weak_ptr"
        line: int
        file: str
    raw_pointers: list[dict] — each with:
        name: str
        line: int
        file: str
    malloc_calls: list[dict] — each with:
        call: str — "malloc", "calloc", "realloc", "free"
        line: int
        file: str
    catch_blocks: list[dict] — each with:
        caught_type: str
        rethrows: bool
        line: int
        file: str
    has_pragma_once: bool
    has_include_guard: bool
    log_statements: list[dict] — kept empty for contract compatibility
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tree_sitter import Node

from nfr_review.collectors.ast_common import BaseASTCollector, find_nodes, text
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.cpp_ast")

_SMART_PTR_TYPES = frozenset({"unique_ptr", "shared_ptr", "weak_ptr"})
_MALLOC_FUNCTIONS = frozenset({"malloc", "calloc", "realloc", "free"})
_INCLUDE_GUARD_RE = re.compile(r"^\s*#\s*ifndef\s+\w+", re.MULTILINE)
_PRAGMA_ONCE_RE = re.compile(r"^\s*#\s*pragma\s+once", re.MULTILINE)


def _extract_functions(root: Node, source: bytes) -> list[dict[str, Any]]:
    funcs: list[dict[str, Any]] = []
    for node in find_nodes(root, "function_definition"):
        name = ""
        return_type = ""
        is_noexcept = False
        declarator = node.child_by_field_name("declarator")
        if declarator:
            fn_decl: Node | None = declarator
            while fn_decl and fn_decl.type not in (
                "function_declarator",
                "identifier",
                "field_identifier",
                "qualified_identifier",
            ):
                fn_decl = fn_decl.children[0] if fn_decl.children else None
            if fn_decl and fn_decl.type == "function_declarator":
                for child in fn_decl.children:
                    if child.type in (
                        "identifier",
                        "field_identifier",
                        "qualified_identifier",
                    ):
                        name = text(child, source)
                        break
                    if child.type == "destructor_name":
                        name = text(child, source)
                        break
            elif fn_decl:
                name = text(fn_decl, source)
        type_node = node.child_by_field_name("type")
        if type_node:
            return_type = text(type_node, source)
        src_text = text(node, source)
        if "noexcept" in src_text:
            is_noexcept = True
        funcs.append(
            {
                "name": name,
                "return_type": return_type,
                "line": node.start_point[0] + 1,
                "is_noexcept": is_noexcept,
            }
        )
    return funcs


def _extract_classes(root: Node, source: bytes) -> list[dict[str, Any]]:
    classes: list[dict[str, Any]] = []
    for node_type in ("class_specifier", "struct_specifier"):
        for node in find_nodes(root, node_type):
            name_node = node.child_by_field_name("name")
            name = text(name_node, source) if name_node else ""
            has_destructor = False
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    child_text = text(child, source)
                    if "~" in child_text:
                        has_destructor = True
                        break
            classes.append(
                {
                    "name": name,
                    "line": node.start_point[0] + 1,
                    "has_destructor": has_destructor,
                }
            )
    return classes


def _extract_namespaces(root: Node, source: bytes) -> list[str]:
    names: list[str] = []
    for node in find_nodes(root, "namespace_definition"):
        name_node = node.child_by_field_name("name")
        if name_node:
            names.append(text(name_node, source))
    return names


def _extract_includes(root: Node, source: bytes) -> list[dict[str, Any]]:
    includes: list[dict[str, Any]] = []
    for node in find_nodes(root, "preproc_include"):
        path_node = node.child_by_field_name("path")
        if path_node:
            path_text = text(path_node, source)
            is_system = path_text.startswith("<")
            path_clean = path_text.strip('<>"')
            includes.append(
                {
                    "path": path_clean,
                    "is_system": is_system,
                    "line": node.start_point[0] + 1,
                }
            )
    return includes


def _extract_new_expressions(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node in find_nodes(root, "new_expression"):
        results.append(
            {
                "line": node.start_point[0] + 1,
                "file": rel_path,
                "expression": text(node, source).strip(),
            }
        )
    return results


def _extract_delete_expressions(
    root: Node, source: bytes, rel_path: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node in find_nodes(root, "delete_expression"):
        results.append(
            {
                "line": node.start_point[0] + 1,
                "file": rel_path,
                "expression": text(node, source).strip(),
            }
        )
    return results


def _extract_smart_pointers(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    src_text = source.decode("utf-8", errors="replace")
    for i, line in enumerate(src_text.splitlines(), start=1):
        for ptr_type in _SMART_PTR_TYPES:
            if ptr_type in line:
                results.append({"kind": ptr_type, "line": i, "file": rel_path})
    return results


def _extract_raw_pointers(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node in find_nodes(root, "pointer_declarator"):
        name = ""
        for child in node.children:
            if child.type == "identifier":
                name = text(child, source)
                break
            if child.type == "field_identifier":
                name = text(child, source)
                break
        results.append({"name": name, "line": node.start_point[0] + 1, "file": rel_path})
    return results


def _extract_malloc_calls(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node in find_nodes(root, "call_expression"):
        func = node.child_by_field_name("function")
        if func and func.type == "identifier":
            name = text(func, source)
            if name in _MALLOC_FUNCTIONS:
                results.append(
                    {
                        "call": name,
                        "line": node.start_point[0] + 1,
                        "file": rel_path,
                    }
                )
    return results


def _extract_catch_blocks(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for node in find_nodes(root, "catch_clause"):
        caught_type = ""
        params = node.child_by_field_name("parameters")
        if params:
            caught_type = text(params, source).strip("()")
        body = node.child_by_field_name("body")
        rethrows = False
        if body:
            for _stmt in find_nodes(body, "throw_statement"):
                rethrows = True
                break
        blocks.append(
            {
                "caught_type": caught_type.strip(),
                "rethrows": rethrows,
                "line": node.start_point[0] + 1,
                "file": rel_path,
            }
        )
    return blocks


def _detect_include_guard(source: bytes) -> tuple[bool, bool]:
    src_text = source.decode("utf-8", errors="replace")
    has_pragma = bool(_PRAGMA_ONCE_RE.search(src_text))
    has_guard = bool(_INCLUDE_GUARD_RE.search(src_text))
    return has_pragma, has_guard


class CppAstCollector(BaseASTCollector):
    name = "cpp-ast"
    version = "0.1.0"
    language = "cpp"
    file_extensions = (".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx")
    evidence_kind = "cpp-ast-file"

    def _parse_file(self, source: bytes, rel_path: str) -> dict[str, Any]:
        assert self._parser is not None
        tree = self._parser.parse(source)
        root = tree.root_node
        has_pragma, has_guard = _detect_include_guard(source)
        return {
            "functions": _extract_functions(root, source),
            "classes": _extract_classes(root, source),
            "namespaces": _extract_namespaces(root, source),
            "includes": _extract_includes(root, source),
            "new_expressions": _extract_new_expressions(root, source, rel_path),
            "delete_expressions": _extract_delete_expressions(root, source, rel_path),
            "smart_pointers": _extract_smart_pointers(root, source, rel_path),
            "raw_pointers": _extract_raw_pointers(root, source, rel_path),
            "malloc_calls": _extract_malloc_calls(root, source, rel_path),
            "catch_blocks": _extract_catch_blocks(root, source, rel_path),
            "has_pragma_once": has_pragma,
            "has_include_guard": has_guard,
            "log_statements": [],
        }


def _register() -> None:
    if "cpp-ast" not in collector_registry:
        collector_registry.register("cpp-ast", CppAstCollector())


_register()

__all__ = ["CppAstCollector"]
