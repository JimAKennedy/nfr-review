# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rust AST collector — parses .rs source via tree-sitter and extracts
evidence for panic-on-error, mutex-poisoning, HTTP-timeout, blocking-in-async,
and unbounded-spawn rules, plus struct/trait/impl data for class-diagram
enrichment.
"""

from __future__ import annotations

from tree_sitter import Node

from nfr_review.collectors.ast_common import BaseASTCollector, find_nodes, text
from nfr_review.collectors.payloads.rust_ast import (
    RustAstFilePayload,
    RustAsyncBlockingCall,
    RustBaseClass,
    RustField,
    RustFunction,
    RustHttpClientBuild,
    RustMethod,
    RustMutexLockUnwrap,
    RustParameter,
    RustSpawnCall,
    RustStruct,
    RustUnwrapExpectCall,
)
from nfr_review.registry import collector_registry

_UNWRAP_METHODS = frozenset({"unwrap", "expect"})
_LOCK_METHODS = frozenset({"lock", "read", "write"})
_LOOP_TYPES = frozenset({"for_expression", "while_expression", "loop_expression"})
_ATTR_SIBLING_TYPES = frozenset({"attribute_item", "line_comment", "block_comment"})


def _is_inside_loop(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type in _LOOP_TYPES:
            return True
        parent = parent.parent
    return False


def _preceding_attrs_text(item_node: Node, source: bytes) -> str:
    parts: list[str] = []
    sib = item_node.prev_sibling
    while sib is not None and sib.type in _ATTR_SIBLING_TYPES:
        if sib.type == "attribute_item":
            parts.append(text(sib, source))
        sib = sib.prev_sibling
    return " ".join(parts)


def _is_inside_test(node: Node, source: bytes) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == "function_item" and "test" in _preceding_attrs_text(parent, source):
            return True
        if parent.type == "mod_item":
            name_node = parent.child_by_field_name("name")
            mod_name = text(name_node, source) if name_node is not None else ""
            attrs = _preceding_attrs_text(parent, source)
            if "test" in mod_name or "test" in attrs:
                return True
        parent = parent.parent
    return False


def _is_async_function_item(node: Node) -> bool:
    for child in node.children:
        if child.type == "function_modifiers" and any(
            gc.type == "async" for gc in child.children
        ):
            return True
        if child.type == "async":
            return True
    return False


def _enclosing_async_function(node: Node, source: bytes) -> str | None:
    parent = node.parent
    while parent is not None:
        if parent.type == "function_item":
            if not _is_async_function_item(parent):
                return None
            name_node = parent.child_by_field_name("name")
            return text(name_node, source) if name_node is not None else "<anonymous>"
        parent = parent.parent
    return None


def _rust_access(node: Node) -> str:
    if any(c.type == "visibility_modifier" for c in node.children):
        return "public"
    return "private"


def _extract_parameters(params_node: Node | None, source: bytes) -> list[RustParameter]:
    if params_node is None:
        return []
    params = []
    for child in params_node.children:
        if child.type != "parameter":
            continue
        pattern = child.child_by_field_name("pattern")
        type_node = child.child_by_field_name("type")
        params.append(
            RustParameter(
                name=text(pattern, source) if pattern is not None else "",
                type=text(type_node, source) if type_node is not None else "",
            )
        )
    return params


def _extract_method(fn_node: Node, source: bytes, *, is_pure_virtual: bool) -> RustMethod:
    name_node = fn_node.child_by_field_name("name")
    return_type_node = fn_node.child_by_field_name("return_type")
    params_node = fn_node.child_by_field_name("parameters")
    return RustMethod(
        name=text(name_node, source) if name_node is not None else "",
        return_type=text(return_type_node, source) if return_type_node is not None else "()",
        access="public" if is_pure_virtual else _rust_access(fn_node),
        is_virtual=False,
        is_pure_virtual=is_pure_virtual,
        line=fn_node.start_point[0] + 1,
        parameters=_extract_parameters(params_node, source),
    )


def _extract_field(fd_node: Node, source: bytes) -> RustField:
    name_node = fd_node.child_by_field_name("name")
    type_node = fd_node.child_by_field_name("type")
    return RustField(
        name=text(name_node, source) if name_node is not None else "",
        type=text(type_node, source) if type_node is not None else "",
        access=_rust_access(fd_node),
        line=fd_node.start_point[0] + 1,
    )


def _extract_structs(root: Node, source: bytes) -> list[RustStruct]:
    """Extract structs (with impl'd methods/traits) and traits, uniformly as RustStruct.

    Enums are deliberately not modeled — not needed by any current rule or by
    class-diagram enrichment's base_classes/methods/fields shape.
    """
    struct_data: dict[str, dict] = {}

    for s in find_nodes(root, "struct_item"):
        name_node = s.child_by_field_name("name")
        if name_node is None:
            continue
        name = text(name_node, source)
        fields: list[RustField] = []
        for c in s.children:
            if c.type == "field_declaration_list":
                fields = [
                    _extract_field(fd, source)
                    for fd in c.children
                    if fd.type == "field_declaration"
                ]
        struct_data[name] = {
            "line": s.start_point[0] + 1,
            "fields": fields,
            "methods": [],
            "base_classes": [],
        }

    traits: list[RustStruct] = []
    for t in find_nodes(root, "trait_item"):
        name_node = t.child_by_field_name("name")
        if name_node is None:
            continue
        methods: list[RustMethod] = []
        for c in t.children:
            if c.type != "declaration_list":
                continue
            for member in c.children:
                if member.type == "function_item":
                    methods.append(_extract_method(member, source, is_pure_virtual=False))
                elif member.type == "function_signature_item":
                    ret_node = member.child_by_field_name("return_type")
                    params_node = member.child_by_field_name("parameters")
                    mname_node = member.child_by_field_name("name")
                    methods.append(
                        RustMethod(
                            name=text(mname_node, source) if mname_node is not None else "",
                            return_type=(
                                text(ret_node, source) if ret_node is not None else "()"
                            ),
                            access="public",
                            is_virtual=False,
                            is_pure_virtual=True,
                            line=member.start_point[0] + 1,
                            parameters=_extract_parameters(params_node, source),
                        )
                    )
        traits.append(
            RustStruct(
                name=text(name_node, source),
                line=t.start_point[0] + 1,
                is_struct=False,
                is_abstract=True,
                is_interface=True,
                base_classes=[],
                fields=[],
                methods=methods,
                namespace="",
                outer_class="",
            )
        )

    for impl in find_nodes(root, "impl_item"):
        type_node = impl.child_by_field_name("type")
        trait_node = impl.child_by_field_name("trait")
        if type_node is None or type_node.type != "type_identifier":
            continue
        target_name = text(type_node, source)
        if target_name not in struct_data:
            continue
        for c in impl.children:
            if c.type != "declaration_list":
                continue
            for member in c.children:
                if member.type == "function_item":
                    struct_data[target_name]["methods"].append(
                        _extract_method(member, source, is_pure_virtual=False)
                    )
        if trait_node is not None and trait_node.type == "type_identifier":
            struct_data[target_name]["base_classes"].append(
                RustBaseClass(name=text(trait_node, source), access="public")
            )

    structs = [
        RustStruct(
            name=name,
            line=data["line"],
            is_struct=True,
            is_abstract=False,
            is_interface=False,
            base_classes=data["base_classes"],
            fields=data["fields"],
            methods=data["methods"],
            namespace="",
            outer_class="",
        )
        for name, data in struct_data.items()
    ]
    structs.extend(traits)
    return structs


def _extract_functions(root: Node, source: bytes) -> list[RustFunction]:
    functions = []
    for fn in find_nodes(root, "function_item"):
        name_node = fn.child_by_field_name("name")
        functions.append(
            RustFunction(
                name=text(name_node, source) if name_node is not None else "",
                line=fn.start_point[0] + 1,
                is_async=_is_async_function_item(fn),
            )
        )
    return functions


def _extract_unwrap_expect_and_mutex(
    root: Node, source: bytes, rel_path: str
) -> tuple[list[RustUnwrapExpectCall], list[RustMutexLockUnwrap]]:
    unwrap_calls: list[RustUnwrapExpectCall] = []
    mutex_calls: list[RustMutexLockUnwrap] = []

    for call in find_nodes(root, "call_expression"):
        func = call.child_by_field_name("function")
        if func is None or func.type != "field_expression":
            continue
        field_node = func.child_by_field_name("field")
        if field_node is None or text(field_node, source) not in _UNWRAP_METHODS:
            continue
        method_name = text(field_node, source)
        receiver = func.child_by_field_name("value")

        if receiver is not None and receiver.type == "call_expression":
            rfunc = receiver.child_by_field_name("function")
            if rfunc is not None and rfunc.type == "field_expression":
                rfield = rfunc.child_by_field_name("field")
                if rfield is not None and text(rfield, source) in _LOCK_METHODS:
                    mutex_calls.append(
                        RustMutexLockUnwrap(
                            lock_method=text(rfield, source),
                            line=call.start_point[0] + 1,
                            file=rel_path,
                        )
                    )
                    continue

        unwrap_calls.append(
            RustUnwrapExpectCall(
                method=method_name,
                receiver=text(receiver, source) if receiver is not None else "",
                line=call.start_point[0] + 1,
                file=rel_path,
                in_test=_is_inside_test(call, source),
            )
        )

    return unwrap_calls, mutex_calls


def _extract_http_client_builds(
    root: Node, source: bytes, rel_path: str
) -> list[RustHttpClientBuild]:
    results = []
    for call in find_nodes(root, "call_expression"):
        func = call.child_by_field_name("function")
        if func is None:
            continue
        if func.type == "scoped_identifier" and text(func, source) == "reqwest::Client::new":
            results.append(
                RustHttpClientBuild(
                    call="reqwest::Client::new",
                    has_timeout=False,
                    line=call.start_point[0] + 1,
                    file=rel_path,
                )
            )
            continue
        if func.type == "field_expression":
            field_node = func.child_by_field_name("field")
            if field_node is None or text(field_node, source) != "build":
                continue
            full_text = text(call, source)
            if "reqwest::Client::builder" in full_text:
                results.append(
                    RustHttpClientBuild(
                        call="reqwest::Client::builder()...build()",
                        has_timeout=".timeout(" in full_text,
                        line=call.start_point[0] + 1,
                        file=rel_path,
                    )
                )
    return results


def _extract_async_blocking_calls(
    root: Node, source: bytes, rel_path: str
) -> list[RustAsyncBlockingCall]:
    results = []
    for call in find_nodes(root, "call_expression"):
        fn_name = _enclosing_async_function(call, source)
        if fn_name is None:
            continue
        func = call.child_by_field_name("function")
        if func is None:
            continue
        if func.type == "scoped_identifier":
            callee = text(func, source)
            if callee in ("std::thread::sleep", "thread::sleep"):
                results.append(
                    RustAsyncBlockingCall(
                        function_name=fn_name,
                        call=callee,
                        kind="thread::sleep",
                        line=call.start_point[0] + 1,
                        file=rel_path,
                    )
                )
            elif callee.startswith("std::fs::") or callee.startswith("fs::"):
                results.append(
                    RustAsyncBlockingCall(
                        function_name=fn_name,
                        call=callee,
                        kind="fs",
                        line=call.start_point[0] + 1,
                        file=rel_path,
                    )
                )
        elif func.type == "field_expression":
            field_node = func.child_by_field_name("field")
            if field_node is not None and text(field_node, source) in _LOCK_METHODS:
                awaited = call.parent is not None and call.parent.type == "await_expression"
                if not awaited:
                    results.append(
                        RustAsyncBlockingCall(
                            function_name=fn_name,
                            call=text(func, source),
                            kind="sync-lock-no-await",
                            line=call.start_point[0] + 1,
                            file=rel_path,
                        )
                    )
    return results


def _extract_spawn_calls(root: Node, source: bytes, rel_path: str) -> list[RustSpawnCall]:
    results = []
    for call in find_nodes(root, "call_expression"):
        func = call.child_by_field_name("function")
        if func is None or func.type != "scoped_identifier":
            continue
        if text(func, source) != "tokio::spawn":
            continue
        results.append(
            RustSpawnCall(
                line=call.start_point[0] + 1,
                file=rel_path,
                in_loop=_is_inside_loop(call),
            )
        )
    return results


class RustAstCollector(BaseASTCollector):
    name = "rust-ast"
    version = "0.1.0"
    language = "rust"
    file_extensions = (".rs",)
    evidence_kind = "rust-ast-file"

    def _parse_file(self, source: bytes, rel_path: str) -> RustAstFilePayload:
        assert self._parser is not None
        tree = self._parser.parse(source)
        root = tree.root_node
        unwrap_calls, mutex_calls = _extract_unwrap_expect_and_mutex(root, source, rel_path)
        return RustAstFilePayload(
            file_path=rel_path,
            structs=_extract_structs(root, source),
            functions=_extract_functions(root, source),
            unwrap_expect_calls=unwrap_calls,
            mutex_lock_unwraps=mutex_calls,
            http_client_builds=_extract_http_client_builds(root, source, rel_path),
            async_blocking_calls=_extract_async_blocking_calls(root, source, rel_path),
            spawn_calls=_extract_spawn_calls(root, source, rel_path),
        )


def _register() -> None:
    if "rust-ast" not in collector_registry:
        collector_registry.register("rust-ast", RustAstCollector())


_register()

__all__ = ["RustAstCollector"]
