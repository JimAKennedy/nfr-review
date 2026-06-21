# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Domain model inference for architecture documentation.

Scans source code for ORM models, Pydantic models, JPA entities, and Django
models to infer domain entities, relationships, and bounded contexts.
Structural inference runs without an LLM; an optional LLM pass enhances
descriptions and discovers missing relationships.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from nfr_review.arch_models import (
    BoundedContext,
    Component,
    DomainEntity,
    DomainModelSection,
    EntityRelationship,
)
from nfr_review.arch_utils import safe_read_text as _safe_read_text
from nfr_review.llm_client import (
    LlmUnavailableError,
    serialize_evidence_bundle,
)
from nfr_review.protocols import LlmClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Directories to skip (mirrors arch_discovery._HIDDEN_DIRS)
# ---------------------------------------------------------------------------

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        ".idea",
        ".vscode",
        ".gsd",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        "target",
        "build",
        "dist",
        ".gradle",
    }
)


# ---------------------------------------------------------------------------
# Relationship-type mappings
# ---------------------------------------------------------------------------

# Python ORM relationship markers -> EntityRelationship.relationship_type
_PYTHON_REL_MAP: dict[str, str] = {
    "ForeignKey": "belongs_to",
    "OneToOneField": "has_one",
    "ManyToManyField": "many_to_many",
    # SQLAlchemy
    "relationship": "has_many",  # default; refined by back_populates later
}

# Java/JPA annotation -> EntityRelationship.relationship_type
_JAVA_REL_MAP: dict[str, str] = {
    "ManyToOne": "belongs_to",
    "OneToMany": "has_many",
    "OneToOne": "has_one",
    "ManyToMany": "many_to_many",
}

# ---------------------------------------------------------------------------
# Python model extraction
# ---------------------------------------------------------------------------

# Matches class Foo(SomeBase): capturing name and bases
_PY_CLASS_RE = re.compile(r"^class\s+(\w+)\s*\(([^)]+)\)\s*:", re.MULTILINE)

# Django / SQLAlchemy field lines  e.g.  name = models.CharField(...)
_PY_FIELD_RE = re.compile(r"^\s{4}(\w+)\s*[:=]", re.MULTILINE)

# Django FK:  field = models.ForeignKey(TargetModel, ...)
_DJANGO_FK_RE = re.compile(
    r"^\s{4}(\w+)\s*=\s*models\.(ForeignKey|OneToOneField|ManyToManyField)"
    r"\s*\(\s*['\"]?(\w+)['\"]?",
    re.MULTILINE,
)

# SQLAlchemy relationship():  items = relationship("Item", ...)
_SA_REL_RE = re.compile(
    r"^\s{4}(\w+)\s*=\s*relationship\s*\(\s*['\"](\w+)['\"]",
    re.MULTILINE,
)

# SQLAlchemy Column with ForeignKey:  user_id = Column(Integer, ForeignKey("users.id"))
_SA_FK_RE = re.compile(
    r"^\s{4}(\w+)\s*=\s*(?:mapped_column|Column)\s*\([^)]*ForeignKey\s*\(\s*['\"](\w+)\.",
    re.MULTILINE,
)

# Pydantic BaseModel field:  name: str = Field(...)   or   name: str
_PYDANTIC_FIELD_RE = re.compile(r"^\s{4}(\w+)\s*:", re.MULTILINE)

# Django model bases we recognise
_DJANGO_BASES = {"models.Model", "Model"}

# SQLAlchemy bases
_SA_BASES = {"Base", "DeclarativeBase", "DeclarativeMeta"}

# Pydantic bases
_PYDANTIC_BASES = {"BaseModel", "BaseSettings"}


def _is_model_class(bases_str: str) -> str | None:
    """Return the framework name if *bases_str* indicates a model class."""
    bases = [b.strip() for b in bases_str.split(",")]
    for b in bases:
        if b in _DJANGO_BASES or b.endswith(".Model"):
            return "django"
        if b in _SA_BASES or b == "db.Model":
            return "sqlalchemy"
        if b in _PYDANTIC_BASES:
            return "pydantic"
    return None


