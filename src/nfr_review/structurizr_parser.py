# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Parse Structurizr DSL text into workspace models.

Recursive-descent parser for the core DSL subset that nfr-review emits:
workspace, model, elements, relationships, views, styles. Does not handle
``!script``, ``!extend``, ``archetypes``, or ``!include`` (yet).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from nfr_review.structurizr_models import (
    AutoLayoutDirection,
    DslAutoLayout,
    DslDynamicStep,
    DslDynamicView,
    DslElement,
    DslElementStyle,
    DslGroup,
    DslModel,
    DslProperty,
    DslRelationship,
    DslRelationshipStyle,
    DslStyles,
    DslView,
    DslViewContent,
    DslWorkspace,
    ElementType,
    LineStyle,
    RoutingKind,
    ShapeKind,
    ViewType,
)

_ELEMENT_KEYWORDS = frozenset(
    {
        "person",
        "softwaresystem",
        "container",
        "component",
        "deploymentnode",
        "infrastructurenode",
        "softwaresysteminstance",
        "containerinstance",
    }
)

_VIEW_KEYWORDS = frozenset(
    {
        "systemlandscape",
        "systemcontext",
        "container",
        "component",
        "dynamic",
        "deployment",
        "filtered",
        "custom",
    }
)

_ELEMENT_TYPE_CANONICAL: dict[str, str] = {
    "person": "person",
    "softwaresystem": "softwareSystem",
    "container": "container",
    "component": "component",
    "deploymentnode": "deploymentNode",
    "infrastructurenode": "infrastructureNode",
    "softwaresysteminstance": "softwareSystemInstance",
    "containerinstance": "containerInstance",
}

_VIEW_TYPE_CANONICAL: dict[str, str] = {
    "systemlandscape": "systemLandscape",
    "systemcontext": "systemContext",
    "container": "container",
    "component": "component",
    "dynamic": "dynamic",
    "deployment": "deployment",
    "filtered": "filtered",
    "custom": "custom",
}

_SHAPE_MAP: dict[str, str] = {
    "box": "Box",
    "roundedbox": "RoundedBox",
    "circle": "Circle",
    "ellipse": "Ellipse",
    "hexagon": "Hexagon",
    "diamond": "Diamond",
    "cylinder": "Cylinder",
    "pipe": "Pipe",
    "person": "Person",
    "robot": "Robot",
    "folder": "Folder",
    "webbrowser": "WebBrowser",
    "mobiledeviceportrait": "MobileDevicePortrait",
    "component": "Component",
}

_LINE_STYLE_MAP: dict[str, str] = {
    "solid": "solid",
    "dashed": "dashed",
    "dotted": "dotted",
}

_ROUTING_MAP: dict[str, str] = {
    "direct": "Direct",
    "orthogonal": "Orthogonal",
    "curved": "Curved",
}

_AUTO_LAYOUT_DIR: dict[str, str] = {
    "tb": "tb",
    "bt": "bt",
    "lr": "lr",
    "rl": "rl",
}


class DslParseError(Exception):
    """Raised when the DSL text is syntactically invalid."""

    def __init__(self, message: str, line: int = 0) -> None:
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


@dataclass
class _Token:
    kind: str
    value: str
    line: int


