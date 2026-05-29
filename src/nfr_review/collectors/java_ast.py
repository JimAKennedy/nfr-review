# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Java AST collector — parses .java files using tree-sitter-java and emits
per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="java-ast-file"):
    file_path: str — path relative to repo_path
    package: str — package name (e.g. "com.example.engine"), empty if none
    classes: list[dict] — each with:
        name: str
        line: int — 1-based line number of class/interface declaration
        annotations: list[str] — e.g. ["RestController", "Service"]
        is_abstract: bool — True for abstract classes and interfaces
        is_interface: bool — True for interface declarations
        base_classes: list[dict] — each with:
            name: str — e.g. "Plugin" or "Serializable"
            access: str — always "public" (Java has no access on inheritance)
        fields: list[dict] — each with:
            name: str
            type: str — e.g. "Config", "int", "List<Plugin>"
            access: str — "public", "protected", or "private"
            line: int — 1-based line number
        methods: list[dict] — each with:
            name: str
            annotations: list[str]
            return_type: str
            access: str — "public", "protected", or "private"
            is_virtual: bool — always False (Java concept N/A)
            is_pure_virtual: bool — True for abstract methods
            line: int — 1-based line number
            parameters: list[dict] — each with:
                name: str
                type: str
            mapping_paths: list[str] — path values from @*Mapping annotations
        namespace: str — package name (same as top-level package)
        outer_class: str — name of enclosing class if inner/nested, empty otherwise
    methods: list[dict] — top-level method list (same shape as class methods)
    catch_blocks: list[dict] — each with:
        caught_type: str — e.g. "Exception"
        rethrows: bool — whether the block contains a throw statement
        line: int — 1-based line number
    imports: list[str] — fully qualified import names
    thread_pool_constructions: list[dict] — each with:
        class_name: str — e.g. "ThreadPoolExecutor"
        line: int — 1-based line number
        has_bounded_queue: bool
        has_rejection_policy: bool
    log_statements: list[dict] — each with:
        method: str — e.g. "logger.info"
        arguments_text: str — full text of the argument list
        line: int — 1-based line number
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tree_sitter import Parser

from nfr_review.collectors.ast_common import make_parser
from nfr_review.models import Evidence
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.java_ast")

_MAPPING_ANNOTATIONS = frozenset(
    {
        "GetMapping",
        "PostMapping",
        "RequestMapping",
        "PutMapping",
        "DeleteMapping",
        "PatchMapping",
    }
)

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_THREAD_POOL_CLASSES = frozenset(
    {
        "ThreadPoolExecutor",
        "ThreadPoolTaskExecutor",
        "ScheduledThreadPoolExecutor",
    }
)

_BOUNDED_QUEUE_TYPES = frozenset(
    {
        "ArrayBlockingQueue",
        "LinkedBlockingQueue",
        "SynchronousQueue",
    }
)

_REJECTION_POLICY_TYPES = frozenset(
    {
        "CallerRunsPolicy",
        "AbortPolicy",
        "DiscardPolicy",
        "DiscardOldestPolicy",
    }
)


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _find_nodes(node: Any, target_type: str) -> list[Any]:
    results: list[Any] = []
    if node.type == target_type:
        results.append(node)
    for child in node.children:
        results.extend(_find_nodes(child, target_type))
    return results


def _extract_annotations(modifiers_node: Any, source: bytes) -> list[str]:
    annotations: list[str] = []
    for child in modifiers_node.children:
        if child.type in ("marker_annotation", "annotation"):
            for sub in child.children:
                if sub.type == "identifier":
                    annotations.append(_text(sub, source))
                    break
    return annotations


def _extract_mapping_paths(modifiers_node: Any, source: bytes) -> list[str]:
    paths: list[str] = []
    for child in modifiers_node.children:
        if child.type in ("marker_annotation", "annotation"):
            ann_name = ""
            for sub in child.children:
                if sub.type == "identifier":
                    ann_name = _text(sub, source)
                    break
            if ann_name not in _MAPPING_ANNOTATIONS:
                continue
            for sub in child.children:
                if sub.type == "annotation_argument_list":
                    for arg in sub.children:
                        if arg.type == "string_literal":
                            path_val = _text(arg, source).strip('"')
                            paths.append(path_val)
                        elif arg.type == "element_value_pair":
                            for ev in arg.children:
                                if ev.type == "string_literal":
                                    path_val = _text(ev, source).strip('"')
                                    paths.append(path_val)
                                elif ev.type == "element_value_array_initializer":
                                    for arr_child in ev.children:
                                        if arr_child.type == "string_literal":
                                            path_val = _text(arr_child, source).strip('"')
                                            paths.append(path_val)
    return paths


