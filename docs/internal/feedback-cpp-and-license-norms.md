# Feedback: C++ Project Support and License Norm Assumptions

**Date:** 2026-06-24
**Source project:** `../poly` (C++20 VST3 plugin, CMake build, GPL-3.0-only)
**Tool version:** nfr-review current main
**Config:** `nfr-review.yaml` with 14 skip rules required to reach clean scan

## Summary

Running nfr-review against a C++ CMake project exposed two systemic gaps:
the hygiene rules assume a Python/JVM/Node ecosystem, and the license rules
assume Apache-2.0 conventions. Both produce clusters of false positives that
require manual suppression via skip rules in `nfr-review.yaml`.

---

## 1. C++ / CMake Blind Spots

### HYG-BLD-002 — Version not in manifest

The rule checks `pyproject.toml`, `package.json`, `pom.xml`, `build.gradle`,
`Cargo.toml`, and `.csproj` for a version declaration. It does not recognise
`CMakeLists.txt`, which declares version via `project(poly VERSION 0.8.0)`.

**Recommendation:** Add a CMake manifest collector that parses `project(... VERSION ...)`
from the root `CMakeLists.txt`.

### HYG-BLD-003 — Missing console_scripts / gui_scripts

This rule checks for Python entry-point declarations. It is not applicable to
C/C++ projects, which produce binaries via CMake `add_executable()` or library
targets via `add_library()`.

**Recommendation:** Auto-skip when no Python manifest is detected, or add a
tech-filter (`tech: python`) so it only fires when Python evidence is present.

### HYG-DOC-001 — No manifest detected

The scanner does not recognise `CMakeLists.txt` as a project manifest. A C++
project with a well-structured CMake build system triggers "no manifest found."

**Recommendation:** Register `CMakeLists.txt` (at root) as a valid manifest for
the document/manifest collector.

### HYG-CI-003 — No lint/format step in CI

The rule searches for ESLint, Prettier, Biome, Ruff, Black, and similar
JS/Python tools. It does not detect:

- `clang-format` (C/C++ formatter)
- `clang-tidy` (C/C++ linter/static analyser)
- `pre-commit run --all-files` when pre-commit hooks include these tools
- `cppcheck`, `cpplint`, or `include-what-you-use`

**Recommendation:** Extend the CI lint detector patterns to include C/C++ tooling.
A quick win: match `clang-format` and `clang-tidy` in workflow files.

### ci-security-scan-missing — No SAST/DAST detected

The rule looks for CodeQL, Snyk, Trivy, Dependabot, and similar scanners. It
does not recognise the C++ equivalent:

- `clang-tidy` with security-relevant checks (`bugprone-*`, `cert-*`, `cppcoreguidelines-*`)
- AddressSanitizer / ThreadSanitizer / UBSan CI jobs
- `gitleaks` for secrets scanning (was detected, but only after adding a
  `.gitleaks.toml` config file)

**Recommendation:** Recognise sanitizer CI jobs (`-fsanitize=address`, ASAN/TSAN/UBSAN)
and clang-tidy as valid SAST evidence for C/C++ projects.

---

## 2. License Norm Assumptions (Apache-Centric)

### HYG-LIC-001 — Copyleft compatibility warning

This rule flags GPL-licensed projects with a compatibility warning. For a
project that has *deliberately chosen* GPL-3.0-only, this is a false positive —
the user already understands the copyleft implications.

The rule makes sense as an *informational* note for projects that haven't
explicitly chosen their license. But when a `LICENSE` file containing the
GPL-3.0 full text is present, the choice is intentional.

**Recommendation:** Downgrade to `green/info` when a full GPL license text is
present (not just an SPDX identifier in a manifest). Or add a license-family
config option so projects can declare their intended license family.

### HYG-LIC-002 — Missing NOTICE file

The `NOTICE` file is an Apache License 2.0 convention (Section 4d requires
attribution notices to be delivered in a NOTICE file). GPL-3.0 has no such
requirement — it requires copyright preservation in source files and the
license text itself.

Flagging a GPL project for missing NOTICE is a false positive.

