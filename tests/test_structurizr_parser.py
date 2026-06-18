# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for Structurizr DSL parser and round-trip validation."""

from __future__ import annotations

import pytest

from nfr_review.output.structurizr_dsl import emit_workspace_dsl
from nfr_review.structurizr_models import (
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
)
from nfr_review.structurizr_parser import DslParseError, parse_dsl


class TestParseMinimal:
    def test_empty_workspace(self) -> None:
        dsl = 'workspace "Test" {\n    model {\n    }\n}\n'
        ws = parse_dsl(dsl)
        assert ws.name == "Test"

    def test_workspace_name_and_description(self) -> None:
        dsl = 'workspace "My App" "Description here" {\n    model {\n    }\n}\n'
        ws = parse_dsl(dsl)
        assert ws.name == "My App"
        assert ws.description == "Description here"

    def test_hierarchical_identifiers(self) -> None:
        dsl = "workspace {\n    !identifiers hierarchical\n    model {\n    }\n}\n"
        ws = parse_dsl(dsl)
        assert ws.use_hierarchical_identifiers is True

    def test_implied_relationships_false(self) -> None:
        dsl = "workspace {\n    !impliedRelationships false\n    model {\n    }\n}\n"
        ws = parse_dsl(dsl)
        assert ws.implied_relationships is False


class TestParseElements:
    def test_person(self) -> None:
        dsl = """workspace {
            model {
                user = person "End User" "A user"
            }
        }"""
        ws = parse_dsl(dsl)
        assert len(ws.model.people) == 1
        assert ws.model.people[0].identifier == "user"
        assert ws.model.people[0].name == "End User"
        assert ws.model.people[0].description == "A user"

    def test_software_system(self) -> None:
        dsl = """workspace {
            model {
                sys = softwareSystem "My System" "The system"
            }
        }"""
        ws = parse_dsl(dsl)
        assert len(ws.model.software_systems) == 1
        assert ws.model.software_systems[0].name == "My System"

    def test_nested_containers(self) -> None:
        dsl = """workspace {
            model {
                sys = softwareSystem "Sys" {
                    api = container "API" "REST API" "Python"
                    db = container "Database" "" "PostgreSQL"
                }
            }
        }"""
        ws = parse_dsl(dsl)
        sys = ws.model.software_systems[0]
        assert len(sys.children) == 2
        assert sys.children[0].identifier == "api"
        assert sys.children[0].technology == "Python"
        assert sys.children[1].identifier == "db"
        assert sys.children[1].technology == "PostgreSQL"

    def test_nested_components(self) -> None:
        dsl = """workspace {
            model {
                sys = softwareSystem "Sys" {
                    api = container "API" {
                        ctrl = component "Controller" "Handles requests" "Spring MVC"
                    }
                }
            }
        }"""
        ws = parse_dsl(dsl)
        ctrl = ws.model.software_systems[0].children[0].children[0]
        assert ctrl.identifier == "ctrl"
        assert ctrl.name == "Controller"
        assert ctrl.technology == "Spring MVC"

    def test_element_with_tags_in_body(self) -> None:
        dsl = """workspace {
            model {
                db = softwareSystem "Database" {
                    tags "Storage" "Critical"
                }
            }
        }"""
        ws = parse_dsl(dsl)
        assert "Storage" in ws.model.software_systems[0].tags
        assert "Critical" in ws.model.software_systems[0].tags

    def test_element_with_properties(self) -> None:
        dsl = """workspace {
            model {
                svc = softwareSystem "Service" {
                    properties {
                        "owner" "platform-team"
                        version "2.0"
                    }
                }
            }
        }"""
        ws = parse_dsl(dsl)
        props = ws.model.software_systems[0].properties
        assert len(props) == 2
        assert props[0].key == "owner"
        assert props[0].value == "platform-team"