def _extract_return_type(method_node: Any, source: bytes) -> str:
    for child in method_node.children:
        if child.type in (
            "type_identifier",
            "void_type",
            "integral_type",
            "floating_point_type",
            "boolean_type",
            "generic_type",
            "array_type",
        ):
            return _text(child, source)
    return "void"


_ACCESS_KEYWORDS = frozenset({"public", "protected", "private"})


def _extract_access(modifiers_node: Any | None, source: bytes) -> str:
    if modifiers_node is None:
        return "private"
    for child in modifiers_node.children:
        if child.type in _ACCESS_KEYWORDS:
            return _text(child, source)
    return "private"


def _has_modifier(modifiers_node: Any | None, keyword: str) -> bool:
    if modifiers_node is None:
        return False
    return any(child.type == keyword for child in modifiers_node.children)


def _extract_type_node(node: Any, source: bytes) -> str:
    for child in node.children:
        if child.type in (
            "type_identifier",
            "void_type",
            "integral_type",
            "floating_point_type",
            "boolean_type",
            "generic_type",
            "array_type",
            "scoped_type_identifier",
        ):
            return _text(child, source)
    return ""


def _extract_parameters(method_node: Any, source: bytes) -> list[dict[str, str]]:
    params: list[dict[str, str]] = []
    for child in method_node.children:
        if child.type == "formal_parameters":
            for param in child.children:
                if param.type == "formal_parameter":
                    ptype = _extract_type_node(param, source)
                    pname = ""
                    for sub in param.children:
                        if sub.type == "identifier":
                            pname = _text(sub, source)
                    if pname:
                        params.append({"name": pname, "type": ptype})
    return params


def _extract_fields(class_body_node: Any, source: bytes) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for child in class_body_node.children:
        if child.type == "field_declaration":
            modifiers_node = None
            for sub in child.children:
                if sub.type == "modifiers":
                    modifiers_node = sub
                    break
            access = _extract_access(modifiers_node, source)
            ftype = _extract_type_node(child, source)
            for sub in child.children:
                if sub.type == "variable_declarator":
                    for var_child in sub.children:
                        if var_child.type == "identifier":
                            fields.append(
                                {
                                    "name": _text(var_child, source),
                                    "type": ftype,
                                    "access": access,
                                    "line": child.start_point[0] + 1,
                                }
                            )
                            break
    return fields


def _extract_base_classes(class_node: Any, source: bytes) -> list[dict[str, str]]:
    bases: list[dict[str, str]] = []
    for child in class_node.children:
        if child.type == "superclass":
            for sub in child.children:
                if sub.type in ("type_identifier", "generic_type", "scoped_type_identifier"):
                    bases.append({"name": _text(sub, source), "access": "public"})
        elif child.type in ("super_interfaces", "extends_interfaces"):
            for sub in child.children:
                if sub.type == "type_list":
                    for iface in sub.children:
                        if iface.type in (
                            "type_identifier",
                            "generic_type",
                            "scoped_type_identifier",
                        ):
                            bases.append({"name": _text(iface, source), "access": "public"})
    return bases


def _extract_package(root: Any, source: bytes) -> str:
    for child in root.children:
        if child.type == "package_declaration":
            for sub in child.children:
                if sub.type in ("scoped_identifier", "identifier"):
                    return _text(sub, source)
    return ""


def _extract_methods(class_body_node: Any, source: bytes) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    for child in class_body_node.children:
        if child.type == "method_declaration":
            name = ""
            annotations: list[str] = []
            mapping_paths: list[str] = []
            modifiers_node = None
            for sub in child.children:
                if sub.type == "identifier":
                    name = _text(sub, source)
                elif sub.type == "modifiers":
                    modifiers_node = sub
                    annotations = _extract_annotations(sub, source)
                    mapping_paths = _extract_mapping_paths(sub, source)
            access = _extract_access(modifiers_node, source)
            is_abstract = _has_modifier(modifiers_node, "abstract")
            return_type = _extract_return_type(child, source)
            parameters = _extract_parameters(child, source)
            methods.append(
                {
                    "name": name,
                    "annotations": annotations,
                    "return_type": return_type,
                    "access": access,
                    "is_virtual": False,
                    "is_pure_virtual": is_abstract,
                    "line": child.start_point[0] + 1,
                    "parameters": parameters,
                    "mapping_paths": mapping_paths,
                }
            )
    return methods