# Hash-comments (#) only at start of line to avoid matching hex colors (#1168bd).
_TOKEN_RE = re.compile(
    r"""
    (?P<comment_block>/\*.*?\*/)            |
    (?P<comment_line>//[^\n]*)              |
    (?P<hash_comment>(?:^|(?<=\n))[ \t]*[#][^\n]*)  |
    (?P<string>"(?:[^"\\]|\\.)*")           |
    (?P<arrow>->)                           |
    (?P<removal>-/>)                        |
    (?P<lbrace>\{)                          |
    (?P<rbrace>\})                          |
    (?P<assign>=)                           |
    (?P<newline>\n)                         |
    (?P<word>[^\s{}"=]+)                    |
    (?P<ws>[ \t\r]+)
    """,
    re.VERBOSE | re.DOTALL,
)


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    line = 1
    prev_end = 0
    continuation = False

    for m in _TOKEN_RE.finditer(text):
        start = m.start()
        for ch in text[prev_end:start]:
            if ch == "\n":
                line += 1
        prev_end = m.end()

        kind = m.lastgroup or "word"
        value = m.group()

        if kind == "newline":
            if not continuation:
                tokens.append(_Token(kind="nl", value="\\n", line=line))
            continuation = False
            line += 1
            continue
        if kind in ("ws", "comment_block", "comment_line", "hash_comment"):
            if kind == "comment_block":
                line += value.count("\n")
            continue
        if kind == "word" and value == "\\":
            continuation = True
            continue
        if kind == "string":
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")

        tokens.append(_Token(kind=kind, value=value, line=line))

    return tokens