class TestParseRelationships:
    def test_explicit_relationship(self) -> None:
        dsl = """workspace {
            model {
                a = softwareSystem "A"
                b = softwareSystem "B"
                a -> b "Uses" "REST"
            }
        }"""
        ws = parse_dsl(dsl)
        assert len(ws.model.relationships) == 1
        rel = ws.model.relationships[0]
        assert rel.source_id == "a"
        assert rel.destination_id == "b"
        assert rel.description == "Uses"
        assert rel.technology == "REST"

    def test_implicit_relationship(self) -> None:
        dsl = """workspace {
            model {
                svc = softwareSystem "Service" {
                    -> db "Reads from"
                }
                db = softwareSystem "Database"
            }
        }"""
        ws = parse_dsl(dsl)
        svc = ws.model.software_systems[0]
        assert len(svc.implicit_relationships) == 1
        assert svc.implicit_relationships[0].destination_id == "db"
        assert svc.implicit_relationships[0].description == "Reads from"

    def test_relationship_with_tags(self) -> None:
        dsl = """workspace {
            model {
                a = softwareSystem "A"
                b = softwareSystem "B"
                a -> b "Events" "Kafka" {
                    tags "Async"
                }
            }
        }"""
        ws = parse_dsl(dsl)
        rel = ws.model.relationships[0]
        assert "Async" in rel.tags


class TestParseGroups:
    def test_group_with_elements(self) -> None:
        dsl = """workspace {
            model {
                group "Internal" {
                    svc = softwareSystem "Service"
                }
            }
        }"""
        ws = parse_dsl(dsl)
        assert len(ws.model.groups) == 1
        assert ws.model.groups[0].name == "Internal"
        assert len(ws.model.groups[0].elements) == 1


class TestParseViews:
    def test_system_landscape(self) -> None:
        dsl = """workspace {
            model { }
            views {
                systemLandscape "landscape" "Overview" {
                    include *
                    autoLayout tb
                }
            }
        }"""
        ws = parse_dsl(dsl)
        assert len(ws.views) == 1
        v = ws.views[0]
        assert v.view_type == "systemLandscape"
        assert v.key == "landscape"
        assert "*" in v.content.include
        assert v.content.auto_layout is not None
        assert v.content.auto_layout.direction == "tb"

    def test_container_view_with_scope(self) -> None:
        dsl = """workspace {
            model {
                sys = softwareSystem "Sys"
            }
            views {
                container sys "containers" {
                    include *
                    autoLayout lr
                }
            }
        }"""
        ws = parse_dsl(dsl)
        v = ws.views[0]
        assert v.view_type == "container"
        assert v.scope_id == "sys"
        assert v.key == "containers"

    def test_dynamic_view(self) -> None:
        dsl = """workspace {
            model {
                sys = softwareSystem "Sys"
            }
            views {
                dynamic sys "flow" "Checkout" {
                    user -> api "POST /orders"
                    api -> db "Insert"
                    autoLayout lr
                }
            }
        }"""
        ws = parse_dsl(dsl)
        assert len(ws.dynamic_views) == 1
        dv = ws.dynamic_views[0]
        assert dv.scope_id == "sys"
        assert dv.key == "flow"
        assert len(dv.steps) == 2
        assert dv.steps[0].description == "POST /orders"


class TestParseStyles:
    def test_element_style(self) -> None:
        dsl = """workspace {
            model { }
            views {
                styles {
                    element "Software System" {
                        shape RoundedBox
                        background #1168bd
                        color #ffffff
                    }
                }
            }
        }"""
        ws = parse_dsl(dsl)
        assert len(ws.styles.elements) == 1
        es = ws.styles.elements[0]
        assert es.tag == "Software System"
        assert es.shape == "RoundedBox"
        assert es.background == "#1168bd"

    def test_relationship_style(self) -> None:
        dsl = """workspace {
            model { }
            views {
                styles {
                    relationship "Async" {
                        style dashed
                        color #707070
                        thickness 2
                    }
                }
            }
        }"""
        ws = parse_dsl(dsl)
        assert len(ws.styles.relationships) == 1
        rs = ws.styles.relationships[0]
        assert rs.tag == "Async"
        assert rs.style == "dashed"
        assert rs.thickness == 2


class TestParseComments:
    def test_line_comments_ignored(self) -> None:
        dsl = """workspace {
            // This is a comment
            # This is also a comment
            model {
                svc = softwareSystem "Service"  // inline comment
            }
        }"""
        ws = parse_dsl(dsl)
        assert len(ws.model.software_systems) == 1

    def test_block_comments_ignored(self) -> None:
        dsl = """workspace {
            /* multi-line
               comment */
            model {
                svc = softwareSystem "Service"
            }
        }"""
        ws = parse_dsl(dsl)
        assert len(ws.model.software_systems) == 1