def _extract_catch_blocks(root: Any, source: bytes) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for catch_node in _find_nodes(root, "catch_clause"):
        caught_type = ""
        for param in _find_nodes(catch_node, "catch_formal_parameter"):
            for ct in _find_nodes(param, "catch_type"):
                for ti in ct.children:
                    if ti.type == "type_identifier":
                        caught_type = _text(ti, source)
                        break
            break
        rethrows = len(_find_nodes(catch_node, "throw_statement")) > 0
        line = catch_node.start_point[0] + 1
        blocks.append(
            {
                "caught_type": caught_type,
                "rethrows": rethrows,
                "line": line,
            }
        )
    return blocks


def _extract_imports(root: Any, source: bytes) -> list[str]:
    imports: list[str] = []
    for imp_node in _find_nodes(root, "import_declaration"):
        for child in imp_node.children:
            if child.type == "scoped_identifier":
                imports.append(_text(child, source))
                break
    return imports


def _oce_type_name(oce_node: Any, source: bytes) -> str:
    for child in oce_node.children:
        if child.type == "type_identifier":
            return _text(child, source)
        if child.type == "generic_type":
            for sub in child.children:
                if sub.type == "type_identifier":
                    return _text(sub, source)
    return ""


def _has_bounded_queue(args_node: Any, source: bytes) -> bool:
    for oce in _find_nodes(args_node, "object_creation_expression"):
        type_name = _oce_type_name(oce, source)
        if type_name in _BOUNDED_QUEUE_TYPES:
            arg_list = None
            for sub in oce.children:
                if sub.type == "argument_list":
                    arg_list = sub
                    break
            if type_name == "SynchronousQueue":
                return True
            if (
                arg_list
                and len([c for c in arg_list.children if c.type not in ("(", ")", ",")]) > 0
            ):
                return True
    return False


def _has_rejection_policy(args_node: Any, source: bytes) -> bool:
    full_text = _text(args_node, source)
    return any(rp in full_text for rp in _REJECTION_POLICY_TYPES)


def _extract_thread_pools(root: Any, source: bytes) -> list[dict[str, Any]]:
    pools: list[dict[str, Any]] = []
    for oce in _find_nodes(root, "object_creation_expression"):
        type_name = ""
        for child in oce.children:
            if child.type == "type_identifier":
                type_name = _text(child, source)
                break
        if type_name not in _THREAD_POOL_CLASSES:
            continue
        arg_list = None
        for child in oce.children:
            if child.type == "argument_list":
                arg_list = child
                break
        pools.append(
            {
                "class_name": type_name,
                "line": oce.start_point[0] + 1,
                "has_bounded_queue": _has_bounded_queue(arg_list, source)
                if arg_list
                else False,
                "has_rejection_policy": _has_rejection_policy(arg_list, source)
                if arg_list
                else False,
            }
        )
    return pools


_LOG_OBJECT_NAMES = frozenset({"log", "logger", "LOG", "LOGGER"})
_LOG_LEVEL_METHODS = frozenset({"info", "warn", "error", "debug", "trace"})
_STDOUT_OBJECTS = frozenset({"System.out", "System.err"})


def _extract_log_statements(root: Any, source: bytes) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    for mi in _find_nodes(root, "method_invocation"):
        children = mi.children
        identifiers = [c for c in children if c.type == "identifier"]

        if len(identifiers) >= 2:
            obj_name = _text(identifiers[0], source)
            method_name = _text(identifiers[1], source)
            if obj_name.lower() in {"log", "logger"} and method_name in _LOG_LEVEL_METHODS:
                arg_list = None
                for c in children:
                    if c.type == "argument_list":
                        arg_list = c
                        break
                arguments_text = _text(arg_list, source) if arg_list else ""
                statements.append(
                    {
                        "method": f"{obj_name}.{method_name}",
                        "arguments_text": arguments_text,
                        "line": mi.start_point[0] + 1,
                    }
                )
                continue

        if children and children[0].type == "field_access":
            obj_text = _text(children[0], source)
            if obj_text in _STDOUT_OBJECTS:
                method_ids = [c for c in children if c.type == "identifier"]
                if method_ids:
                    method_name = _text(method_ids[0], source)
                    arg_list = None
                    for c in children:
                        if c.type == "argument_list":
                            arg_list = c
                            break
                    statements.append(
                        {
                            "method": f"{obj_text}.{method_name}",
                            "arguments_text": _text(arg_list, source) if arg_list else "",
                            "line": mi.start_point[0] + 1,
                        }
                    )

    return statements