**Recommendation:** Only fire this rule when the detected license is Apache-2.0
(or a permissive license that uses NOTICE conventions, like some BSD variants).

### HYG-LIC-003 — Missing license headers in source files

While license headers are good practice, this rule fires on generated files,
config files, and framework boilerplate (e.g. Astro's `content.config.ts`)
where headers add noise without legal value. GPL-3.0 recommends headers but
does not require them in every file — the LICENSE file at the project root is
sufficient for copyright assertion.

**Recommendation:** Add a file-type filter that skips generated/config files
(build output, `.config.ts`, lockfiles, etc.), or allow a path-based exclusion
list within the rule itself (separate from the global `exclude_paths`).

---

## 3. Other C++-Unfriendly Rules

### cpp-dormant-classes

Flags VST3/VSTGUI factory methods that use `new` with ownership transfer to
the framework. The scanner sees unused-looking classes because they are
instantiated via framework callbacks (`createView()`, `createCustomView()`),
not direct construction.

**Recommendation:** Recognise the `// ownership-transfer` annotation pattern
(already a convention in the VST3 community) as a suppression signal.

### structure-god-node / structure-weak-boundary

Google Test `TEST()` / `TEST_F()` macros register as coupling hotspots, and
the engine/plugin boundary (which is intentional and CI-enforced) triggers
weak-boundary findings.

These are design-by-intent patterns that the scanner cannot distinguish from
actual structural problems.

**Recommendation:** Consider a `tech: gtest` filter for the god-node rule,
and allow `nfr-review.yaml` to declare intentional boundaries that suppress
weak-boundary findings for specific directory pairs.

---

## 4. Proposed Improvements (Priority Order)

| Priority | Item | Impact |
|----------|------|--------|
| P1 | CMake manifest detection (HYG-BLD-002, HYG-DOC-001) | Eliminates 2 false positives for all C/C++ projects |
| P1 | License-family-aware rules (HYG-LIC-001, HYG-LIC-002) | Eliminates 2 false positives for all GPL projects |
| P2 | C++ lint/SAST detection (HYG-CI-003, ci-security-scan-missing) | Eliminates 2 false positives, better C++ coverage |
| P2 | Auto-skip Python-specific rules when no Python manifest present | Eliminates HYG-BLD-003 without manual config |
| P3 | License header file-type filtering (HYG-LIC-003) | Reduces noise on generated/config files |
| P3 | Ownership-transfer annotation support (cpp-dormant-classes) | Better VST3/framework interop |

---

## Appendix: Skip Rules Required for Clean Scan

The following 14 rules were skipped in `poly/nfr-review.yaml` to achieve a
100/100 score. Each has a rationale comment in the config file. Of these,
**9 are attributable to the C++/GPL gaps described above** — a purpose-built
C++ profile would eliminate most of them without per-project configuration.

```yaml
# C++ ecosystem gaps (would be fixed by recommendations above)
- HYG-BLD-002    # version in CMake, not Python/JVM manifest
- HYG-BLD-003    # Python entry points, not applicable
- HYG-DOC-001    # CMake not recognised as manifest
- HYG-CI-003     # clang-format/clang-tidy not detected
- HYG-LIC-001    # GPL is intentional, not a compatibility issue
- HYG-LIC-002    # NOTICE is Apache convention, not GPL
- HYG-LIC-003    # headers on generated files add noise
- ci-security-scan-missing   # sanitizers + clang-tidy not detected
- cpp-dormant-classes        # framework ownership transfer pattern

# Genuinely not applicable (correct to skip regardless of C++ support)
- structure-god-node         # GTest macro coupling
- cmake-minimum-version     # inherited from root CMakeLists
- cmake-build-config        # inherited from root CMakeLists
- structure-weak-boundary   # intentional engine/plugin boundary
- sample-readme-exists      # not a sample/demo project
- otel-test-observability   # GTest, not OTel-traced tests
- adr-gap                   # decisions in IMPLEMENTATION_PLAN.md + .gsd/
- ci-test-stage-missing     # non-build workflows misidentified
- PATCH-ROLL-002            # no deployable service to roll back
```
