---
name: structurizr-dsl
description: Structurizr DSL grammar reference — workspace structure, C4 element types, relationship syntax, view definitions, styling, identifier rules, implied relationships, and common gotchas. Use when generating, parsing, or validating Structurizr DSL files, building architecture models from scan results, or implementing drift detection against a DSL baseline.
---

# Structurizr DSL

Reference for the Structurizr DSL used by nfr-review to emit architecture models from static/dynamic analysis and detect architectural drift against a curated baseline.

Our use cases:
1. **Emit** — generate valid `.dsl` files from scan results (arch command output)
2. **Parse** — read a curated `.dsl` baseline back into our model
3. **Diff** — compare scan-derived workspace against parsed baseline for drift

## Workspace Structure

Every DSL file has exactly one workspace at the top level:

```dsl
workspace [name] [description] {
    !identifiers hierarchical     # optional, recommended for multi-system models
    !impliedRelationships true    # default

    model { ... }
    views { ... }
    configuration { ... }        # optional
}
```

**Critical syntax rules:**
- Opening `{` must be on the same line as the keyword (never alone on next line)
- Closing `}` must be alone on its own line
- No forward references — elements must be defined before use
- `this` refers to the currently-scoped element (use for self-references)
- Keywords are case-insensitive (`softwareSystem` == `softwaresystem`)
- Line continuation: `\` as last character
- Comments: `/* ... */`, `// ...`, `# ...`

## Element Types

### Core C4 Hierarchy

```
person
softwareSystem
  └─ container
       └─ component
```

### Syntax (all element types)

```dsl
[id = ]person <name> [description] [tags] { ... }
[id = ]softwareSystem <name> [description] [tags] { ... }
[id = ]container <name> [description] [technology] [tags] { ... }
[id = ]component <name> [description] [technology] [tags] { ... }
```

Default tags added automatically: `Element` + type name (e.g., `Element`, `Software System`).

### Deployment Elements

```dsl
deploymentEnvironment <name> {
    deploymentNode <name> [description] [technology] [tags] [instances] {
        # instances: integer or range "1..N"
        # can nest deploymentNode, infrastructureNode, softwareSystemInstance, containerInstance
        softwareSystemInstance <systemId> [deploymentGroups] [tags] { ... }
        containerInstance <containerId> [deploymentGroups] [tags] { ... }
        infrastructureNode <name> [description] [technology] [tags] { ... }
    }
}
```

### Common Properties Block (any element)

```dsl
tags "Tag1" "Tag2"           # additive, never replaces defaults
description "..."
technology "..."             # containers and components only
url https://...
properties {
    key value
    "key with spaces" "value with spaces"
}
```

## Relationships

### Explicit (model scope, both elements already defined)

```dsl
sourceId -> destId [description] [technology] [tags]
```

### Implicit (inside element block, source = enclosing element)

```dsl
-> destId [description] [technology] [tags]
```

### With Properties

```dsl
sourceId -> destId "Description" {
    tags "Async"
    technology "Kafka"
    properties { protocol "AMQP" }
}
```

### Removal

```dsl
sourceId -/> destId
```

### Permitted Connections

| Source | Valid Destinations |
|---|---|
| Person | Person, SoftwareSystem, Container, Component |
| SoftwareSystem | Person, SoftwareSystem, Container, Component |
| Container | Person, SoftwareSystem, Container, Component |
| Component | Person, SoftwareSystem, Container, Component |
| DeploymentNode | DeploymentNode |
| InfrastructureNode | DeploymentNode, InfrastructureNode, Instances |
| Instances | InfrastructureNode |

Default tag on all relationships: `Relationship`.

**Same-pair constraint:** two relationships between the same source→dest must have different descriptions.

## Identifiers

- Valid chars: `a-zA-Z_0-9` (no hyphens)
- Optional — only needed when referencing the element later
- Assignment: `id = softwareSystem "Name"`
- `this` = currently scoped element

### Flat Mode (default)

All identifiers globally scoped. Duplicates fail.