def _extract_class_or_interface(
    node: Any,
    source: bytes,
    *,
    is_interface: bool = False,
    outer_class: str = "",
    namespace: str = "",
) -> list[dict[str, Any]]:
    """Extract one class/interface and any inner classes it contains."""
    results: list[dict[str, Any]] = []

    class_name = ""
    annotations: list[str] = []
    modifiers_node = None
    for child in node.children:
        if child.type == "identifier":
            class_name = _text(child, source)
        elif child.type == "modifiers":
            modifiers_node = child
            annotations = _extract_annotations(child, source)

    is_abstract = is_interface or _has_modifier(modifiers_node, "abstract")
    base_classes = _extract_base_classes(node, source)

    body_type = "interface_body" if is_interface else "class_body"
    body_node = None
    for child in node.children:
        if child.type == body_type:
            body_node = child
            break

    methods: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    if body_node is not None:
        methods = _extract_methods(body_node, source)
        if not is_interface:
            fields = _extract_fields(body_node, source)
        else:
            for m in methods:
                m["access"] = "public"

    cls_dict: dict[str, Any] = {
        "name": class_name,
        "line": node.start_point[0] + 1,
        "annotations": annotations,
        "is_abstract": is_abstract,
        "is_interface": is_interface,
        "base_classes": base_classes,
        "fields": fields,
        "methods": methods,
        "namespace": namespace,
        "outer_class": outer_class,
    }
    results.append(cls_dict)

    if body_node is not None:
        for child in body_node.children:
            if child.type == "class_declaration":
                results.extend(
                    _extract_class_or_interface(
                        child,
                        source,
                        is_interface=False,
                        outer_class=class_name,
                        namespace=namespace,
                    )
                )
            elif child.type == "interface_declaration":
                results.extend(
                    _extract_class_or_interface(
                        child,
                        source,
                        is_interface=True,
                        outer_class=class_name,
                        namespace=namespace,
                    )
                )

    return results


def _parse_file(parser: Parser, source: bytes) -> dict[str, Any]:
    tree = parser.parse(source)
    root = tree.root_node

    package = _extract_package(root, source)
    imports = _extract_imports(root, source)
    catch_blocks = _extract_catch_blocks(root, source)
    thread_pools = _extract_thread_pools(root, source)
    log_statements = _extract_log_statements(root, source)

    classes: list[dict[str, Any]] = []
    all_methods: list[dict[str, Any]] = []

    for node in root.children:
        if node.type == "class_declaration":
            for cls in _extract_class_or_interface(
                node, source, is_interface=False, namespace=package
            ):
                classes.append(cls)
                all_methods.extend(cls["methods"])
        elif node.type == "interface_declaration":
            for cls in _extract_class_or_interface(
                node, source, is_interface=True, namespace=package
            ):
                classes.append(cls)
                all_methods.extend(cls["methods"])

    return {
        "package": package,
        "classes": classes,
        "methods": all_methods,
        "catch_blocks": catch_blocks,
        "imports": imports,
        "thread_pool_constructions": thread_pools,
        "log_statements": log_statements,
    }


class JavaAstCollector:
    name = "java-ast"
    version = "0.1.0"

    def __init__(self) -> None:
        self._parser: Parser | None = None

    def _get_parser(self) -> Parser | None:
        if self._parser is None:
            try:
                self._parser = make_parser("java")
            except (ImportError, ModuleNotFoundError):
                logger.warning(
                    "tree-sitter grammar for java not installed — java-ast collector disabled"
                )
                return None
        return self._parser

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        if self._get_parser() is None:
            return []
        exclude_pats = compile_exclude_patterns(getattr(config, "exclude_paths", []))
        exclude_test = getattr(config, "exclude_test_paths", True)
        evidence: list[Evidence] = []
        for java_file in sorted(repo_path.rglob("*.java")):
            rel = java_file.relative_to(repo_path)
            if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
                continue
            if should_exclude_path(
                str(rel),
                exclude_test_paths=exclude_test,
                exclude_patterns=exclude_pats or None,
            ):
                continue
            try:
                source = java_file.read_bytes()
            except OSError as exc:
                logger.debug("Cannot read %s: %s", rel, exc)
                continue
            try:
                payload = _parse_file(self._parser, source)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                logger.debug("Parse error in %s: %s", rel, exc)
                continue
            payload["file_path"] = str(rel)
            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=str(rel),
                    kind="java-ast-file",
                    payload=payload,
                )
            )
        return evidence


def _register() -> None:
    if "java-ast" not in collector_registry:
        collector_registry.register("java-ast", JavaAstCollector())


_register()

__all__ = ["JavaAstCollector"]
