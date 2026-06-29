# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Lint the documentation site for accuracy drift.

Checks:
  1. rules.json entry count matches the rule registry
  2. CodeSnippet region markers referenced in .mdx files exist in source
  3. Compliance rule count in compliance_mapping matches the doc site

Exit non-zero if any check fails.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
DOCS_DIR = SITE_DIR / "src" / "content" / "docs"
RULES_JSON = SITE_DIR / "src" / "data" / "rules.json"

failures: list[str] = []


def check_rules_json_count() -> None:
    import nfr_review.rules  # noqa: F401 — triggers registration
    from nfr_review.registry import rule_registry

    json_count = len(json.loads(RULES_JSON.read_text()))
    registry_count = len(rule_registry)

    if json_count != registry_count:
        failures.append(
            f"rules.json has {json_count} entries but registry has {registry_count}"
        )
    else:
        print(f"  rules.json: {json_count} entries (matches registry)")


def check_code_snippet_regions() -> None:
    project_root = SRC_DIR.parent
    snippet_re = re.compile(r'<CodeSnippet\s+file="([^"]+)"\s+region="([^"]+)"')
    checked = 0

    for mdx in DOCS_DIR.rglob("*.mdx"):
        text = mdx.read_text()
        for match in snippet_re.finditer(text):
            file_rel, region = match.group(1), match.group(2)
            source_file = project_root / file_rel
            if not source_file.exists():
                failures.append(
                    f"{mdx.relative_to(project_root)}: CodeSnippet references "
                    f"missing file {file_rel}"
                )
                checked += 1
                continue

            content = source_file.read_text()
            ext = source_file.suffix
            prefix = "#" if ext in (".py", ".yaml", ".yml", ".toml", ".sh") else "//"
            start_marker = f"{prefix} region:{region}"
            end_marker = f"{prefix} endregion:{region}"

            if start_marker not in content or end_marker not in content:
                failures.append(
                    f"{mdx.relative_to(project_root)}: region '{region}' "
                    f"not found in {file_rel}"
                )
            checked += 1

    print(f"  CodeSnippet regions: {checked} checked")


def check_compliance_count() -> None:
    from nfr_review.compliance_mapping import FRAMEWORK_RULES

    actual = len(set().union(*FRAMEWORK_RULES.values()))

    compliance_mdx = DOCS_DIR / "reference" / "compliance.mdx"
    if not compliance_mdx.exists():
        failures.append("reference/compliance.mdx not found")
        return

    text = compliance_mdx.read_text()
    m = re.search(r"\*\*(\d+) rules\*\*", text)
    if not m:
        failures.append("compliance.mdx: could not find '**N rules**' pattern")
        return

    doc_count = int(m.group(1))
    if doc_count != actual:
        failures.append(
            f"compliance.mdx says {doc_count} rules but compliance_mapping has {actual}"
        )
    else:
        print(f"  Compliance rules: {doc_count} (matches mapping)")


def main() -> int:
    print("Linting documentation site accuracy...")
    check_rules_json_count()
    check_code_snippet_regions()
    check_compliance_count()

    if failures:
        print(f"\n{len(failures)} failure(s):")
        for f in failures:
            print(f"  FAIL: {f}")
        return 1

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
