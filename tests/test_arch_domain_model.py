# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for domain model inference."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nfr_review.arch_domain_model import (
    analyze_domain_model,
    enhance_domain_model_with_llm,
    generate_context_map_mermaid,
    infer_bounded_contexts,
    infer_entities_from_models,
)
from nfr_review.arch_models import (
    BoundedContext,
    Component,
    ComponentBoundary,
    DomainEntity,
    EntityRelationship,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure."""
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def sample_components() -> list[Component]:
    """A handful of components for bounded-context mapping."""
    return [
        Component(
            id="comp-orders-abc123",
            name="orders",
            description="Order processing service",
            component_type="service",
            boundaries=[
                ComponentBoundary(boundary_type="package", path="orders/", repo="myapp")
            ],
        ),
        Component(
            id="comp-users-def456",
            name="users",
            description="User management service",
            component_type="service",
            boundaries=[
                ComponentBoundary(boundary_type="package", path="users/", repo="myapp")
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# Django model extraction
# ---------------------------------------------------------------------------


class TestDjangoModels:
    def test_basic_django_model(self, tmp_repo: Path) -> None:
        models_dir = tmp_repo / "orders"
        models_dir.mkdir()
        (models_dir / "models.py").write_text(
            """\
from django.db import models

class Order(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20)
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        assert len(entities) == 1
        assert entities[0].name == "Order"
        assert "created_at" in entities[0].attributes
        assert "total" in entities[0].attributes
        assert "status" in entities[0].attributes

    def test_django_foreign_key(self, tmp_repo: Path) -> None:
        models_dir = tmp_repo / "orders"
        models_dir.mkdir()
        (models_dir / "models.py").write_text(
            """\
from django.db import models

class Customer(models.Model):
    name = models.CharField(max_length=100)

class Order(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    total = models.DecimalField(max_digits=10, decimal_places=2)
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        order = next(e for e in entities if e.name == "Order")
        assert len(order.relationships) == 1
        assert order.relationships[0].target_entity == "Customer"
        assert order.relationships[0].relationship_type == "belongs_to"

    def test_django_many_to_many(self, tmp_repo: Path) -> None:
        models_dir = tmp_repo / "courses"
        models_dir.mkdir()
        (models_dir / "models.py").write_text(
            """\
from django.db import models

class Student(models.Model):
    name = models.CharField(max_length=100)

class Course(models.Model):
    title = models.CharField(max_length=200)
    students = models.ManyToManyField(Student)
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        course = next(e for e in entities if e.name == "Course")
        assert any(
            r.relationship_type == "many_to_many" and r.target_entity == "Student"
            for r in course.relationships
        )

    def test_django_one_to_one(self, tmp_repo: Path) -> None:
        models_dir = tmp_repo / "profiles"
        models_dir.mkdir()
        (models_dir / "models.py").write_text(
            """\
from django.db import models

class User(models.Model):
    username = models.CharField(max_length=100)

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField()
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        profile = next(e for e in entities if e.name == "Profile")
        assert any(
            r.relationship_type == "has_one" and r.target_entity == "User"
            for r in profile.relationships
        )


# ---------------------------------------------------------------------------
# SQLAlchemy model extraction
# ---------------------------------------------------------------------------


class TestSQLAlchemyModels:
    def test_sqlalchemy_model(self, tmp_repo: Path) -> None:
        models_dir = tmp_repo / "warehouse"
        models_dir.mkdir()
        (models_dir / "models.py").write_text(
            """\
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import Column, Integer, String, ForeignKey

class Base(DeclarativeBase):
    pass

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    category_id = Column(Integer, ForeignKey("categories.id"))
    category = relationship("Category", back_populates="products")
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        # Should pick up Product (Base is a base class, not an entity itself in this case)
        product = next((e for e in entities if e.name == "Product"), None)
        assert product is not None
        assert "name" in product.attributes

        # Should detect ForeignKey relationship
        fk_rels = [r for r in product.relationships if r.relationship_type == "belongs_to"]
        assert len(fk_rels) >= 1
        assert fk_rels[0].target_entity == "categories"

        # Should detect relationship()
        rel_rels = [r for r in product.relationships if r.relationship_type == "has_many"]
        assert len(rel_rels) >= 1
        assert rel_rels[0].target_entity == "Category"

    def test_sqlalchemy_db_model(self, tmp_repo: Path) -> None:
        """Flask-SQLAlchemy db.Model pattern."""
        models_dir = tmp_repo / "app"
        models_dir.mkdir()
        (models_dir / "models.py").write_text(
            """\
from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120))
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        assert len(entities) == 1
        assert entities[0].name == "User"


# ---------------------------------------------------------------------------
# Pydantic model extraction
# ---------------------------------------------------------------------------


class TestPydanticModels:
    def test_pydantic_basemodel(self, tmp_repo: Path) -> None:
        schemas_dir = tmp_repo / "api"
        schemas_dir.mkdir()
        (schemas_dir / "schemas.py").write_text(
            """\
from pydantic import BaseModel, Field

class OrderCreate(BaseModel):
    customer_id: int
    items: list[str] = Field(default_factory=list)
    total: float
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        assert len(entities) == 1
        assert entities[0].name == "OrderCreate"
        assert "customer_id" in entities[0].attributes
        assert "items" in entities[0].attributes
        assert "total" in entities[0].attributes

    def test_pydantic_skips_model_config(self, tmp_repo: Path) -> None:
        schemas_dir = tmp_repo / "api"
        schemas_dir.mkdir()
        (schemas_dir / "schemas.py").write_text(
            """\
from pydantic import BaseModel, ConfigDict

class MyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value: int
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        assert len(entities) == 1
        assert "model_config" not in entities[0].attributes
        assert "name" in entities[0].attributes

    def test_pydantic_not_in_model_file_still_detected(self, tmp_repo: Path) -> None:
        """Files not named models.py should still be detected if they contain BaseModel."""
        pkg = tmp_repo / "myapp"
        pkg.mkdir()
        (pkg / "dto.py").write_text(
            """\
from pydantic import BaseModel

class ItemDTO(BaseModel):
    name: str
    price: float
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        assert len(entities) == 1
        assert entities[0].name == "ItemDTO"


# ---------------------------------------------------------------------------
# JPA / Java entity extraction
# ---------------------------------------------------------------------------


class TestJavaEntities:
    def test_jpa_entity(self, tmp_repo: Path) -> None:
        java_dir = tmp_repo / "src" / "main" / "java" / "com" / "example"
        java_dir.mkdir(parents=True)
        (java_dir / "Order.java").write_text(
            """\
package com.example;

import javax.persistence.*;
import java.util.List;

@Entity
@Table(name = "orders")
public class Order {
    @Id
    @GeneratedValue
    private Long id;

    private String status;
    private Double total;

    @ManyToOne
    private Customer customer;

    @OneToMany(mappedBy = "order")
    private List<OrderItem> items;
}
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        assert len(entities) == 1
        order = entities[0]
        assert order.name == "Order"
        assert "id" in order.attributes
        assert "status" in order.attributes
        assert "total" in order.attributes

        # Check relationships
        m2o = [r for r in order.relationships if r.relationship_type == "belongs_to"]
        assert len(m2o) >= 1

        o2m = [r for r in order.relationships if r.relationship_type == "has_many"]
        assert len(o2m) >= 1
        assert any(r.target_entity == "OrderItem" for r in o2m)

    def test_jpa_many_to_many(self, tmp_repo: Path) -> None:
        java_dir = tmp_repo / "src" / "main" / "java" / "com" / "school"
        java_dir.mkdir(parents=True)
        (java_dir / "Student.java").write_text(
            """\
package com.school;

import javax.persistence.*;
import java.util.Set;

@Entity
public class Student {
    @Id
    private Long id;

    private String name;

    @ManyToMany
    private Set<Course> courses;
}
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        assert len(entities) == 1
        student = entities[0]
        m2m = [r for r in student.relationships if r.relationship_type == "many_to_many"]
        assert len(m2m) >= 1
        assert any(r.target_entity == "Course" for r in m2m)

    def test_no_entity_annotation_skipped(self, tmp_repo: Path) -> None:
        """Java classes without @Entity should not be picked up."""
        java_dir = tmp_repo / "src" / "main" / "java" / "com" / "example"
        java_dir.mkdir(parents=True)
        (java_dir / "Helper.java").write_text(
            """\
package com.example;

public class Helper {
    private String name;

    public String getName() { return name; }
}
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        assert len(entities) == 0


# ---------------------------------------------------------------------------
# Bounded context inference
# ---------------------------------------------------------------------------


class TestBoundedContexts:
    def test_groups_by_context_hint(self, sample_components: list[Component]) -> None:
        entities = [
            DomainEntity(
                name="Order",
                description="Order model",
                bounded_context="orders",
            ),
            DomainEntity(
                name="OrderItem",
                description="Order item model",
                bounded_context="orders",
            ),
            DomainEntity(
                name="User",
                description="User model",
                bounded_context="users",
            ),
        ]

        contexts = infer_bounded_contexts(entities, sample_components)
        assert len(contexts) == 2

        orders_ctx = next(c for c in contexts if "Order" in c.name)
        assert "Order" in orders_ctx.entities
        assert "OrderItem" in orders_ctx.entities

        users_ctx = next(c for c in contexts if "User" in c.name)
        assert "User" in users_ctx.entities

    def test_maps_to_components(self, sample_components: list[Component]) -> None:
        entities = [
            DomainEntity(
                name="Order",
                description="test",
                bounded_context="orders",
            ),
        ]

        contexts = infer_bounded_contexts(entities, sample_components)
        orders_ctx = next(c for c in contexts if "Order" in c.name)
        assert "comp-orders-abc123" in orders_ctx.component_ids

    def test_cross_context_relationships(self, sample_components: list[Component]) -> None:
        entities = [
            DomainEntity(
                name="Order",
                description="test",
                bounded_context="orders",
                relationships=[
                    EntityRelationship(
                        target_entity="User",
                        relationship_type="belongs_to",
                    )
                ],
            ),
            DomainEntity(
                name="User",
                description="test",
                bounded_context="users",
            ),
        ]

        contexts = infer_bounded_contexts(entities, sample_components)
        orders_ctx = next(c for c in contexts if "Order" in c.name)
        users_ctx = next(c for c in contexts if "User" in c.name)

        assert users_ctx.name in orders_ctx.upstream_contexts
        assert orders_ctx.name in users_ctx.downstream_contexts

    def test_empty_entities(self, sample_components: list[Component]) -> None:
        contexts = infer_bounded_contexts([], sample_components)
        assert contexts == []

    def test_default_context_when_no_hint(self, sample_components: list[Component]) -> None:
        entities = [
            DomainEntity(
                name="Thing",
                description="test",
                bounded_context=None,
            ),
        ]

        contexts = infer_bounded_contexts(entities, sample_components)
        assert len(contexts) == 1
        assert contexts[0].name == "Default"
        assert "Thing" in contexts[0].entities


# ---------------------------------------------------------------------------
# Mermaid context map generation
# ---------------------------------------------------------------------------


class TestMermaidContextMap:
    def test_generates_flowchart(self) -> None:
        contexts = [
            BoundedContext(
                name="Orders",
                description="Order context",
                entities=["Order", "OrderItem"],
            ),
            BoundedContext(
                name="Users",
                description="User context",
                entities=["User"],
                downstream_contexts=["Orders"],
            ),
        ]

        mermaid = generate_context_map_mermaid(contexts)
        assert "flowchart LR" in mermaid
        assert "Orders" in mermaid
        assert "Users" in mermaid
        assert "2 entities" in mermaid
        assert "1 entities" in mermaid

    def test_includes_edges(self) -> None:
        contexts = [
            BoundedContext(
                name="Orders",
                description="Order context",
                entities=["Order"],
                upstream_contexts=["Users"],
            ),
            BoundedContext(
                name="Users",
                description="User context",
                entities=["User"],
                downstream_contexts=["Orders"],
            ),
        ]

        mermaid = generate_context_map_mermaid(contexts)
        assert "-->" in mermaid

    def test_empty_contexts(self) -> None:
        assert generate_context_map_mermaid([]) == ""

    def test_single_context_no_edges(self) -> None:
        contexts = [
            BoundedContext(
                name="Core",
                description="Core context",
                entities=["Foo"],
            ),
        ]

        mermaid = generate_context_map_mermaid(contexts)
        assert "flowchart LR" in mermaid
        assert "-->" not in mermaid


# ---------------------------------------------------------------------------
# LLM enhancement
# ---------------------------------------------------------------------------


class TestLlmEnhancement:
    def test_enhances_descriptions(self) -> None:
        entities = [
            DomainEntity(name="Order", description="Django model in models.py"),
        ]
        contexts = [
            BoundedContext(
                name="Orders",
                description="Bounded context containing 1 entities",
                entities=["Order"],
            ),
        ]
        components: list[Component] = []

        llm = MagicMock()
        llm.available = True
        llm.analyze.return_value = (
            '{"entities": [{"name": "Order", "description": '
            '"Represents a customer purchase transaction", '
            '"additional_relationships": [], "suggested_context": "Orders"}], '
            '"context_refinements": [{"original_name": "Orders", '
            '"suggested_name": "Order Management", '
            '"description": "Handles the full order lifecycle"}]}'
        )

        result = enhance_domain_model_with_llm(entities, contexts, components, llm)
        assert result.entities[0].description == "Represents a customer purchase transaction"
        assert result.bounded_contexts[0].name == "Order Management"
        llm.analyze.assert_called_once()

    def test_adds_relationships_from_llm(self) -> None:
        entities = [
            DomainEntity(name="Order", description="test"),
        ]
        contexts: list[BoundedContext] = []
        components: list[Component] = []

        llm = MagicMock()
        llm.available = True
        llm.analyze.return_value = (
            '{"entities": [{"name": "Order", "description": "test", '
            '"additional_relationships": [{"target_entity": "Invoice", '
            '"relationship_type": "has_one", "description": "inferred"}], '
            '"suggested_context": null}], "context_refinements": []}'
        )

        result = enhance_domain_model_with_llm(entities, contexts, components, llm)
        order = result.entities[0]
        assert any(
            r.target_entity == "Invoice" and r.relationship_type == "has_one"
            for r in order.relationships
        )

    def test_handles_json_in_code_fences(self) -> None:
        entities = [
            DomainEntity(name="Foo", description="test"),
        ]
        contexts: list[BoundedContext] = []
        components: list[Component] = []

        llm = MagicMock()
        llm.available = True
        llm.analyze.return_value = (
            "Here is the analysis:\n```json\n"
            '{"entities": [{"name": "Foo", "description": "A foo thing", '
            '"additional_relationships": [], "suggested_context": null}], '
            '"context_refinements": []}\n```'
        )

        result = enhance_domain_model_with_llm(entities, contexts, components, llm)
        assert result.entities[0].description == "A foo thing"

    def test_llm_unavailable_returns_structural(self) -> None:
        entities = [
            DomainEntity(name="Order", description="original"),
        ]
        contexts = [
            BoundedContext(
                name="Orders",
                description="context",
                entities=["Order"],
            ),
        ]

        from nfr_review.llm_client import LlmUnavailableError

        llm = MagicMock()
        llm.available = True
        llm.analyze.side_effect = LlmUnavailableError("no key")

        result = enhance_domain_model_with_llm(entities, contexts, [], llm)
        assert result.entities[0].description == "original"
        assert result.bounded_contexts[0].name == "Orders"

    def test_llm_error_returns_structural(self) -> None:
        entities = [
            DomainEntity(name="Order", description="original"),
        ]
        contexts: list[BoundedContext] = []

        llm = MagicMock()
        llm.available = True
        llm.analyze.side_effect = RuntimeError("API error")

        result = enhance_domain_model_with_llm(entities, contexts, [], llm)
        assert result.entities[0].description == "original"

    def test_bad_json_returns_structural(self) -> None:
        entities = [
            DomainEntity(name="Order", description="original"),
        ]
        contexts: list[BoundedContext] = []

        llm = MagicMock()
        llm.available = True
        llm.analyze.return_value = "This is not valid JSON at all"

        result = enhance_domain_model_with_llm(entities, contexts, [], llm)
        assert result.entities[0].description == "original"


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


class TestAnalyzeDomainModel:
    def test_returns_none_when_no_entities(self, tmp_repo: Path) -> None:
        result = analyze_domain_model([tmp_repo], [])
        assert result is None

    def test_returns_section_with_entities(self, tmp_repo: Path) -> None:
        models_dir = tmp_repo / "myapp"
        models_dir.mkdir()
        (models_dir / "models.py").write_text(
            """\
from django.db import models

class Product(models.Model):
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=8, decimal_places=2)
"""
        )

        result = analyze_domain_model([tmp_repo], [])
        assert result is not None
        assert len(result.entities) == 1
        assert result.entities[0].name == "Product"
        assert len(result.bounded_contexts) >= 1

    def test_with_llm_calls_enhance(self, tmp_repo: Path) -> None:
        models_dir = tmp_repo / "shop"
        models_dir.mkdir()
        (models_dir / "models.py").write_text(
            """\
from django.db import models

class Item(models.Model):
    name = models.CharField(max_length=100)
"""
        )

        llm = MagicMock()
        llm.available = True
        llm.analyze.return_value = '{"entities": [], "context_refinements": []}'

        result = analyze_domain_model([tmp_repo], [], llm=llm)
        assert result is not None
        llm.analyze.assert_called_once()

    def test_llm_none_skips_enhance(self, tmp_repo: Path) -> None:
        models_dir = tmp_repo / "shop"
        models_dir.mkdir()
        (models_dir / "models.py").write_text(
            """\
from django.db import models

class Item(models.Model):
    name = models.CharField(max_length=100)
"""
        )

        result = analyze_domain_model([tmp_repo], [], llm=None)
        assert result is not None
        assert result.entities[0].name == "Item"

    def test_llm_not_available_skips_enhance(self, tmp_repo: Path) -> None:
        models_dir = tmp_repo / "shop"
        models_dir.mkdir()
        (models_dir / "models.py").write_text(
            """\
from django.db import models

class Item(models.Model):
    name = models.CharField(max_length=100)
"""
        )

        llm = MagicMock()
        llm.available = False

        result = analyze_domain_model([tmp_repo], [], llm=llm)
        assert result is not None
        llm.analyze.assert_not_called()


# ---------------------------------------------------------------------------
# Skipping hidden dirs
# ---------------------------------------------------------------------------


class TestSkipDirs:
    def test_skips_hidden_dirs(self, tmp_repo: Path) -> None:
        hidden = tmp_repo / "__pycache__" / "models.py"
        hidden.parent.mkdir(parents=True)
        hidden.write_text(
            """\
from django.db import models

class Cached(models.Model):
    x = models.IntegerField()
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        assert len(entities) == 0

    def test_skips_node_modules(self, tmp_repo: Path) -> None:
        nm = tmp_repo / "node_modules" / "pkg" / "models.py"
        nm.parent.mkdir(parents=True)
        nm.write_text(
            """\
from pydantic import BaseModel

class Hidden(BaseModel):
    x: int
"""
        )

        entities = infer_entities_from_models([tmp_repo])
        assert len(entities) == 0


# ---------------------------------------------------------------------------
# Multi-repo
# ---------------------------------------------------------------------------


class TestMultiRepo:
    def test_entities_from_multiple_repos(self, tmp_path: Path) -> None:
        repo_a = tmp_path / "repo_a"
        repo_a.mkdir()
        (repo_a / "models.py").write_text(
            """\
from django.db import models

class Alpha(models.Model):
    name = models.CharField(max_length=50)
"""
        )

        repo_b = tmp_path / "repo_b"
        repo_b.mkdir()
        (repo_b / "models.py").write_text(
            """\
from django.db import models

class Beta(models.Model):
    value = models.IntegerField()
"""
        )

        entities = infer_entities_from_models([repo_a, repo_b])
        names = {e.name for e in entities}
        assert "Alpha" in names
        assert "Beta" in names

    def test_deduplication(self, tmp_path: Path) -> None:
        """Same entity name in two repos: first wins."""
        repo_a = tmp_path / "repo_a"
        repo_a.mkdir()
        (repo_a / "models.py").write_text(
            """\
from django.db import models

class Shared(models.Model):
    name = models.CharField(max_length=50)
"""
        )

        repo_b = tmp_path / "repo_b"
        repo_b.mkdir()
        (repo_b / "models.py").write_text(
            """\
from django.db import models

class Shared(models.Model):
    other = models.IntegerField()
"""
        )

        entities = infer_entities_from_models([repo_a, repo_b])
        shared_entities = [e for e in entities if e.name == "Shared"]
        assert len(shared_entities) == 1


# ---------------------------------------------------------------------------
# Empty inputs
# ---------------------------------------------------------------------------


class TestEmptyInputs:
    def test_no_repos(self) -> None:
        entities = infer_entities_from_models([])
        assert entities == []

    def test_empty_repo(self, tmp_repo: Path) -> None:
        entities = infer_entities_from_models([tmp_repo])
        assert entities == []

    def test_bounded_contexts_no_entities(self) -> None:
        contexts = infer_bounded_contexts([], [])
        assert contexts == []

    def test_mermaid_no_contexts(self) -> None:
        assert generate_context_map_mermaid([]) == ""

    def test_analyze_empty(self, tmp_repo: Path) -> None:
        assert analyze_domain_model([tmp_repo], []) is None