class TestParseErrors:
    def test_missing_workspace(self) -> None:
        with pytest.raises(DslParseError):
            parse_dsl("model { }")

    def test_unclosed_brace(self) -> None:
        with pytest.raises(DslParseError):
            parse_dsl('workspace { model { svc = softwareSystem "S"')


class TestRoundTrip:
    """Verify emit -> parse -> emit produces identical output."""

    def _round_trip(self, ws: DslWorkspace) -> None:
        dsl1 = emit_workspace_dsl(ws)
        parsed = parse_dsl(dsl1)
        dsl2 = emit_workspace_dsl(parsed)
        assert dsl1 == dsl2, (
            f"Round-trip mismatch:\n--- emitted ---\n{dsl1}\n--- re-emitted ---\n{dsl2}"
        )

    def test_minimal_workspace(self) -> None:
        self._round_trip(DslWorkspace(name="Test"))

    def test_workspace_with_elements(self) -> None:
        ws = DslWorkspace(
            name="Test",
            model=DslModel(
                people=[
                    DslElement(
                        identifier="user",
                        element_type="person",
                        name="User",
                        description="End user",
                    )
                ],
                software_systems=[
                    DslElement(
                        identifier="sys",
                        element_type="softwareSystem",
                        name="System",
                        description="Main system",
                        children=[
                            DslElement(
                                identifier="api",
                                element_type="container",
                                name="API",
                                description="REST API",
                                technology="Python",
                            ),
                            DslElement(
                                identifier="db",
                                element_type="container",
                                name="Database",
                                technology="PostgreSQL",
                                tags=["Storage"],
                            ),
                        ],
                    )
                ],
                relationships=[
                    DslRelationship(
                        source_id="user",
                        destination_id="sys.api",
                        description="Uses",
                        technology="HTTPS",
                    ),
                ],
            ),
        )
        self._round_trip(ws)

    def test_workspace_with_views_and_styles(self) -> None:
        ws = DslWorkspace(
            name="Styled",
            model=DslModel(
                software_systems=[
                    DslElement(
                        identifier="sys",
                        element_type="softwareSystem",
                        name="System",
                    )
                ]
            ),
            views=[
                DslView(
                    view_type="systemLandscape",
                    key="landscape",
                    description="Overview",
                    content=DslViewContent(
                        include=["*"],
                        auto_layout=DslAutoLayout(direction="tb"),
                    ),
                ),
                DslView(
                    view_type="container",
                    scope_id="sys",
                    key="containers",
                    content=DslViewContent(
                        include=["*"],
                        exclude=["element.tag==Internal"],
                        auto_layout=DslAutoLayout(direction="lr", rank_sep=300, node_sep=100),
                    ),
                ),
            ],
            styles=DslStyles(
                elements=[
                    DslElementStyle(
                        tag="Element",
                        shape="RoundedBox",
                        background="#1168bd",
                        color="#ffffff",
                    )
                ],
                relationships=[
                    DslRelationshipStyle(
                        tag="Relationship",
                        thickness=2,
                        color="#707070",
                    )
                ],
            ),
        )
        self._round_trip(ws)

    def test_workspace_with_dynamic_views(self) -> None:
        ws = DslWorkspace(
            name="Dynamic",
            dynamic_views=[
                DslDynamicView(
                    scope_id="sys",
                    key="checkout",
                    description="Checkout Flow",
                    steps=[
                        DslDynamicStep(
                            source_id="user",
                            destination_id="api",
                            description="POST /orders",
                        ),
                        DslDynamicStep(
                            source_id="api",
                            destination_id="db",
                            description="Insert order",
                        ),
                    ],
                    auto_layout=DslAutoLayout(direction="lr"),
                )
            ],
        )
        self._round_trip(ws)

    def test_workspace_with_groups_and_properties(self) -> None:
        ws = DslWorkspace(
            name="Grouped",
            model=DslModel(
                groups=[
                    DslGroup(
                        name="Internal Services",
                        elements=[
                            DslElement(
                                identifier="svc_a",
                                element_type="softwareSystem",
                                name="Service A",
                                tags=["Internal"],
                                properties=[
                                    DslProperty(key="owner", value="team-alpha"),
                                ],
                            )
                        ],
                    )
                ],
            ),
        )
        self._round_trip(ws)

    def test_realistic_multi_system_workspace(self) -> None:
        ws = DslWorkspace(
            name="E-Commerce Platform",
            description="Auto-generated architecture model",
            model=DslModel(
                people=[
                    DslElement(
                        identifier="customer",
                        element_type="person",
                        name="Customer",
                        description="Online shopper",
                    ),
                    DslElement(
                        identifier="admin",
                        element_type="person",
                        name="Admin",
                        description="Back-office user",
                    ),
                ],
                software_systems=[
                    DslElement(
                        identifier="storefront",
                        element_type="softwareSystem",
                        name="Storefront",
                        description="Customer-facing web app",
                        children=[
                            DslElement(
                                identifier="web",
                                element_type="container",
                                name="Web Frontend",
                                technology="React",
                            ),
                            DslElement(
                                identifier="bff",
                                element_type="container",
                                name="BFF",
                                description="Backend for frontend",
                                technology="Node.js",
                            ),
                        ],
                    ),
                    DslElement(
                        identifier="orders",
                        element_type="softwareSystem",
                        name="Order Service",
                        description="Handles order processing",
                        children=[
                            DslElement(
                                identifier="order_api",
                                element_type="container",
                                name="Order API",
                                technology="Go",
                            ),
                            DslElement(
                                identifier="order_db",
                                element_type="container",
                                name="Order DB",
                                technology="PostgreSQL",
                                tags=["Storage"],
                            ),
                        ],
                    ),
                    DslElement(
                        identifier="payments",
                        element_type="softwareSystem",
                        name="Payment Gateway",
                        tags=["External"],
                    ),
                ],
                relationships=[
                    DslRelationship(
                        source_id="customer",
                        destination_id="storefront.web",
                        description="Browses",
                        technology="HTTPS",
                    ),
                    DslRelationship(
                        source_id="storefront.bff",
                        destination_id="orders.order_api",
                        description="Places orders",
                        technology="gRPC",
                    ),
                    DslRelationship(
                        source_id="orders.order_api",
                        destination_id="payments",
                        description="Processes payment",
                        technology="REST/HTTPS",
                        tags=["CrossBoundary"],
                    ),
                ],
            ),
            views=[
                DslView(
                    view_type="systemLandscape",
                    key="landscape",
                    content=DslViewContent(
                        include=["*"],
                        auto_layout=DslAutoLayout(direction="tb"),
                    ),
                ),
                DslView(
                    view_type="container",
                    scope_id="storefront",
                    key="storefront_containers",
                    content=DslViewContent(
                        include=["*"],
                        auto_layout=DslAutoLayout(direction="lr"),
                    ),
                ),
                DslView(
                    view_type="container",
                    scope_id="orders",
                    key="orders_containers",
                    content=DslViewContent(
                        include=["*"],
                        auto_layout=DslAutoLayout(direction="lr"),
                    ),
                ),
            ],
            dynamic_views=[
                DslDynamicView(
                    scope_id="orders",
                    key="place_order",
                    description="Place Order Flow",
                    steps=[
                        DslDynamicStep(
                            source_id="storefront.bff",
                            destination_id="orders.order_api",
                            description="POST /orders",
                        ),
                        DslDynamicStep(
                            source_id="orders.order_api",
                            destination_id="orders.order_db",
                            description="INSERT order",
                        ),
                        DslDynamicStep(
                            source_id="orders.order_api",
                            destination_id="payments",
                            description="Charge card",
                        ),
                    ],
                    auto_layout=DslAutoLayout(direction="lr"),
                ),
            ],
            styles=DslStyles(
                elements=[
                    DslElementStyle(
                        tag="Element",
                        shape="RoundedBox",
                    ),
                    DslElementStyle(
                        tag="External",
                        background="#999999",
                        color="#ffffff",
                    ),
                    DslElementStyle(
                        tag="Storage",
                        shape="Cylinder",
                    ),
                ],
                relationships=[
                    DslRelationshipStyle(
                        tag="Relationship",
                        thickness=2,
                    ),
                    DslRelationshipStyle(
                        tag="CrossBoundary",
                        style="dashed",
                        color="#ff0000",
                    ),
                ],
            ),
        )
        self._round_trip(ws)