### Hierarchical Mode

```dsl
!identifiers hierarchical
```

Dot-notation paths: `system1.api`, `system2.api` — same local name, different parents.

**Gotcha:** Groups are always globally scoped regardless of `!identifiers hierarchical`.

## Views

All views live inside `views { }`. Always specify explicit keys — auto-generated keys are unstable.

### View Types

```dsl
systemLandscape [key] [description] { ... }
systemContext <systemId> [key] [description] { ... }
container <systemId> [key] [description] { ... }
component <containerId> [key] [description] { ... }
deployment <*|systemId> <envName> [key] [description] { ... }
dynamic <*|systemId|containerId> [key] [description] { ... }
filtered <baseKey> <include|exclude> <tags> [key] [description]
custom [key] [title] [description] { ... }
```

### View Content

```dsl
include *                              # all default elements for view type
include <id> [id...]                   # specific elements
include "element.tag==Tag1"            # expression
include "->systemA->"                  # element + all relationships
exclude <id>
exclude "element.tag==Internal"
autoLayout [tb|bt|lr|rl] [rankSep] [nodeSep]
title "Override"
default                                # mark as default view
```

### Dynamic View Sequences

```dsl
dynamic crm "flow-key" "Checkout" {
    customer -> crm.frontend "Opens page"
    crm.frontend -> crm.api "POST /orders"
    {
        { crm.api -> crm.db "Insert" }
        { crm.api -> notify.worker "Event" }
    }
    autoLayout lr
}
```

### Filtered Views

```dsl
filtered "landscape" include "Element,Relationship" "landscape-all"
filtered "landscape" exclude "Internal" "landscape-external"
```

**Gotcha:** creating any filtered view on a base view hides the base. Add a catch-all to keep it visible.

## Styles

Inside `views { }`:

```dsl
styles {
    element "Tag" {
        shape <Box|RoundedBox|Circle|Ellipse|Hexagon|Diamond|Cylinder|Pipe|
               Person|Robot|Folder|WebBrowser|MobileDevicePortrait|Component>
        background #1168bd
        color #ffffff
        stroke #0b4884
        strokeWidth 2
        border <solid|dashed|dotted>
        fontSize 14
        opacity 100
        icon <file|url>
        metadata <true|false>
        description <true|false>
    }
    relationship "Tag" {
        thickness 2
        color #707070
        style <solid|dashed|dotted>
        routing <Direct|Orthogonal|Curved>
        fontSize 12
        position 50
        opacity 100
    }
}
```

Built-in tags for broad targeting: `"Element"` (all elements), `"Person"`, `"Software System"`, `"Container"`, `"Component"`, `"Relationship"` (all relationships).

Group styling: `element "Group"` for all groups, `element "Group:Name"` for specific.

### Themes

```dsl
theme default
themes <url> [url...]
```

## Groups

```dsl
group "Domain Name" {
    svc = softwareSystem "Service"
}
```

Nested groups require the separator property:

```dsl
model {
    properties {
        "structurizr.groupSeparator" "/"
    }
    group "Company/Department" { ... }
}
```

## Implied Relationships

When component A → container B exists, Structurizr auto-creates system-level implied relationships.

```dsl
!impliedRelationships true     # default: create unless ANY relationship exists between pair
!impliedRelationships false    # disable; define all levels explicitly
```

Default strategy skips implied creation if *any* relationship already exists between the parent pair, even with a different description.

## Constants and Variables

Defined outside or at top of workspace:

```dsl
!const ORG "Acme Corp"
!var ENV "Production"

workspace "${ORG} - ${ENV}" { ... }
```

`${NAME}` substitution works anywhere. Undefined variables are silently skipped.

## Include and Documentation

```dsl
!include path/to/fragment.dsl     # inline, relative to parent file
!include subdir                    # all .dsl files in directory
!docs docs/architecture            # attach markdown docs to element
!adrs docs/adr adrtools            # attach ADRs (adrtools|madr|log4brains)
```

