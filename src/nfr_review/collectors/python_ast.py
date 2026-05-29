# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Python AST collector — parses .py files using tree-sitter and emits
per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="python-ast-file"):
    file_path: str — path relative to repo_path
    module_path: str — dotted module path derived from file path
    classes: list[dict] — each with:
        name: str
        line: int — 1-based
        is_abstract: bool — True when class inherits ABC or uses @abstractmethod
        is_interface: bool — True when class inherits Protocol
        base_classes: list[dict] — each with:
            name: str — e.g. "ABC", "Plugin"
            access: str — always "public" (Python has no access on inheritance)
        fields: list[dict] — each with:
            name: str
            type: str — annotation type or ""
            access: str — "public"/"private" per _ naming convention
            line: int — 1-based
        methods: list[dict] — each with:
            name: str
            return_type: str — annotation type or ""
            access: str — "public"/"private" per _ naming convention
            is_virtual: bool — always False
            is_pure_virtual: bool — True for @abstractmethod
            line: int — 1-based
            parameters: list[dict] — each with:
                name: str
                type: str
            decorators: list[str]
        namespace: str — dotted module path
        outer_class: str — name of enclosing class if nested, empty otherwise
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


def _caught_type_from_node(node: Node, source: bytes) -> str:
    """Extract the caught exception type string from a tree-sitter node."""
    if node.type in ("identifier", "attribute"):
        return text(node, source)
    if node.type == "tuple":
        parts = [
            text(c, source) for c in node.children if c.type in ("identifier", "attribute")
        ]
        return ", ".join(parts)
    return ""


