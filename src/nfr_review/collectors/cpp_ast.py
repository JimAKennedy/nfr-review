# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
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
        is_struct: bool
        base_classes: list[dict] — each with name: str, access: str
        methods: list[dict] — each with name, return_type, access,
            is_virtual, is_pure_virtual, line
        fields: list[dict] — each with name, type, access, line
        is_abstract: bool — True when any method is pure virtual
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


def _extract_base_classes(node: Node, source: bytes) -> list[dict[str, str]]:
    """Extract base classes from a class/struct specifier node."""
    bases: list[dict[str, str]] = []
    for child in node.children:
        if child.type == "base_class_clause":
            current_access = "private"
            for bc_child in child.children:
                if bc_child.type == "access_specifier":
                    current_access = text(bc_child, source).strip()
                elif bc_child.type in ("type_identifier", "qualified_identifier"):
                    bases.append({"name": text(bc_child, source), "access": current_access})
            break
    return bases


def _extract_members(
    body: Node, source: bytes, is_struct: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Extract methods, fields, and destructor presence from a class body.

    Returns (methods, fields, has_destructor).
    """
    methods: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    has_destructor = False
    current_access = "public" if is_struct else "private"

    for child in body.children:
        if child.type == "access_specifier":
            current_access = text(child, source).strip().rstrip(":")
            continue

        if child.type == "function_definition":
            decl = child.child_by_field_name("declarator")
            if decl and "~" in text(decl, source):
                has_destructor = True
            fname = _member_func_name(decl, source) if decl else ""
            rtype = ""
            type_node = child.child_by_field_name("type")
            if type_node:
                rtype = text(type_node, source)
            is_virtual = "virtual" in text(child, source).split("(")[0]
            methods.append(
                {
                    "name": fname,
                    "return_type": rtype,
                    "access": current_access,
                    "is_virtual": is_virtual,
                    "is_pure_virtual": False,
                    "line": child.start_point[0] + 1,
                }
            )
            continue

        if child.type == "field_declaration":
            decl = child.child_by_field_name("declarator")
            if decl and _has_function_declarator(decl):
                fname = _member_func_name(decl, source)
                if "~" in fname:
                    has_destructor = True
                    continue
                rtype = ""
                type_node = child.child_by_field_name("type")
                if type_node:
                    rtype = text(type_node, source)
                child_text = text(child, source)
                is_virtual = child_text.lstrip().startswith("virtual")
                is_pure = is_virtual and "= 0" in child_text
                methods.append(
                    {
                        "name": fname,
                        "return_type": rtype,
                        "access": current_access,
                        "is_virtual": is_virtual,
                        "is_pure_virtual": is_pure,
                        "line": child.start_point[0] + 1,
                    }
                )
            elif decl:
                field_name = ""
                if decl.type in ("field_identifier", "identifier"):
                    field_name = text(decl, source)
                elif decl.type == "pointer_declarator":
                    for dc in decl.children:
                        if dc.type in ("field_identifier", "identifier"):
                            field_name = text(dc, source)
                            break
                ftype = ""
                type_node = child.child_by_field_name("type")
                if type_node:
                    ftype = text(type_node, source)
                if field_name:
                    fields.append(
                        {
                            "name": field_name,
                            "type": ftype,
                            "access": current_access,
                            "line": child.start_point[0] + 1,
                        }
                    )

    return methods, fields, has_destructor


def _member_func_name(declarator: Node, source: bytes) -> str:
    """Extract function name from a declarator node."""
    func_decl = _find_descendant(declarator, "function_declarator")
    if func_decl:
        for child in func_decl.children:
            if child.type in ("identifier", "field_identifier", "qualified_identifier"):
                return text(child, source)
            if child.type == "destructor_name":
                return text(child, source)
    if declarator.type in ("identifier", "field_identifier"):
        return text(declarator, source)
    return ""


def _find_descendant(node: Node, target_type: str) -> Node | None:
    """Find the first descendant of a specific type (BFS)."""
    if node.type == target_type:
        return node
    for child in node.children:
        result = _find_descendant(child, target_type)
        if result:
            return result
    return None


def _has_function_declarator(node: Node) -> bool:
    """Check if a node contains a function_declarator anywhere."""
    if node.type == "function_declarator":
        return True
    for child in node.children:
        if _has_function_declarator(child):
            return True
    return False


def _extract_classes(root: Node, source: bytes) -> list[dict[str, Any]]:
    classes: list[dict[str, Any]] = []
    for node_type in ("class_specifier", "struct_specifier"):
        is_struct = node_type == "struct_specifier"
        for node in find_nodes(root, node_type):
            name_node = node.child_by_field_name("name")
            name = text(name_node, source) if name_node else ""
            base_classes = _extract_base_classes(node, source)
            has_destructor = False
            methods: list[dict[str, Any]] = []
            fields: list[dict[str, Any]] = []
            body = node.child_by_field_name("body")
            if body:
                methods, fields, has_destructor = _extract_members(body, source, is_struct)
            has_pure_virtual = any(m.get("is_pure_virtual") for m in methods)
            classes.append(
                {
                    "name": name,
                    "line": node.start_point[0] + 1,
                    "has_destructor": has_destructor,
                    "is_struct": is_struct,
                    "base_classes": base_classes,
                    "methods": methods,
                    "fields": fields,
                    "is_abstract": has_pure_virtual,
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