`!include` is sandboxed — no `../` traversal.

## String Quoting Rules

- Quotes optional when value has no whitespace: `tags Database`
- Quotes required for spaces: `tags "My Tag"`
- Double quotes only (no single quotes)
- `""` as placeholder to skip optional positional args:
  ```dsl
  container "Name" "" "Java" "Tag1"
  #          name  desc tech  tags
  ```
- Hex colors don't need quotes: `background #1168bd`

## Archetypes

Reusable element/relationship templates:

```dsl
archetypes {
    webApp = container {
        technology "React"
        tags "Web"
    }
    asyncLink = -> {
        tags "Async"
        technology "Kafka"
    }
}
model {
    s = softwareSystem "Sys" {
        fe = webApp "Frontend"         # inherits React + Web tag
    }
    fe --asyncLink-> worker "Events"   # inherits Async tag + Kafka tech
}
```

## Expressions (for view include/exclude)

```dsl
"element.type==Container"
"element.tag==Database"
"element.tag!=Internal"
"element.parent==systemId"
"element.technology==Java"
"element.group==GroupName"
"element.properties[owner]==teamA"
"relationship.tag==Async"
"*->*"                    # all relationships
"systemA->*"              # outbound from systemA
"->systemB"               # systemB + inbound
"element.tag==A && element.type==Container"
"element.tag==A || element.tag==B"
```

## Gotchas for Code Generation

1. **No forward references.** Emit elements before relationships that reference them. Use topological sort.
2. **Opening `{` same line.** Never emit `softwareSystem "Name"\n{`.
3. **View keys must be explicit.** Auto-generated keys change between renders, breaking layouts.
4. **`""` placeholders.** When emitting `container "X" "" "Java"`, the empty string skips description.
5. **Filtered views hide base.** Always emit a catch-all filtered view to keep the base visible.
6. **Group identifiers always global.** Even with `!identifiers hierarchical`.
7. **Same-pair unique descriptions.** Two relationships A→B must have different description strings.
8. **Tag additivity.** `tags "X"` adds to defaults — never emit code that assumes tags replace.
9. **Deployment view env name is string, not identifier.** Must exactly match `deploymentEnvironment` name.
10. **`!impliedRelationships` default skips if ANY exists.** Don't emit redundant parent-level relationships — they'll prevent implied ones with different descriptions.

## Validation Checklist

When generating or parsing DSL, verify:

- [ ] Every `{` is on the same line as its keyword
- [ ] Every `}` is alone on its line
- [ ] All referenced identifiers are defined before use
- [ ] View keys are explicit strings, not auto-generated
- [ ] No two relationships between same pair share a description
- [ ] Identifier names use only `a-zA-Z_0-9`
- [ ] Containers are inside softwareSystem blocks
- [ ] Components are inside container blocks
- [ ] Deployment instances reference valid element identifiers
- [ ] `!identifiers hierarchical` is set when multiple systems share local names

## nfr-review Integration Points

### Emitter (scan → DSL)

Maps our analysis to C4:
- Repositories / deployment units → `softwareSystem`
- Build modules / service processes → `container`
- Packages / significant classes → `component`
- OTel trace edges → relationships with technology from span attributes
- Static import/call edges → relationships with technology from language

Heuristics for collapsing (don't emit every class):
- Group by package into components; only promote to container if separate deployment unit
- Filter internal-only relationships below a threshold
- Use `tags` to mark inferred vs. confirmed elements

### Parser (DSL → model)

Recursive-descent for the core subset we emit (no need to support `!script`, archetypes, or extends initially). Parse into our Pydantic workspace model, preserving identifiers and hierarchy.

### Drift Detector (scan workspace vs. parsed baseline)

Compare element sets and relationship sets:
- **New in scan, absent in baseline** → unplanned coupling / undocumented service
- **In baseline, absent in scan** → dead architecture / removed dependency
- **Relationship description mismatch** → technology change
- **New tags** → role change

Output as design-change findings with severity based on scope of drift.
