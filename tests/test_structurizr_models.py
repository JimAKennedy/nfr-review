# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for Structurizr DSL models and emitter."""

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
    make_identifier,
)


class TestMakeIdentifier:
    def test_simple_name(self) -> None:
        assert make_identifier("OrderService") == "orderservice"

    def test_spaces_and_hyphens(self) -> None:
        assert make_identifier("my-api service") == "my_api_service"

    def test_leading_digit(self) -> None:
        assert make_identifier("123service") == "_123service"

    def test_special_chars(self) -> None:
        assert make_identifier("foo@bar.baz") == "foo_bar_baz"

    def test_empty_string(self) -> None:
        assert make_identifier("") == "_"

    def test_consecutive_underscores_collapsed(self) -> None:
        assert make_identifier("a--b__c") == "a_b_c"


class TestDslElementValidation:
    def test_valid_identifier(self) -> None:
        elem = DslElement(
            identifier="my_service",
            element_type="softwareSystem",
            name="My Service",
        )
        assert elem.identifier == "my_service"

    def test_invalid_identifier_rejected(self) -> None:
        with pytest.raises(ValueError, match="Identifier must match"):
            DslElement(
                identifier="my-service",
                element_type="softwareSystem",
                name="My Service",
            )

    def test_identifier_with_leading_digit_rejected(self) -> None:
        with pytest.raises(ValueError, match="Identifier must match"):
            DslElement(
                identifier="1service",
                element_type="softwareSystem",
                name="Service",
            )


class TestEmitMinimalWorkspace:
    def test_empty_workspace(self) -> None:
        ws = DslWorkspace(name="Test")
        dsl = emit_workspace_dsl(ws)
        assert dsl.startswith('workspace "Test" {')
        assert "!identifiers hierarchical" in dsl
        assert "model {" in dsl
        assert dsl.strip().endswith("}")

    def test_workspace_without_hierarchical(self) -> None:
        ws = DslWorkspace(name="Flat", use_hierarchical_identifiers=False)
        dsl = emit_workspace_dsl(ws)
        assert "!identifiers hierarchical" not in dsl

    def test_implied_relationships_disabled(self) -> None:
        ws = DslWorkspace(name="NoImplied", implied_relationships=False)
        dsl = emit_workspace_dsl(ws)
        assert "!impliedRelationships false" in dsl


class TestEmitElements:
    def test_person(self) -> None:
        ws = DslWorkspace(
            name="Test",
            model=DslModel(
                people=[
                    DslElement(
                        identifier="user",
                        element_type="person",
                        name="End User",
                        description="A user of the system",
                    )
                ]
            ),
        )
        dsl = emit_workspace_dsl(ws)
        assert 'user = person "End User" "A user of the system"' in dsl

    def test_system_with_container(self) -> None:
        ws = DslWorkspace(
            name="Test",
            model=DslModel(
                software_systems=[
                    DslElement(
                        identifier="backend",
                        element_type="softwareSystem",
                        name="Backend",
                        description="Main backend system",
                        children=[
                            DslElement(
                                identifier="api",
                                element_type="container",
                                name="API",
                                description="REST API",
                                technology="Python/FastAPI",
                            )
                        ],
                    )
                ]
            ),
        )
        dsl = emit_workspace_dsl(ws)
        assert 'backend = softwareSystem "Backend" "Main backend system" {' in dsl
        assert 'api = container "API" "REST API" "Python/FastAPI"' in dsl

    def test_element_with_tags_and_properties(self) -> None:
        ws = DslWorkspace(
            name="Test",
            model=DslModel(
                software_systems=[
                    DslElement(
                        identifier="db",
                        element_type="softwareSystem",
                        name="Database",
                        tags=["Storage", "Critical"],
                        properties=[
                            DslProperty(key="owner", value="platform-team"),
                        ],
                    )
                ]
            ),
        )
        dsl = emit_workspace_dsl(ws)
        assert 'tags "Storage" "Critical"' in dsl
        assert '"owner" "platform-team"' in dsl

    def test_container_with_technology_no_description(self) -> None:
        ws = DslWorkspace(
            name="Test",
            model=DslModel(
                software_systems=[
                    DslElement(
                        identifier="sys",
                        element_type="softwareSystem",
                        name="Sys",
                        children=[
                            DslElement(
                                identifier="web",
                                element_type="container",
                                name="Web App",
                                technology="React",
                            )
                        ],
                    )
                ]
            ),
        )
        dsl = emit_workspace_dsl(ws)
        assert 'web = container "Web App" "" "React"' in dsl