def _extract_catch_blocks(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for exc_clause in find_nodes(root, "except_clause"):
        caught_type = ""
        for child in exc_clause.children:
            if child.type == "as_pattern":
                for sub in child.children:
                    if sub.type in ("identifier", "attribute", "tuple"):
                        caught_type = _caught_type_from_node(sub, source)
                        break
                break
            if child.type in ("identifier", "attribute", "tuple"):
                caught_type = _caught_type_from_node(child, source)
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


_ABSTRACT_BASES = frozenset({"ABC", "ABCMeta"})
_PROTOCOL_BASES = frozenset({"Protocol", "runtime_checkable"})

_PY_BUILTIN_TYPES = frozenset(
    {
        "str",
        "int",
        "float",
        "bool",
        "bytes",
        "None",
        "complex",
        "object",
        "type",
        "list",
        "dict",
        "set",
        "tuple",
        "frozenset",
    }
)


def _python_access(name: str) -> str:
    if name.startswith("_"):
        return "private"
    return "public"


def _extract_type_annotation(node: Node, source: bytes) -> str:
    for child in node.children:
        if child.type == "type":
            return text(child, source)
    return ""


def _extract_return_type(func_node: Node, source: bytes) -> str:
    saw_arrow = False
    for child in func_node.children:
        if child.type == "->":
            saw_arrow = True
        elif saw_arrow and child.type == "type":
            return text(child, source)
    return ""


def _extract_method_parameters(func_node: Node, source: bytes) -> list[dict[str, str]]:
    params: list[dict[str, str]] = []
    for child in func_node.children:
        if child.type != "parameters":
            continue
        for param in child.children:
            if param.type == "identifier":
                name = text(param, source)
                if name == "self" or name == "cls":
                    continue
                params.append({"name": name, "type": ""})
            elif param.type == "typed_parameter":
                pname = ""
                ptype = ""
                for sub in param.children:
                    if sub.type == "identifier" and not pname:
                        pname = text(sub, source)
                    elif sub.type == "type":
                        ptype = text(sub, source)
                if pname and pname not in ("self", "cls"):
                    params.append({"name": pname, "type": ptype})
            elif param.type == "typed_default_parameter":
                pname = ""
                ptype = ""
                for sub in param.children:
                    if sub.type == "identifier" and not pname:
                        pname = text(sub, source)
                    elif sub.type == "type":
                        ptype = text(sub, source)
                if pname and pname not in ("self", "cls"):
                    params.append({"name": pname, "type": ptype})
            elif param.type == "default_parameter":
                pname = ""
                for sub in param.children:
                    if sub.type == "identifier" and not pname:
                        pname = text(sub, source)
                if pname and pname not in ("self", "cls"):
                    params.append({"name": pname, "type": ""})
    return params


def _extract_class_fields(block_node: Node, source: bytes) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for child in block_node.children:
        if child.type != "expression_statement":
            continue
        inner = child.children[0] if child.children else None
        if inner is None or inner.type != "assignment":
            continue
        has_type_annotation = any(c.type == "type" for c in inner.children)
        if not has_type_annotation:
            continue
        fname = ""
        ftype = ""
        for sub in inner.children:
            if sub.type == "identifier" and not fname:
                fname = text(sub, source)
            elif sub.type == "type":
                ftype = text(sub, source)
        if fname and fname not in seen:
            seen.add(fname)
            fields.append(
                {
                    "name": fname,
                    "type": ftype,
                    "access": _python_access(fname),
                    "line": inner.start_point[0] + 1,
                }
            )
    return fields


def _extract_class_methods(block_node: Node, source: bytes) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    for child in block_node.children:
        if child.type == "function_definition":
            _process_class_method(child, source, [], methods)
        elif child.type == "decorated_definition":
            decorators = _extract_decorators(child, source)
            for sub in child.children:
                if sub.type == "function_definition":
                    _process_class_method(sub, source, decorators, methods)
    return methods


def _process_class_method(
    func_node: Node,
    source: bytes,
    decorators: list[str],
    methods: list[dict[str, Any]],
) -> None:
    name = ""
    for child in func_node.children:
        if child.type == "identifier" and not name:
            name = text(child, source)
            break
    if not name:
        return
    return_type = _extract_return_type(func_node, source)
    parameters = _extract_method_parameters(func_node, source)
    is_pure_virtual = "abstractmethod" in decorators
    methods.append(
        {
            "name": name,
            "return_type": return_type,
            "access": _python_access(name),
            "is_virtual": False,
            "is_pure_virtual": is_pure_virtual,
            "line": func_node.start_point[0] + 1,
            "parameters": parameters,
            "decorators": decorators,
        }
    )


def _extract_base_classes(class_node: Node, source: bytes) -> list[dict[str, str]]:
    bases: list[dict[str, str]] = []
    for child in class_node.children:
        if child.type != "argument_list":
            continue
        for arg in child.children:
            if arg.type == "identifier":
                bases.append({"name": text(arg, source), "access": "public"})
            elif arg.type == "keyword_argument":
                pass
            elif arg.type == "attribute":
                bases.append({"name": _attribute_text(arg, source), "access": "public"})
    return bases


def _is_abstract_class(bases: list[dict[str, str]], methods: list[dict[str, Any]]) -> bool:
    base_names = {b["name"] for b in bases}
    if base_names & _ABSTRACT_BASES:
        return True
    return any(m.get("is_pure_virtual") for m in methods)


def _is_protocol_class(bases: list[dict[str, str]]) -> bool:
    return any(b["name"] in _PROTOCOL_BASES for b in bases)


def _extract_class_or_nested(
    class_node: Node,
    source: bytes,
    *,
    outer_class: str = "",
    namespace: str = "",
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    class_name = ""
    for child in class_node.children:
        if child.type == "identifier":
            class_name = text(child, source)
            break

    if not class_name:
        return results

    bases = _extract_base_classes(class_node, source)
    block_node = None
    for child in class_node.children:
        if child.type == "block":
            block_node = child
            break

    fields: list[dict[str, Any]] = []
    methods: list[dict[str, Any]] = []
    if block_node is not None:
        fields = _extract_class_fields(block_node, source)
        methods = _extract_class_methods(block_node, source)

    is_protocol = _is_protocol_class(bases)
    is_abstract = is_protocol or _is_abstract_class(bases, methods)

    results.append(
        {
            "name": class_name,
            "line": class_node.start_point[0] + 1,
            "is_abstract": is_abstract,
            "is_interface": is_protocol,
            "base_classes": bases,
            "fields": fields,
            "methods": methods,
            "namespace": namespace,
            "outer_class": outer_class,
        }
    )

    if block_node is not None:
        for child in block_node.children:
            if child.type == "class_definition":
                results.extend(
                    _extract_class_or_nested(
                        child,
                        source,
                        outer_class=class_name,
                        namespace=namespace,
                    )
                )

    return results


def _module_path_from_rel(rel_path: str) -> str:
    path = rel_path.replace("\\", "/")
    if path.endswith(".py"):
        path = path[:-3]
    if path.endswith("/__init__"):
        path = path[: -len("/__init__")]
    return path.replace("/", ".")


def _extract_classes(root: Node, source: bytes, rel_path: str) -> list[dict[str, Any]]:
    namespace = _module_path_from_rel(rel_path)
    classes: list[dict[str, Any]] = []
    for node in root.children:
        if node.type == "class_definition":
            classes.extend(_extract_class_or_nested(node, source, namespace=namespace))
    return classes


class PythonAstCollector(BaseASTCollector):
    name = "python-ast"
    version = "0.2.0"
    language = "python"
    file_extensions = (".py",)
    evidence_kind = "python-ast-file"

    def _parse_file(self, source: bytes, rel_path: str) -> dict[str, Any]:
        assert self._parser is not None
        tree = self._parser.parse(source)
        root = tree.root_node
        return {
            "module_path": _module_path_from_rel(rel_path),
            "classes": _extract_classes(root, source, rel_path),
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
