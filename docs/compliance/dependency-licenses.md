# Dependency License Inventory

**Generated:** 2026-05-10
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
| tree-sitter | 0.25.2 | MIT | https://github.com/tree-sitter/py-tree-sitter |
| tree-sitter-java | 0.23.5 | MIT | https://github.com/tree-sitter/tree-sitter-java |
| tree-sitter-python | 0.25.0 | MIT | https://github.com/tree-sitter/tree-sitter-python |
| tree-sitter-go | 0.25.0 | MIT | https://github.com/tree-sitter/tree-sitter-go |
| tree-sitter-hcl | 1.2.0 | Apache-2.0 | https://github.com/tree-sitter-grammars/tree-sitter-hcl |
| tree-sitter-dockerfile | 0.2.0 | MIT | https://github.com/camdencheek/tree-sitter-dockerfile |
| tree-sitter-c-sharp | 0.23.5 | MIT | https://github.com/tree-sitter/tree-sitter-c-sharp |
| tree-sitter-typescript | 0.23.2 | MIT | https://github.com/tree-sitter/tree-sitter-typescript |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| resolvelib | 1.2.1 | ISC | https://github.com/sarugaku/resolvelib |

All runtime dependencies use permissive licenses (MIT, BSD-3-Clause, Apache-2.0,
ISC, and BSD-2-Clause) that are compatible with the project's Apache-2.0 license.

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

Individual tree-sitter grammar packages are used instead of a bundled language
pack. Each package provides pre-compiled parser binaries for a single language.

All grammar packages consumed by this project use permissive licenses (MIT or
Apache-2.0) compatible with the project's Apache-2.0 license. See the Runtime
Dependencies table above for specific versions and source URLs.

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
| MIT | 13 | Yes |
| BSD-3-Clause | 1 | Yes |
| Apache-2.0 | 1 | Yes |
| Apache-2.0 OR BSD-2-Clause | 1 | Yes |
| ISC | 1 | Yes |

No copyleft (GPL, LGPL, AGPL) or proprietary licenses are present in the direct
dependency tree. All licenses are permissive and compatible with the project's
Apache-2.0 license.