def _extract_python_entities(path: Path, content: str, repo_root: Path) -> list[DomainEntity]:
    """Extract domain entities from a single Python file."""
    entities: list[DomainEntity] = []

    for cls_match in _PY_CLASS_RE.finditer(content):
        class_name = cls_match.group(1)
        bases_str = cls_match.group(2)
        framework = _is_model_class(bases_str)
        if framework is None:
            continue

        # Determine the body of the class (up to next top-level def/class or EOF)
        start = cls_match.end()
        next_top = re.search(r"^\S", content[start:], re.MULTILINE)
        body = content[start : start + next_top.start()] if next_top else content[start:]

        # Extract attributes
        attributes: list[str] = []
        if framework == "pydantic":
            for fm in _PYDANTIC_FIELD_RE.finditer(body):
                attr = fm.group(1)
                if not attr.startswith("_") and attr != "model_config":
                    attributes.append(attr)
        else:
            for fm in _PY_FIELD_RE.finditer(body):
                attr = fm.group(1)
                if not attr.startswith("_") and attr != "class":
                    attributes.append(attr)

        # Extract relationships
        relationships: list[EntityRelationship] = []

        # Django FK / M2M / O2O
        for fk_match in _DJANGO_FK_RE.finditer(body):
            _field_name, rel_type_str, target = fk_match.groups()
            rel_type = _PYTHON_REL_MAP.get(rel_type_str, "references")
            relationships.append(
                EntityRelationship(
                    target_entity=target,
                    relationship_type=rel_type,  # type: ignore[arg-type]
                )
            )

        # SQLAlchemy relationship()
        for sa_match in _SA_REL_RE.finditer(body):
            _field_name, target = sa_match.groups()
            relationships.append(
                EntityRelationship(
                    target_entity=target,
                    relationship_type="has_many",
                )
            )

        # SQLAlchemy ForeignKey in Column
        for sa_fk in _SA_FK_RE.finditer(body):
            _field_name, target_table = sa_fk.groups()
            relationships.append(
                EntityRelationship(
                    target_entity=target_table,
                    relationship_type="belongs_to",
                )
            )

        # Compute relative module path for bounded_context hint
        try:
            rel = path.relative_to(repo_root)
            parts = list(rel.parts)
            # Remove leading src/ if present
            if parts and parts[0] == "src":
                parts = parts[1:]
            context_hint = parts[0] if parts else None
        except ValueError:
            context_hint = None

        entities.append(
            DomainEntity(
                name=class_name,
                description=f"{framework.title()} model in {path.name}",
                attributes=attributes,
                relationships=relationships,
                bounded_context=context_hint,
            )
        )

    return entities


# ---------------------------------------------------------------------------
# Java / JPA entity extraction
# ---------------------------------------------------------------------------

# Java class with @Entity annotation
_JAVA_ENTITY_RE = re.compile(
    r"@Entity\b.*?public\s+(?:abstract\s+)?class\s+(\w+)",
    re.DOTALL,
)

# Java field:  private Type name;
_JAVA_FIELD_RE = re.compile(r"^\s+private\s+\S+\s+(\w+)\s*;", re.MULTILINE)

# Java relationship annotations:  @ManyToOne, @OneToMany(mappedBy=..., targetEntity=Foo.class)
_JAVA_REL_ANNOTATION_RE = re.compile(
    r"@(ManyToOne|OneToMany|OneToOne|ManyToMany)"
    r"(?:\s*\([^)]*\))?"
    r"\s+(?:private\s+)?(?:\w+(?:<(\w+)>)?)\s+(\w+)\s*;",
    re.MULTILINE,
)

# Simpler fallback: just annotation + next field type for generics
_JAVA_REL_SIMPLE_RE = re.compile(
    r"@(ManyToOne|OneToMany|OneToOne|ManyToMany)\b",
    re.MULTILINE,
)