class TestEmitRelationships:
    def test_explicit_relationship(self) -> None:
        ws = DslWorkspace(
            name="Test",
            model=DslModel(
                software_systems=[
                    DslElement(
                        identifier="a",
                        element_type="softwareSystem",
                        name="A",
                    ),
                    DslElement(
                        identifier="b",
                        element_type="softwareSystem",
                        name="B",
                    ),
                ],
                relationships=[
                    DslRelationship(
                        source_id="a",
                        destination_id="b",
                        description="Uses",
                        technology="REST/HTTPS",
                    )
                ],
            ),
        )
        dsl = emit_workspace_dsl(ws)
        assert 'a -> b "Uses" "REST/HTTPS"' in dsl

    def test_implicit_relationship(self) -> None:
        ws = DslWorkspace(
            name="Test",
            model=DslModel(
                software_systems=[
                    DslElement(
                        identifier="svc",
                        element_type="softwareSystem",
                        name="Service",
                        implicit_relationships=[
                            DslRelationship(
                                source_id="svc",
                                destination_id="db",
                                description="Reads from",
                            )
                        ],
                    ),
                    DslElement(
                        identifier="db",
                        element_type="softwareSystem",
                        name="Database",
                    ),
                ]
            ),
        )
        dsl = emit_workspace_dsl(ws)
        assert '-> db "Reads from"' in dsl

    def test_relationship_with_tags(self) -> None:
        ws = DslWorkspace(
            name="Test",
            model=DslModel(
                software_systems=[
                    DslElement(identifier="a", element_type="softwareSystem", name="A"),
                    DslElement(identifier="b", element_type="softwareSystem", name="B"),
                ],
                relationships=[
                    DslRelationship(
                        source_id="a",
                        destination_id="b",
                        description="Events",
                        technology="Kafka",
                        tags=["Async"],
                    )
                ],
            ),
        )
        dsl = emit_workspace_dsl(ws)
        assert 'a -> b "Events" "Kafka" {' in dsl
        assert 'tags "Async"' in dsl


class TestEmitGroups:
    def test_group_with_elements(self) -> None:
        ws = DslWorkspace(
            name="Test",
            model=DslModel(
                groups=[
                    DslGroup(
                        name="Internal",
                        elements=[
                            DslElement(
                                identifier="svc",
                                element_type="softwareSystem",
                                name="Internal Service",
                            )
                        ],
                    )
                ]
            ),
        )
        dsl = emit_workspace_dsl(ws)
        assert 'group "Internal" {' in dsl
        assert 'svc = softwareSystem "Internal Service"' in dsl


class TestEmitViews:
    def test_system_landscape_view(self) -> None:
        ws = DslWorkspace(
            name="Test",
            views=[
                DslView(
                    view_type="systemLandscape",
                    key="landscape",
                    description="Overview",
                    content=DslViewContent(
                        include=["*"],
                        auto_layout=DslAutoLayout(direction="tb"),
                    ),
                )
            ],
        )
        dsl = emit_workspace_dsl(ws)
        assert 'systemLandscape "landscape" "Overview" {' in dsl
        assert "include *" in dsl
        assert "autoLayout tb" in dsl

    def test_container_view_with_scope(self) -> None:
        ws = DslWorkspace(
            name="Test",
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
                    view_type="container",
                    scope_id="sys",
                    key="containers",
                    content=DslViewContent(
                        include=["*"],
                        auto_layout=DslAutoLayout(direction="lr"),
                    ),
                )
            ],
        )
        dsl = emit_workspace_dsl(ws)
        assert 'container sys "containers" {' in dsl