@dataclass
class _Parser:
    tokens: list[_Token]
    pos: int = 0

    def _peek(self) -> _Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _advance(self) -> _Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _skip_nl(self) -> None:
        while self.pos < len(self.tokens) and self.tokens[self.pos].kind == "nl":
            self.pos += 1

    def _peek_significant(self) -> _Token | None:
        self._skip_nl()
        return self._peek()

    def _expect(self, kind: str | None = None, value: str | None = None) -> _Token:
        self._skip_nl()
        tok = self._peek()
        if tok is None:
            raise DslParseError("Unexpected end of input")
        if kind and tok.kind != kind:
            raise DslParseError(f"Expected {kind}, got {tok.kind} ({tok.value!r})", tok.line)
        if value and tok.value.lower() != value.lower():
            raise DslParseError(f"Expected {value!r}, got {tok.value!r}", tok.line)
        return self._advance()

    def _collect_line_strings(self) -> list[str]:
        """Collect word/string tokens until end of line or structural token."""
        result: list[str] = []
        while self.pos < len(self.tokens):
            tok = self.tokens[self.pos]
            if tok.kind in ("nl", "lbrace", "rbrace", "arrow", "removal", "assign"):
                break
            if tok.kind in ("word", "string"):
                result.append(self._advance().value)
            else:
                break
        return result

    def _collect_one_string(self) -> str:
        tok = self._peek()
        if tok and tok.kind in ("word", "string"):
            return self._advance().value
        return ""

    def parse(self) -> DslWorkspace:
        self._expect(value="workspace")
        args = self._collect_line_strings()
        name = args[0] if args else ""
        description = args[1] if len(args) > 1 else ""
        self._expect(kind="lbrace")

        ws = DslWorkspace(name=name, description=description)
        ws.use_hierarchical_identifiers = False
        ws.implied_relationships = True

        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of workspace block")
            if tok.kind == "rbrace":
                self._advance()
                break
            kw = tok.value.lower()
            if kw == "!identifiers":
                self._advance()
                mode = self._collect_one_string()
                if mode.lower() == "hierarchical":
                    ws.use_hierarchical_identifiers = True
            elif kw == "!impliedrelationships":
                self._advance()
                val = self._collect_one_string()
                ws.implied_relationships = val.lower() != "false"
            elif kw in ("!const", "!var"):
                self._advance()
                self._collect_line_strings()
            elif kw == "model":
                ws.model = self._parse_model()
            elif kw == "views":
                self._parse_views_block(ws)
            elif kw == "configuration":
                self._skip_block()
            elif kw.startswith("!"):
                self._advance()
                self._collect_line_strings()
            else:
                raise DslParseError(f"Unexpected token in workspace: {tok.value!r}", tok.line)

        return ws

    def _skip_block(self) -> None:
        self._skip_nl()
        self._advance()
        self._collect_line_strings()
        self._skip_nl()
        tok = self._peek()
        if tok and tok.kind == "lbrace":
            self._advance()
            depth = 1
            while depth > 0:
                self._skip_nl()
                t = self._advance()
                if t.kind == "lbrace":
                    depth += 1
                elif t.kind == "rbrace":
                    depth -= 1

    def _parse_model(self) -> DslModel:
        self._expect(value="model")
        self._expect(kind="lbrace")
        model = DslModel()

        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of model block")
            if tok.kind == "rbrace":
                self._advance()
                break

            if self._is_relationship_line():
                model.relationships.append(self._parse_relationship())
            elif tok.value.lower() == "group":
                model.groups.append(self._parse_group())
            elif tok.value.lower() == "properties":
                model.properties = self._parse_properties()
            elif tok.value.lower() in _ELEMENT_KEYWORDS:
                elem = self._parse_element(identifier="")
                self._place_element(model, elem)
            elif self._is_identifier_assignment():
                ident = self._advance().value
                self._expect(kind="assign")
                elem = self._parse_element(identifier=ident)
                self._place_element(model, elem)
            elif tok.value.lower().startswith("!"):
                self._advance()
                self._collect_line_strings()
            else:
                raise DslParseError(f"Unexpected token in model: {tok.value!r}", tok.line)

        return model

    def _place_element(self, model: DslModel, elem: DslElement) -> None:
        if elem.element_type == "person":
            model.people.append(elem)
        else:
            model.software_systems.append(elem)

    def _is_relationship_line(self) -> bool:
        i = self.pos
        while i < len(self.tokens) and self.tokens[i].kind == "nl":
            i += 1
        if i + 1 >= len(self.tokens):
            return False
        return self.tokens[i].kind == "word" and self.tokens[i + 1].kind == "arrow"

    def _is_identifier_assignment(self) -> bool:
        i = self.pos
        while i < len(self.tokens) and self.tokens[i].kind == "nl":
            i += 1
        if i + 1 >= len(self.tokens):
            return False
        return self.tokens[i].kind == "word" and self.tokens[i + 1].kind == "assign"

    def _parse_element(self, identifier: str) -> DslElement:
        self._skip_nl()
        type_tok = self._advance()
        elem_type = _ELEMENT_TYPE_CANONICAL.get(type_tok.value.lower())
        if not elem_type:
            raise DslParseError(f"Unknown element type: {type_tok.value!r}", type_tok.line)

        args = self._collect_line_strings()
        name = args[0] if args else ""
        description = args[1] if len(args) > 1 else ""
        technology = ""
        tag_str = ""

        if elem_type in ("container", "component"):
            technology = args[2] if len(args) > 2 else ""
            tag_str = args[3] if len(args) > 3 else ""
        elif elem_type in ("person", "softwareSystem"):
            tag_str = args[2] if len(args) > 2 else ""

        if not identifier:
            identifier = f"_anon_{self.pos}"

        tags = [t.strip() for t in tag_str.split(",") if t.strip()] if tag_str else []

        elem = DslElement(
            identifier=identifier,
            element_type=cast(ElementType, elem_type),
            name=name,
            description=description,
            technology=technology,
            tags=tags,
        )

        self._skip_nl()
        tok = self._peek()
        if tok and tok.kind == "lbrace":
            self._advance()
            self._parse_element_body(elem)

        return elem

    def _parse_element_body(self, elem: DslElement) -> None:
        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of element block")
            if tok.kind == "rbrace":
                self._advance()
                break

            kw = tok.value.lower()

            if tok.kind == "arrow":
                elem.implicit_relationships.append(
                    self._parse_implicit_relationship(elem.identifier)
                )
            elif self._is_relationship_line():
                elem.implicit_relationships.append(self._parse_relationship())
            elif kw == "tags":
                self._advance()
                elem.tags.extend(self._collect_line_strings())
            elif kw == "description":
                self._advance()
                elem.description = self._collect_one_string()
            elif kw == "technology":
                self._advance()
                elem.technology = self._collect_one_string()
            elif kw == "url":
                self._advance()
                elem.url = self._collect_one_string()
            elif kw == "properties":
                elem.properties = self._parse_properties()
            elif kw == "group":
                self._parse_group()
            elif kw in _ELEMENT_KEYWORDS:
                child = self._parse_element(identifier="")
                elem.children.append(child)
            elif self._is_identifier_assignment():
                ident = self._advance().value
                self._expect(kind="assign")
                child = self._parse_element(identifier=ident)
                elem.children.append(child)
            elif kw.startswith("!"):
                self._advance()
                self._collect_line_strings()
            else:
                raise DslParseError(
                    f"Unexpected token in element body: {tok.value!r}", tok.line
                )

    def _parse_relationship(self) -> DslRelationship:
        self._skip_nl()
        source = self._advance().value
        self._expect(kind="arrow")
        dest = self._collect_one_string()
        args = self._collect_line_strings()
        description = args[0] if args else ""
        technology = args[1] if len(args) > 1 else ""

        rel = DslRelationship(
            source_id=source,
            destination_id=dest,
            description=description,
            technology=technology,
        )

        self._skip_nl()
        tok = self._peek()
        if tok and tok.kind == "lbrace":
            self._advance()
            self._parse_relationship_body(rel)

        return rel

    def _parse_implicit_relationship(self, source_id: str) -> DslRelationship:
        self._skip_nl()
        self._expect(kind="arrow")
        dest = self._collect_one_string()
        args = self._collect_line_strings()
        description = args[0] if args else ""
        technology = args[1] if len(args) > 1 else ""

        rel = DslRelationship(
            source_id=source_id,
            destination_id=dest,
            description=description,
            technology=technology,
        )

        self._skip_nl()
        tok = self._peek()
        if tok and tok.kind == "lbrace":
            self._advance()
            self._parse_relationship_body(rel)

        return rel

    def _parse_relationship_body(self, rel: DslRelationship) -> None:
        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of relationship block")
            if tok.kind == "rbrace":
                self._advance()
                break
            kw = tok.value.lower()
            if kw == "tags":
                self._advance()
                rel.tags.extend(self._collect_line_strings())
            elif kw == "technology":
                self._advance()
                rel.technology = self._collect_one_string()
            elif kw == "properties":
                rel.properties = self._parse_properties()
            else:
                self._advance()
                self._collect_line_strings()

    def _parse_group(self) -> DslGroup:
        self._expect(value="group")
        name = self._collect_one_string()
        self._expect(kind="lbrace")

        group = DslGroup(name=name)

        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of group block")
            if tok.kind == "rbrace":
                self._advance()
                break
            kw = tok.value.lower()
            if kw == "group":
                group.groups.append(self._parse_group())
            elif kw in _ELEMENT_KEYWORDS:
                group.elements.append(self._parse_element(identifier=""))
            elif self._is_identifier_assignment():
                ident = self._advance().value
                self._expect(kind="assign")
                group.elements.append(self._parse_element(identifier=ident))
            else:
                self._advance()
                self._collect_line_strings()

        return group

    def _parse_properties(self) -> list[DslProperty]:
        self._expect(value="properties")
        self._expect(kind="lbrace")
        props: list[DslProperty] = []
        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of properties block")
            if tok.kind == "rbrace":
                self._advance()
                break
            key = self._advance().value
            value = self._collect_one_string()
            props.append(DslProperty(key=key, value=value))
        return props

    def _parse_views_block(self, ws: DslWorkspace) -> None:
        self._expect(value="views")
        self._expect(kind="lbrace")

        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of views block")
            if tok.kind == "rbrace":
                self._advance()
                break

            kw = tok.value.lower()
            if kw == "styles":
                ws.styles = self._parse_styles()
            elif kw == "dynamic":
                ws.dynamic_views.append(self._parse_dynamic_view())
            elif kw in ("theme", "themes"):
                self._advance()
                self._collect_line_strings()
            elif kw in _VIEW_KEYWORDS:
                ws.views.append(self._parse_view())
            else:
                self._advance()
                self._collect_line_strings()
                self._skip_nl()
                nxt = self._peek()
                if nxt and nxt.kind == "lbrace":
                    self._skip_block_inner()

    def _skip_block_inner(self) -> None:
        self._advance()
        depth = 1
        while depth > 0:
            self._skip_nl()
            t = self._advance()
            if t.kind == "lbrace":
                depth += 1
            elif t.kind == "rbrace":
                depth -= 1

    def _parse_view(self) -> DslView:
        self._skip_nl()
        type_tok = self._advance()
        view_type = _VIEW_TYPE_CANONICAL.get(type_tok.value.lower(), type_tok.value)

        args = self._collect_line_strings()

        scope_id = ""
        key = ""
        description = ""

        if view_type in ("systemContext", "container", "component", "deployment"):
            scope_id = args[0] if args else ""
            key = args[1] if len(args) > 1 else ""
            description = args[2] if len(args) > 2 else ""
        elif view_type == "filtered":
            scope_id = args[0] if args else ""
            key = args[1] if len(args) > 1 else ""
            description = args[2] if len(args) > 2 else ""
        else:
            key = args[0] if args else ""
            description = args[1] if len(args) > 1 else ""

        content = DslViewContent()

        self._skip_nl()
        tok = self._peek()
        if tok and tok.kind == "lbrace":
            self._advance()
            content = self._parse_view_content()

        return DslView(
            view_type=cast(ViewType, view_type),
            scope_id=scope_id,
            key=key,
            description=description,
            content=content,
        )

    def _parse_view_content(self) -> DslViewContent:
        content = DslViewContent()

        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of view block")
            if tok.kind == "rbrace":
                self._advance()
                break

            kw = tok.value.lower()
            if kw == "include":
                self._advance()
                content.include.extend(self._collect_line_strings())
            elif kw == "exclude":
                self._advance()
                content.exclude.extend(self._collect_line_strings())
            elif kw == "autolayout":
                content.auto_layout = self._parse_auto_layout()
            elif kw == "title":
                self._advance()
                content.title = self._collect_one_string()
            elif kw == "default":
                self._advance()
                content.is_default = True
            else:
                self._advance()
                self._collect_line_strings()

        return content

    def _parse_dynamic_view(self) -> DslDynamicView:
        self._expect(value="dynamic")
        args = self._collect_line_strings()

        scope_id = ""
        key = ""
        description = ""

        if len(args) >= 3:
            scope_id = args[0]
            key = args[1]
            description = args[2]
        elif len(args) == 2:
            scope_id = args[0]
            key = args[1]
        elif len(args) == 1:
            key = args[0]

        self._expect(kind="lbrace")

        steps: list[DslDynamicStep] = []
        auto_layout: DslAutoLayout | None = None

        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of dynamic view block")
            if tok.kind == "rbrace":
                self._advance()
                break

            kw = tok.value.lower()
            if kw == "autolayout":
                auto_layout = self._parse_auto_layout()
            elif self._is_relationship_line():
                src = self._advance().value
                self._expect(kind="arrow")
                dst = self._collect_one_string()
                desc_args = self._collect_line_strings()
                desc = desc_args[0] if desc_args else ""
                steps.append(
                    DslDynamicStep(
                        source_id=src,
                        destination_id=dst,
                        description=desc,
                    )
                )
            else:
                self._advance()
                self._collect_line_strings()

        return DslDynamicView(
            scope_id=scope_id,
            key=key,
            description=description,
            steps=steps,
            auto_layout=auto_layout,
        )

    def _parse_auto_layout(self) -> DslAutoLayout:
        self._expect(value="autoLayout")
        args = self._collect_line_strings()
        direction = "tb"
        rank_sep = None
        node_sep = None
        if args:
            direction = _AUTO_LAYOUT_DIR.get(args[0].lower(), "tb")
        if len(args) > 1:
            try:
                rank_sep = int(args[1])
            except ValueError:
                pass
        if len(args) > 2:
            try:
                node_sep = int(args[2])
            except ValueError:
                pass
        return DslAutoLayout(
            direction=cast(AutoLayoutDirection, direction),
            rank_sep=rank_sep,
            node_sep=node_sep,
        )

    def _parse_styles(self) -> DslStyles:
        self._expect(value="styles")
        self._expect(kind="lbrace")

        styles = DslStyles()

        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of styles block")
            if tok.kind == "rbrace":
                self._advance()
                break

            kw = tok.value.lower()
            if kw == "element":
                styles.elements.append(self._parse_element_style())
            elif kw == "relationship":
                styles.relationships.append(self._parse_relationship_style())
            else:
                self._advance()
                self._collect_line_strings()

        return styles

    def _parse_element_style(self) -> DslElementStyle:
        self._expect(value="element")
        tag = self._collect_one_string()
        self._expect(kind="lbrace")

        style = DslElementStyle(tag=tag)

        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of element style block")
            if tok.kind == "rbrace":
                self._advance()
                break

            kw = tok.value.lower()
            self._advance()
            val = self._collect_one_string()

            if kw == "shape":
                style.shape = cast(ShapeKind, _SHAPE_MAP.get(val.lower(), val))
            elif kw == "background":
                style.background = val
            elif kw == "color":
                style.color = val
            elif kw == "stroke":
                style.stroke = val
            elif kw == "strokewidth":
                style.stroke_width = int(val) if val.isdigit() else None
            elif kw == "border":
                style.border = cast(LineStyle | None, _LINE_STYLE_MAP.get(val.lower()))
            elif kw == "fontsize":
                style.font_size = int(val) if val.isdigit() else None
            elif kw == "opacity":
                style.opacity = int(val) if val.isdigit() else None
            elif kw == "icon":
                style.icon = val
            elif kw == "metadata":
                style.metadata = val.lower() == "true"
            elif kw == "description":
                style.show_description = val.lower() == "true"

        return style

    def _parse_relationship_style(self) -> DslRelationshipStyle:
        self._expect(value="relationship")
        tag = self._collect_one_string()
        self._expect(kind="lbrace")

        style = DslRelationshipStyle(tag=tag)

        while True:
            tok = self._peek_significant()
            if tok is None:
                raise DslParseError("Unexpected end of relationship style block")
            if tok.kind == "rbrace":
                self._advance()
                break

            kw = tok.value.lower()
            self._advance()
            val = self._collect_one_string()

            if kw == "thickness":
                style.thickness = int(val) if val.isdigit() else None
            elif kw == "color":
                style.color = val
            elif kw == "style":
                style.style = cast(LineStyle | None, _LINE_STYLE_MAP.get(val.lower()))
            elif kw == "routing":
                style.routing = cast(RoutingKind | None, _ROUTING_MAP.get(val.lower()))
            elif kw == "fontsize":
                style.font_size = int(val) if val.isdigit() else None
            elif kw == "position":
                style.position = int(val) if val.isdigit() else None
            elif kw == "opacity":
                style.opacity = int(val) if val.isdigit() else None

        return style


def parse_dsl(text: str) -> DslWorkspace:
    """Parse Structurizr DSL text into a DslWorkspace model."""
    tokens = _tokenize(text)
    parser = _Parser(tokens=tokens)
    return parser.parse()


def parse_dsl_file(path: Path) -> DslWorkspace:
    """Read and parse a ``.dsl`` file."""
    text = path.read_text(encoding="utf-8")
    return parse_dsl(text)


__all__ = [
    "DslParseError",
    "parse_dsl",
    "parse_dsl_file",
]