def _extract_java_entities(path: Path, content: str, repo_root: Path) -> list[DomainEntity]:
    """Extract domain entities from a Java file with @Entity."""
    entities: list[DomainEntity] = []

    for entity_match in _JAVA_ENTITY_RE.finditer(content):
        class_name = entity_match.group(1)

        # Get the class body (up to the matching closing brace -- approximation)
        start = entity_match.end()
        # Find the class body approximately: from start to next top-level class or EOF
        next_class = re.search(
            r"^(?:@\w+\s+)*public\s+(?:abstract\s+)?class\s+", content[start:], re.MULTILINE
        )
        body = content[start : start + next_class.start()] if next_class else content[start:]

        # Extract fields
        attributes: list[str] = []
        for fm in _JAVA_FIELD_RE.finditer(body):
            attr = fm.group(1)
            attributes.append(attr)

        # Extract relationships
        relationships: list[EntityRelationship] = []
        for rel_match in _JAVA_REL_ANNOTATION_RE.finditer(body):
            annotation = rel_match.group(1)
            generic_type = rel_match.group(2)
            field_name = rel_match.group(3)

            rel_type = _JAVA_REL_MAP.get(annotation, "references")
            # Target: prefer generic type (e.g. List<Order> -> Order), else field name
            target = generic_type if generic_type else field_name.capitalize()

            relationships.append(
                EntityRelationship(
                    target_entity=target,
                    relationship_type=rel_type,  # type: ignore[arg-type]
                )
            )

        # If annotation regex missed some, use the simple count
        found_annotations = {m.group(1) for m in _JAVA_REL_SIMPLE_RE.finditer(body)}
        matched_annotations = {m.group(1) for m in _JAVA_REL_ANNOTATION_RE.finditer(body)}
        for ann in found_annotations - matched_annotations:
            rel_type = _JAVA_REL_MAP.get(ann, "references")
            relationships.append(
                EntityRelationship(
                    target_entity="Unknown",
                    relationship_type=rel_type,  # type: ignore[arg-type]
                )
            )

        # Bounded context hint from package structure
        try:
            rel = path.relative_to(repo_root)
            parts = list(rel.parts)
            # Look for src/main/java/<org>/<pkg> pattern
            if "java" in parts:
                java_idx = parts.index("java")
                pkg_parts = parts[java_idx + 1 :]
                # Use the first meaningful package segment after org
                context_hint = pkg_parts[0] if pkg_parts else None
            else:
                context_hint = parts[0] if parts else None
        except ValueError:
            context_hint = None

        entities.append(
            DomainEntity(
                name=class_name,
                description=f"JPA entity in {path.name}",
                attributes=attributes,
                relationships=relationships,
                bounded_context=context_hint,
            )
        )

    return entities


# ---------------------------------------------------------------------------
# File-walking and dispatching
# ---------------------------------------------------------------------------

_PYTHON_MODEL_FILENAMES = frozenset({"models.py", "model.py", "entities.py", "schemas.py"})


def _is_python_model_file(path: Path) -> bool:
    """Check whether a Python file is likely to contain model definitions."""
    if path.name in _PYTHON_MODEL_FILENAMES:
        return True
    # Also check any .py file that might contain BaseModel / models.Model
    return False


def _walk_source_files(repo_path: Path):
    """Yield source files, skipping hidden/build dirs."""
    for child in sorted(repo_path.iterdir()):
        if child.name in _SKIP_DIRS or child.name.startswith("."):
            continue
        if child.is_file():
            yield child
        elif child.is_dir():
            yield from _walk_source_files(child)


def infer_entities_from_models(repo_paths: list[Path]) -> list[DomainEntity]:
    """Scan repositories for ORM/model files and extract domain entities.

    Supports:
    - Django ``models.Model``
    - SQLAlchemy declarative models
    - Pydantic ``BaseModel`` subclasses
    - JPA ``@Entity`` annotated Java classes
    """
    all_entities: list[DomainEntity] = []

    for repo_path in repo_paths:
        for source_file in _walk_source_files(repo_path):
            content = None  # lazy read

            if source_file.suffix == ".py":
                # Check known model filenames first
                if _is_python_model_file(source_file):
                    content = _safe_read_text(source_file)
                    if content:
                        all_entities.extend(
                            _extract_python_entities(source_file, content, repo_path)
                        )
                else:
                    # Peek into the file for model base classes
                    content = _safe_read_text(source_file)
                    if content and (
                        "BaseModel" in content
                        or "models.Model" in content
                        or "DeclarativeBase" in content
                        or "db.Model" in content
                    ):
                        all_entities.extend(
                            _extract_python_entities(source_file, content, repo_path)
                        )

            elif source_file.suffix == ".java":
                content = _safe_read_text(source_file)
                if content and "@Entity" in content:
                    all_entities.extend(
                        _extract_java_entities(source_file, content, repo_path)
                    )

    # Deduplicate by name (keep first occurrence)
    seen: set[str] = set()
    unique: list[DomainEntity] = []
    for entity in all_entities:
        if entity.name not in seen:
            seen.add(entity.name)
            unique.append(entity)

    logger.info("Inferred %d domain entities from %d repos", len(unique), len(repo_paths))
    return unique


# ---------------------------------------------------------------------------
# Bounded context inference
# ---------------------------------------------------------------------------


