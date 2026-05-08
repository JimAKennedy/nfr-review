# Dependency License Inventory

**Generated:** 2026-05-08
**Project:** nfr-review v0.1.0
**License:** Apache-2.0

This is a point-in-time inventory of licenses for all direct dependencies declared
in `pyproject.toml`. Transitive (indirect) dependencies are not enumerated here.
Versions reflect what was installed at generation time and may differ from the
version constraints in `pyproject.toml`.

---

## Runtime Dependencies

These packages are listed under `[project.dependencies]` in `pyproject.toml`.

| Package | Version | License (SPDX) | Source URL |
|---------|---------|----------------|------------|
| click | 8.1.8 | BSD-3-Clause | https://github.com/pallets/click/ |
| pydantic | 2.13.3 | MIT | https://github.com/pydantic/pydantic |
| ruamel.yaml | 0.19.1 | MIT | https://sourceforge.net/p/ruamel-yaml/code/ci/default/tree/ |
| anthropic | 0.97.0 | MIT | https://github.com/anthropics/anthropic-sdk-python |
| tree-sitter | 0.23.2 | MIT | https://github.com/tree-sitter/py-tree-sitter |
| tree-sitter-language-pack | 0.9.1 | MIT OR Apache-2.0 | https://github.com/Goldziher/tree-sitter-language-pack |

All runtime dependencies use permissive licenses (MIT, BSD-3-Clause, or
Apache-2.0) that are compatible with the project's Apache-2.0 license.

---

## Development Dependencies

These packages are listed under `[project.optional-dependencies.dev]` in
`pyproject.toml`. They are not distributed with the project.

| Package | Version | License (SPDX) | Source URL |
|---------|---------|----------------|------------|
| pytest | 8.4.2 | MIT | https://github.com/pytest-dev/pytest |
| pytest-cov | not installed | MIT | https://github.com/pytest-dev/pytest-cov |
| ruff | 0.11.12 | MIT | https://github.com/astral-sh/ruff |

**Note:** pytest-cov was not installed in the current environment at inventory
time. Its license (MIT) is documented from its PyPI metadata.

---

## Tree-Sitter Grammar Licenses

The `tree-sitter-language-pack` package (v0.9.1) bundles pre-compiled grammar
binaries for 160+ programming languages as shared objects (`.abi3.so` files). The
package itself is dual-licensed under **MIT OR Apache-2.0** (SPDX expression).

### Package-level license

The package's `LICENSE` file contains two license grants:

1. **MIT License** -- Copyright 2024-2025 Na'aman Hirschfeld (the package author)
2. **Apache License 2.0** -- Copyright 2022 Grant Jenks (original
   `tree-sitter-languages` project that this package forked from)

### Bundled grammar parsers

Each upstream tree-sitter grammar repository carries its own license. The vast
majority of tree-sitter grammars use the **MIT** license. A small number use
**Apache-2.0** or are dual-licensed MIT/Apache-2.0. The compiled `.abi3.so`
binaries in the package do not embed separate license files.

The grammars used by nfr-review's AST collectors are:

| Grammar | Upstream Repository | License (SPDX) |
|---------|-------------------|----------------|
| java | https://github.com/tree-sitter/tree-sitter-java | MIT |
| python | https://github.com/tree-sitter/tree-sitter-python | MIT |
| go | https://github.com/tree-sitter/tree-sitter-go | MIT |
| c_sharp | https://github.com/tree-sitter/tree-sitter-c-sharp | MIT |
| javascript / typescript | https://github.com/tree-sitter/tree-sitter-javascript / tree-sitter-typescript | MIT |

All grammars consumed by this project use permissive licenses compatible with
Apache-2.0.

---

## How to Regenerate

To regenerate a machine-readable license report, install `pip-licenses` and run:

```bash
pip install pip-licenses
pip-licenses --format=markdown --with-urls --with-license-file --output-file=licenses-full.md
```

Alternatively, use `pip show <package>` for each dependency to inspect version and
license metadata manually, which is how this inventory was originally produced.

---

## Compatibility Summary

| License | Count | Compatible with Apache-2.0? |
|---------|-------|-----------------------------|
| MIT | 8 | Yes |
| BSD-3-Clause | 1 | Yes |
| Apache-2.0 | 1 (dual) | Yes |

No copyleft (GPL, LGPL, AGPL) or proprietary licenses are present in the direct
dependency tree. All licenses are permissive and compatible with the project's
Apache-2.0 license.