class TestEmitDynamicViews:
    def test_dynamic_view_with_steps(self) -> None:
        ws = DslWorkspace(
            name="Test",
            dynamic_views=[
                DslDynamicView(
                    scope_id="sys",
                    key="checkout_flow",
                    description="Checkout",
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
        dsl = emit_workspace_dsl(ws)
        assert 'dynamic sys "checkout_flow" "Checkout" {' in dsl
        assert 'user -> api "POST /orders"' in dsl
        assert 'api -> db "Insert order"' in dsl
        assert "autoLayout lr" in dsl


class TestEmitStyles:
    def test_element_and_relationship_styles(self) -> None:
        ws = DslWorkspace(
            name="Test",
            styles=DslStyles(
                elements=[
                    DslElementStyle(
                        tag="Software System",
                        shape="RoundedBox",
                        background="#1168bd",
                        color="#ffffff",
                    )
                ],
                relationships=[
                    DslRelationshipStyle(
                        tag="Async",
                        style="dashed",
                        color="#707070",
                    )
                ],
            ),
        )
        dsl = emit_workspace_dsl(ws)
        assert "styles {" in dsl
        assert 'element "Software System" {' in dsl
        assert "shape RoundedBox" in dsl
        assert "background #1168bd" in dsl
        assert "color #ffffff" in dsl
        assert 'relationship "Async" {' in dsl
        assert "style dashed" in dsl


class TestEmitFullWorkspace:
    def test_realistic_workspace(self) -> None:
        """Emit a realistic multi-system workspace and verify structure."""
        ws = DslWorkspace(
            name="nfr-review Architecture",
            description="Auto-generated from scan",
            model=DslModel(
                people=[
                    DslElement(
                        identifier="dev",
                        element_type="person",
                        name="Developer",
                        description="Runs nfr-review scans",
                    )
                ],
                software_systems=[
                    DslElement(
                        identifier="nfr",
                        element_type="softwareSystem",
                        name="nfr-review",
                        description="NFR analysis tool",
                        children=[
                            DslElement(
                                identifier="cli",
                                element_type="container",
                                name="CLI",
                                technology="Python/Click",
                            ),
                            DslElement(
                                identifier="collectors",
                                element_type="container",
                                name="Collectors",
                                technology="Python",
                                tags=["Inferred"],
                            ),
                        ],
                    ),
                    DslElement(
                        identifier="target_repo",
                        element_type="softwareSystem",
                        name="Target Repository",
                        tags=["External"],
                    ),
                ],
                relationships=[
                    DslRelationship(
                        source_id="dev",
                        destination_id="nfr.cli",
                        description="Runs",
                    ),
                    DslRelationship(
                        source_id="nfr.collectors",
                        destination_id="target_repo",
                        description="Analyzes",
                        technology="File I/O",
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
                    scope_id="nfr",
                    key="nfr_containers",
                    content=DslViewContent(
                        include=["*"],
                        auto_layout=DslAutoLayout(direction="lr"),
                    ),
                ),
            ],
            styles=DslStyles(
                elements=[
                    DslElementStyle(
                        tag="External",
                        background="#999999",
                        shape="RoundedBox",
                    ),
                    DslElementStyle(
                        tag="Inferred",
                        border="dashed",
                    ),
                ],
                relationships=[
                    DslRelationshipStyle(
                        tag="Relationship",
                        thickness=2,
                    )
                ],
            ),
        )

        dsl = emit_workspace_dsl(ws)

        assert dsl.startswith('workspace "nfr-review Architecture"')
        assert "!identifiers hierarchical" in dsl
        assert 'dev = person "Developer"' in dsl
        assert 'nfr = softwareSystem "nfr-review"' in dsl
        assert 'cli = container "CLI"' in dsl
        assert 'dev -> nfr.cli "Runs"' in dsl
        assert 'nfr.collectors -> target_repo "Analyzes" "File I/O"' in dsl
        assert "systemLandscape" in dsl
        assert "container nfr" in dsl
        assert "styles {" in dsl

        for line in dsl.splitlines():
            stripped = line.strip()
            if stripped.endswith("{") and stripped != "{":
                kw = stripped.split()[0]
                assert (
                    kw
                    in {
                        "workspace",
                        "model",
                        "views",
                        "styles",
                        "element",
                        "relationship",
                        "group",
                        "properties",
                        "systemLandscape",
                        "systemContext",
                        "container",
                        "component",
                        "dynamic",
                        "deployment",
                        "filtered",
                        "custom",
                    }
                    or "=" in stripped
                ), f"Unexpected opening brace line: {stripped}"
            if stripped == "}":
                assert line.replace("}", "").replace(" ", "") == "" or line.strip() == "}"


class TestEmitQuoting:
    def test_description_with_quotes(self) -> None:
        ws = DslWorkspace(
            name="Test",
            model=DslModel(
                software_systems=[
                    DslElement(
                        identifier="svc",
                        element_type="softwareSystem",
                        name='My "Quoted" Service',
                    )
                ]
            ),
        )
        dsl = emit_workspace_dsl(ws)
        assert r"My \"Quoted\" Service" in dsl