def infer_bounded_contexts(
    entities: list[DomainEntity],
    components: list[Component],
) -> list[BoundedContext]:
    """Group entities into bounded contexts by package/module structure.

    Heuristic: entities sharing the same ``bounded_context`` hint (top-level
    package) belong to the same context.  Each context is mapped to components
    whose boundary path contains the context name.
    """
    if not entities:
        return []

    # Group entities by their bounded_context hint
    context_groups: dict[str, list[DomainEntity]] = {}
    for entity in entities:
        ctx_key = entity.bounded_context or "default"
        context_groups.setdefault(ctx_key, []).append(entity)

    contexts: list[BoundedContext] = []
    context_names = sorted(context_groups.keys())

    for ctx_name in context_names:
        ctx_entities = context_groups[ctx_name]
        entity_names = [e.name for e in ctx_entities]

        # Map to components by boundary path overlap
        matched_component_ids: list[str] = []
        for comp in components:
            for boundary in comp.boundaries:
                if ctx_name != "default" and ctx_name.lower() in boundary.path.lower():
                    matched_component_ids.append(comp.id)
                    break

        display_name = ctx_name.replace("_", " ").replace("-", " ").title()

        contexts.append(
            BoundedContext(
                name=display_name,
                description=f"Bounded context containing {len(entity_names)} entities",
                entities=entity_names,
                component_ids=matched_component_ids,
            )
        )

    # Infer upstream/downstream from entity relationships crossing contexts
    entity_to_ctx: dict[str, str] = {}
    for ctx in contexts:
        for ename in ctx.entities:
            entity_to_ctx[ename] = ctx.name

    for entity in entities:
        source_ctx = entity_to_ctx.get(entity.name)
        if not source_ctx:
            continue
        for rel in entity.relationships:
            target_ctx = entity_to_ctx.get(rel.target_entity)
            if target_ctx and target_ctx != source_ctx:
                # Source depends on target -> source is downstream of target
                src_bc = next((c for c in contexts if c.name == source_ctx), None)
                tgt_bc = next((c for c in contexts if c.name == target_ctx), None)
                if src_bc and tgt_bc:
                    if target_ctx not in src_bc.upstream_contexts:
                        src_bc.upstream_contexts.append(target_ctx)
                    if source_ctx not in tgt_bc.downstream_contexts:
                        tgt_bc.downstream_contexts.append(source_ctx)

    logger.info("Inferred %d bounded contexts", len(contexts))
    return contexts


# ---------------------------------------------------------------------------
# Mermaid context map
# ---------------------------------------------------------------------------


