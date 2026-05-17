"""Hygiene rules. Importing this package auto-registers them."""

from __future__ import annotations

import nfr_review.hygiene.rules.bld_build_system  # noqa: F401
import nfr_review.hygiene.rules.bld_entry_points  # noqa: F401
import nfr_review.hygiene.rules.bld_version_strategy  # noqa: F401
import nfr_review.hygiene.rules.ci_coverage_gate  # noqa: F401
import nfr_review.hygiene.rules.ci_has_ci  # noqa: F401
import nfr_review.hygiene.rules.ci_has_lint  # noqa: F401
import nfr_review.hygiene.rules.ci_has_sast  # noqa: F401
import nfr_review.hygiene.rules.ci_has_tests  # noqa: F401
import nfr_review.hygiene.rules.ci_pin_actions  # noqa: F401
import nfr_review.hygiene.rules.com_changelog  # noqa: F401
import nfr_review.hygiene.rules.com_code_of_conduct  # noqa: F401
import nfr_review.hygiene.rules.com_codeowners  # noqa: F401
import nfr_review.hygiene.rules.com_contributing  # noqa: F401
import nfr_review.hygiene.rules.com_readme  # noqa: F401
import nfr_review.hygiene.rules.com_security  # noqa: F401
import nfr_review.hygiene.rules.doc_api_docs  # noqa: F401
import nfr_review.hygiene.rules.doc_docs_exist  # noqa: F401
import nfr_review.hygiene.rules.doc_pkg_metadata  # noqa: F401
import nfr_review.hygiene.rules.lic_copyleft  # noqa: F401
import nfr_review.hygiene.rules.lic_headers  # noqa: F401
import nfr_review.hygiene.rules.lic_notice  # noqa: F401
import nfr_review.hygiene.rules.lic_spdx  # noqa: F401
import nfr_review.hygiene.rules.prv_internal_refs  # noqa: F401
import nfr_review.hygiene.rules.prv_pii_patterns  # noqa: F401
import nfr_review.hygiene.rules.prv_tracking_ids  # noqa: F401
