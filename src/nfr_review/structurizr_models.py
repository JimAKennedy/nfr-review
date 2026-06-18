# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Pydantic v2 data models for Structurizr workspace elements.

Covers the C4 model hierarchy (Person, SoftwareSystem, Container, Component),
relationships, views, and styles — the subset needed to emit and parse
Structurizr DSL for architecture review reports.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

ElementType = Literal[
    "person",
    "softwareSystem",
    "container",
    "component",
    "deploymentNode",
    "infrastructureNode",
    "softwareSystemInstance",
    "containerInstance",
]

ViewType = Literal[
    "systemLandscape",
    "systemContext",
    "container",
    "component",
    "dynamic",
    "deployment",
    "filtered",
    "custom",
]

AutoLayoutDirection = Literal["tb", "bt", "lr", "rl"]

ShapeKind = Literal[
    "Box",
    "RoundedBox",
    "Circle",
    "Ellipse",
    "Hexagon",
    "Diamond",
    "Cylinder",
    "Pipe",
    "Person",
    "Robot",
    "Folder",
    "WebBrowser",
    "MobileDevicePortrait",
    "Component",
]

LineStyle = Literal["solid", "dashed", "dotted"]
RoutingKind = Literal["Direct", "Orthogonal", "Curved"]


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DslProperty(_StrictBase):
    """A key-value property on an element or relationship."""

    key: str
    value: str


class DslRelationship(_StrictBase):
    """A relationship between two elements in the model."""

    source_id: str
    destination_id: str
    description: str = ""
    technology: str = ""
    tags: list[str] = Field(default_factory=list)
    properties: list[DslProperty] = Field(default_factory=list)


class DslElement(_StrictBase):
    """A model element (person, softwareSystem, container, component)."""

    identifier: str
    element_type: ElementType
    name: str
    description: str = ""
    technology: str = ""
    tags: list[str] = Field(default_factory=list)
    properties: list[DslProperty] = Field(default_factory=list)
    url: str = ""
    children: list[DslElement] = Field(default_factory=list)
    # Implicit relationships (source = this element)
    implicit_relationships: list[DslRelationship] = Field(default_factory=list)

    @field_validator("identifier")
    @classmethod
    def _valid_identifier(cls, v: str) -> str:
        if not _IDENT_RE.match(v):
            msg = f"Identifier must match [a-zA-Z_][a-zA-Z0-9_]*, got {v!r}"
            raise ValueError(msg)
        return v


class DslGroup(_StrictBase):
    """A named group containing elements."""

    name: str
    elements: list[DslElement] = Field(default_factory=list)
    groups: list[DslGroup] = Field(default_factory=list)


class DslAutoLayout(_StrictBase):
    """Auto-layout configuration for a view."""

    direction: AutoLayoutDirection = "tb"
    rank_sep: int | None = None
    node_sep: int | None = None


class DslViewContent(_StrictBase):
    """Content specification for a view (includes, excludes, layout)."""

    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    auto_layout: DslAutoLayout | None = None
    title: str = ""
    is_default: bool = False


class DslView(_StrictBase):
    """A view definition in the workspace."""

    view_type: ViewType
    scope_id: str = ""
    key: str
    description: str = ""
    content: DslViewContent = Field(default_factory=DslViewContent)


class DslDynamicStep(_StrictBase):
    """A step in a dynamic view sequence."""

    source_id: str
    destination_id: str
    description: str = ""


class DslDynamicView(_StrictBase):
    """A dynamic view with ordered interaction steps."""

    scope_id: str = ""
    key: str
    description: str = ""
    steps: list[DslDynamicStep] = Field(default_factory=list)
    auto_layout: DslAutoLayout | None = None


class DslElementStyle(_StrictBase):
    """Style applied to elements matching a tag."""

    tag: str
    shape: ShapeKind | None = None
    background: str = ""
    color: str = ""
    stroke: str = ""
    stroke_width: int | None = None
    border: LineStyle | None = None
    font_size: int | None = None
    opacity: int | None = None
    icon: str = ""
    metadata: bool | None = None
    show_description: bool | None = None


class DslRelationshipStyle(_StrictBase):
    """Style applied to relationships matching a tag."""

    tag: str
    thickness: int | None = None
    color: str = ""
    style: LineStyle | None = None
    routing: RoutingKind | None = None
    font_size: int | None = None
    position: int | None = None
    opacity: int | None = None


class DslStyles(_StrictBase):
    """Styles block containing element and relationship styles."""

    elements: list[DslElementStyle] = Field(default_factory=list)
    relationships: list[DslRelationshipStyle] = Field(default_factory=list)


class DslModel(_StrictBase):
    """The model block containing all elements and relationships."""

    people: list[DslElement] = Field(default_factory=list)
    software_systems: list[DslElement] = Field(default_factory=list)
    groups: list[DslGroup] = Field(default_factory=list)
    relationships: list[DslRelationship] = Field(default_factory=list)
    properties: list[DslProperty] = Field(default_factory=list)


class DslWorkspace(_StrictBase):
    """Root model representing a complete Structurizr workspace."""

    name: str = ""
    description: str = ""
    use_hierarchical_identifiers: bool = True
    implied_relationships: bool = True
    model: DslModel = Field(default_factory=DslModel)
    views: list[DslView] = Field(default_factory=list)
    dynamic_views: list[DslDynamicView] = Field(default_factory=list)
    styles: DslStyles = Field(default_factory=DslStyles)


def make_identifier(name: str) -> str:
    """Convert a human-readable name to a valid DSL identifier.

    Replaces non-alphanumeric chars with underscores, lowercases, and ensures
    it starts with a letter or underscore.
    """
    ident = re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()
    ident = re.sub(r"_+", "_", ident).strip("_")
    if not ident or ident[0].isdigit():
        ident = f"_{ident}"
    return ident


__all__ = [
    "AutoLayoutDirection",
    "DslAutoLayout",
    "DslDynamicStep",
    "DslDynamicView",
    "DslElement",
    "DslElementStyle",
    "DslGroup",
    "DslModel",
    "DslProperty",
    "DslRelationship",
    "DslRelationshipStyle",
    "DslStyles",
    "DslView",
    "DslViewContent",
    "DslWorkspace",
    "ElementType",
    "LineStyle",
    "RoutingKind",
    "ShapeKind",
    "ViewType",
    "make_identifier",
]