def generate_context_map_mermaid(contexts: list[BoundedContext]) -> str:
    """Generate a Mermaid flowchart showing bounded contexts and relationships."""
    if not contexts:
        return ""

    lines = ["flowchart LR"]

    # Node definitions
    name_to_id: dict[str, str] = {}
    for i, ctx in enumerate(contexts):
        node_id = f"ctx{i}"
        name_to_id[ctx.name] = node_id
        entity_count = len(ctx.entities)
        label = f"{ctx.name}<br/>({entity_count} entities)"
        lines.append(f'    {node_id}["{label}"]')

    # Edges from upstream -> downstream
    seen_edges: set[tuple[str, str]] = set()
    for ctx in contexts:
        for upstream_name in ctx.upstream_contexts:
            src_id = name_to_id.get(upstream_name)
            dst_id = name_to_id.get(ctx.name)
            if src_id and dst_id and (src_id, dst_id) not in seen_edges:
                seen_edges.add((src_id, dst_id))
                lines.append(f"    {src_id} --> {dst_id}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM-enhanced domain model
# ---------------------------------------------------------------------------

_LLM_DOMAIN_PROMPT = """\
You are a domain-driven design expert. Analyze the following structural domain \
model findings and enhance them.

For each entity, provide:
1. A concise one-sentence business description
2. Any missing relationships you can infer from naming conventions and field types
3. A suggested bounded context assignment if the current one seems wrong

For bounded contexts:
1. Suggest better names if the current names are too technical
2. Identify any contexts that should be merged or split
3. Describe upstream/downstream relationships between contexts

Return your response as JSON with this exact structure:
{
  "entities": [
    {
      "name": "EntityName",
      "description": "Business description",
      "additional_relationships": [
        {"target_entity": "OtherEntity", "relationship_type": "has_many",
         "description": "reason"}
      ],
      "suggested_context": "ContextName"
    }
  ],
  "context_refinements": [
    {
      "original_name": "OldName",
      "suggested_name": "BetterName",
      "description": "Business description of this context"
    }
  ]
}
"""


def enhance_domain_model_with_llm(
    entities: list[DomainEntity],
    contexts: list[BoundedContext],
    components: list[Component],
    llm: LlmClient,
) -> DomainModelSection:
    """Use an LLM to enhance the structurally-inferred domain model.

    Falls back gracefully by returning the structural model unchanged if the
    LLM call fails.
    """
    # Build evidence bundle
    evidence_items: list[dict] = []
    for entity in entities:
        evidence_items.append(
            {
                "type": "entity",
                "name": entity.name,
                "description": entity.description,
                "attributes": entity.attributes,
                "relationships": [
                    {"target": r.target_entity, "type": r.relationship_type}
                    for r in entity.relationships
                ],
                "bounded_context": entity.bounded_context,
            }
        )
    for ctx in contexts:
        evidence_items.append(
            {
                "type": "bounded_context",
                "name": ctx.name,
                "entities": ctx.entities,
                "upstream": ctx.upstream_contexts,
                "downstream": ctx.downstream_contexts,
            }
        )

    bundle = serialize_evidence_bundle(evidence_items, max_bytes=8192)

    try:
        response = llm.analyze(
            prompt=_LLM_DOMAIN_PROMPT,
            evidence_bundle=bundle,
            max_tokens=2048,
        )
    except LlmUnavailableError as exc:
        logger.warning("LLM unavailable; returning structural model only: %s", exc)
        mermaid = generate_context_map_mermaid(contexts)
        return DomainModelSection(
            entities=entities,
            bounded_contexts=contexts,
            context_map_mermaid=mermaid or None,
        )
    except Exception:
        logger.exception("LLM call failed; returning structural model only")
        mermaid = generate_context_map_mermaid(contexts)
        return DomainModelSection(
            entities=entities,
            bounded_contexts=contexts,
            context_map_mermaid=mermaid or None,
        )

    # Parse LLM response
    enhanced_entities = list(entities)
    enhanced_contexts = list(contexts)

    try:
        # Extract JSON from response (may be wrapped in markdown code fences)
        json_text = response
        fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", response, re.DOTALL)
        if fence_match:
            json_text = fence_match.group(1)
        data = json.loads(json_text)

        # Apply entity enhancements
        entity_by_name = {e.name: e for e in enhanced_entities}
        for enh in data.get("entities", []):
            ename = enh.get("name", "")
            if ename in entity_by_name:
                entity = entity_by_name[ename]
                # Update description if provided
                if enh.get("description"):
                    entity = entity.model_copy(update={"description": enh["description"]})
                # Add new relationships
                new_rels = list(entity.relationships)
                for rel_data in enh.get("additional_relationships", []):
                    target = rel_data.get("target_entity", "")
                    rel_type = rel_data.get("relationship_type", "references")
                    if target and rel_type in {
                        "has_many",
                        "has_one",
                        "belongs_to",
                        "many_to_many",
                        "references",
                        "extends",
                    }:
                        new_rels.append(
                            EntityRelationship(
                                target_entity=target,
                                relationship_type=rel_type,
                                description=rel_data.get("description", ""),
                            )
                        )
                entity = entity.model_copy(update={"relationships": new_rels})
                entity_by_name[ename] = entity

        enhanced_entities = list(entity_by_name.values())

        # Apply context refinements
        ctx_by_name = {c.name: c for c in enhanced_contexts}
        for ref in data.get("context_refinements", []):
            orig = ref.get("original_name", "")
            if orig in ctx_by_name:
                updates: dict = {}
                if ref.get("suggested_name"):
                    updates["name"] = ref["suggested_name"]
                if ref.get("description"):
                    updates["description"] = ref["description"]
                if updates:
                    ctx_by_name[orig] = ctx_by_name[orig].model_copy(update=updates)

        enhanced_contexts = list(ctx_by_name.values())

    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Could not parse LLM response; using structural model")

    mermaid = generate_context_map_mermaid(enhanced_contexts)
    return DomainModelSection(
        entities=enhanced_entities,
        bounded_contexts=enhanced_contexts,
        context_map_mermaid=mermaid or None,
    )


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def analyze_domain_model(
    repo_paths: list[Path],
    components: list[Component],
    llm: LlmClient | None = None,
) -> DomainModelSection | None:
    """Infer a domain model from repository source code.

    Returns ``None`` if no entities are found.

    1. Structural inference: scan for ORM/model classes.
    2. Bounded context grouping by package structure.
    3. (Optional) LLM enhancement for descriptions and missing relationships.
    """
    logger.info("Analyzing domain model across %d repos", len(repo_paths))

    entities = infer_entities_from_models(repo_paths)
    if not entities:
        logger.info("No domain entities found; skipping domain model")
        return None

    contexts = infer_bounded_contexts(entities, components)
    mermaid = generate_context_map_mermaid(contexts)

    # LLM enhancement
    if llm is not None and llm.available:
        return enhance_domain_model_with_llm(entities, contexts, components, llm)

    return DomainModelSection(
        entities=entities,
        bounded_contexts=contexts,
        context_map_mermaid=mermaid or None,
    )


__all__ = [
    "analyze_domain_model",
    "enhance_domain_model_with_llm",
    "generate_context_map_mermaid",
    "infer_bounded_contexts",
    "infer_entities_from_models",
]
