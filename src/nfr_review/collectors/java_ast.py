"""Java AST collector — parses .java files using tree-sitter-java and emits
per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="java-ast-file"):
    file_path: str — path relative to repo_path
    classes: list[dict] — each with:
        name: str
        annotations: list[str] — e.g. ["RestController", "Service"]
        methods: list[dict] — each with:
            name: str
            annotations: list[str]
            return_type: str
            mapping_paths: list[str] — path values from @*Mapping annotations
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
from typing import Any

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser

from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.java_ast")

_LANG = Language(tsjava.language())

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


def _extract_methods(class_body_node: Any, source: bytes) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    for child in class_body_node.children:
        if child.type == "method_declaration":
            name = ""
            annotations: list[str] = []
            mapping_paths: list[str] = []
            for sub in child.children:
                if sub.type == "identifier":
                    name = _text(sub, source)
                elif sub.type == "modifiers":
                    annotations = _extract_annotations(sub, source)
                    mapping_paths = _extract_mapping_paths(sub, source)
            return_type = _extract_return_type(child, source)
            methods.append(
                {
                    "name": name,
                    "annotations": annotations,
                    "return_type": return_type,
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


def _extract_log_statements(root: Any, source: bytes) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    for mi in _find_nodes(root, "method_invocation"):
        children = mi.children
        identifiers = [c for c in children if c.type == "identifier"]
        if len(identifiers) < 2:
            continue
        obj_name = _text(identifiers[0], source)
        method_name = _text(identifiers[1], source)
        if obj_name.lower() not in {"log", "logger"} or method_name not in _LOG_LEVEL_METHODS:
            continue
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
    return statements


def _parse_file(parser: Parser, source: bytes) -> dict[str, Any]:
    tree = parser.parse(source)
    root = tree.root_node

    imports = _extract_imports(root, source)
    catch_blocks = _extract_catch_blocks(root, source)
    thread_pools = _extract_thread_pools(root, source)
    log_statements = _extract_log_statements(root, source)

    classes: list[dict[str, Any]] = []
    all_methods: list[dict[str, Any]] = []

    for node in _find_nodes(root, "class_declaration"):
        class_name = ""
        class_annotations: list[str] = []
        for child in node.children:
            if child.type == "identifier":
                class_name = _text(child, source)
            elif child.type == "modifiers":
                class_annotations = _extract_annotations(child, source)
        methods: list[dict[str, Any]] = []
        for child in node.children:
            if child.type == "class_body":
                methods = _extract_methods(child, source)
                break
        classes.append(
            {
                "name": class_name,
                "annotations": class_annotations,
                "methods": methods,
            }
        )
        all_methods.extend(methods)

    return {
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
        self._parser = Parser(_LANG)

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        for java_file in sorted(repo_path.rglob("*.java")):
            rel = java_file.relative_to(repo_path)
            if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
                continue
            try:
                source = java_file.read_bytes()
            except OSError as exc:
                logger.warning("Cannot read %s: %s", rel, exc)
                continue
            try:
                payload = _parse_file(self._parser, source)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Parse error in %s: %s", rel, exc)
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
