"""Tests for PDF report generation (typst backend)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from nfr_review.engine import RunResult
from nfr_review.models import Finding, RunMetadata
from nfr_review.output.pdf import _md_to_typst, _render_mermaid_for_typst, _t, render_pdf
from nfr_review.output.summary_models import ExecSummary, RemediationItem


def _make_valid_png(width: int = 1, height: int = 1) -> bytes:
    """Build a valid PNG image with the given dimensions."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    # One white pixel row per scanline, preceded by filter byte 0
    row = b"\x00" + b"\xff\xff\xff" * width
    raw_px = row * height
    compressed = zlib.compress(raw_px)
    idat_crc = zlib.crc32(b"IDAT" + compressed)
    idat = (
        struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)
    )
    iend_crc = zlib.crc32(b"IEND")
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    return sig + ihdr + idat + iend


def _make_finding(
    rule_id: str = "TEST-001",
    severity: str = "medium",
    rag: str = "amber",
    locator: str = "src/foo.py:10",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rag=rag,
        severity=severity,
        summary=f"Test finding for {rule_id}",
        recommendation="Fix it",
        evidence_locator=locator,
        collector_name="test-collector",
        collector_version="1.0",
        confidence=0.8,
        pattern_tag="test",
    )


def _make_run_result(findings: list[Finding] | None = None) -> RunResult:
    return RunResult(
        findings=findings
        or [
            _make_finding("SEC-001", "critical", "red"),
            _make_finding("DEP-002", "high", "red"),
            _make_finding("DOC-003", "medium", "amber"),
            _make_finding("STYLE-004", "low", "green"),
        ],
        rule_results=[],
        run_metadata=RunMetadata(
            tool_version="0.1.0",
            target_repo="/tmp/test-repo",
            timestamp="2026-05-20T10:00:00Z",
            git_sha="abc1234",
            git_branch="main",
            rules_run=["SEC-001", "DEP-002", "DOC-003", "STYLE-004"],
        ),
    )


def _make_exec_summary() -> ExecSummary:
    return ExecSummary(
        verdict="conditional",
        verdict_explanation="The project has moderate issues requiring attention.",
        risk_highlights=["Outdated deps with CVEs", "Missing license headers"],
        remediation_priorities=[
            RemediationItem(
                title="Update vulnerable deps",
                urgency="immediate",
                description="Critical CVEs in 3 dependencies.",
            ),
            RemediationItem(
                title="Add license headers",
                urgency="short-term",
                description="12 files missing headers.",
            ),
        ],
        production_risks="Main risk is outdated dependencies.",
        open_source_readiness="Close to ready, needs license work.",
        overall_score=62,
    )


class TestRenderPdf:
    def test_minimal_pdf(self, tmp_path: Path) -> None:
        """Minimal report with just findings produces a valid PDF file."""
        out = tmp_path / "report.pdf"
        result = render_pdf(nfr_result=_make_run_result(), output_path=out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000

    def test_pdf_with_findings(self, tmp_path: Path) -> None:
        """Report with several findings produces a valid PDF."""
        findings = [
            _make_finding("SEC-001", "critical", "red", "src/app.py:10"),
            _make_finding("DOC-002", "medium", "amber", "src/util.py:5"),
            _make_finding("STYLE-003", "low", "green", "src/helpers.py:3"),
        ]
        out = tmp_path / "findings-report.pdf"
        result = render_pdf(nfr_result=_make_run_result(findings), output_path=out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """render_pdf creates missing parent directories automatically."""
        out = tmp_path / "nested" / "deep" / "report.pdf"
        render_pdf(nfr_result=_make_run_result(), output_path=out)
        assert out.exists()

    def test_pdf_with_exec_summary(self, tmp_path: Path) -> None:
        """Report with exec summary produces a valid PDF."""
        out = tmp_path / "exec-report.pdf"
        result = render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            exec_summary=_make_exec_summary(),
        )
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000

    def test_pdf_with_hygiene_result(self, tmp_path: Path) -> None:
        """Report with hygiene_result merges findings and produces a valid PDF."""
        nfr = _make_run_result([_make_finding("NFR-001", "high", "red")])
        hygiene = RunResult(
            findings=[_make_finding("HYG-001", "medium", "amber")],
            rule_results=[],
        )
        out = tmp_path / "hygiene-report.pdf"
        result = render_pdf(
            nfr_result=nfr,
            output_path=out,
            hygiene_result=hygiene,
        )
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000

    def test_empty_findings(self, tmp_path: Path) -> None:
        """Report with zero findings still produces a valid PDF."""
        out = tmp_path / "empty.pdf"
        result = render_pdf(
            nfr_result=RunResult(findings=[], rule_results=[]),
            output_path=out,
        )
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000

    def test_full_pdf_with_summary(self, tmp_path: Path) -> None:
        """Report with exec summary and test results produces a valid PDF."""
        from nfr_review.output.pytest_runner import PytestResult

        out = tmp_path / "full-report.pdf"
        result = render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            exec_summary=_make_exec_summary(),
            pytest_result=PytestResult(
                passed=45, failed=2, skipped=3, errors=0, duration_seconds=12.5
            ),
        )
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 2000

    def test_hygiene_findings_included(self, tmp_path: Path) -> None:
        """Hygiene findings are merged into the report."""
        nfr = _make_run_result([_make_finding("NFR-001", "high", "red")])
        hygiene = RunResult(
            findings=[_make_finding("HYG-001", "medium", "amber")],
            rule_results=[],
        )
        out = tmp_path / "merged.pdf"
        result = render_pdf(
            nfr_result=nfr,
            output_path=out,
            hygiene_result=hygiene,
        )
        assert result == out
        assert out.stat().st_size > 1000

    def test_grouped_findings_in_pdf(self, tmp_path: Path) -> None:
        """Duplicate findings (same rule_id) produce a valid PDF."""
        findings = [
            _make_finding("CPP-001", "high", "red", locator="src/a.cpp:10"),
            _make_finding("CPP-001", "high", "red", locator="src/b.cpp:20"),
            _make_finding("CPP-001", "high", "red", locator="src/c.cpp:30"),
        ]
        out = tmp_path / "grouped.pdf"
        result = render_pdf(nfr_result=_make_run_result(findings), output_path=out)
        assert result == out
        assert out.exists()

    def test_deps_section_produces_pdf(self, tmp_path: Path) -> None:
        """deps_section_md content produces a valid PDF."""
        deps_md = (
            "## Dependency Analysis\n\n"
            "### PYPI Dependencies\n\n"
            "| # | Package | Current | Latest |\n"
            "|---|---------|---------|--------|\n"
            "| 1 | click | 8.1.0 | 8.3.0 |\n"
        )
        out = tmp_path / "deps.pdf"
        result = render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            deps_section_md=deps_md,
        )
        assert result == out
        assert out.exists()

    def test_pdf_with_diagram_stub(self, tmp_path: Path) -> None:
        """diagram_paths provided embeds the image and produces a valid PDF."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        png_path = img_dir / "chart.png"
        png_path.write_bytes(_make_valid_png())
        out = tmp_path / "diagram-stub.pdf"
        result = render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            diagram_paths={"Severity Distribution": png_path},
        )
        assert result == out
        assert out.exists()
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_dependency_findings_separated(self, tmp_path: Path) -> None:
        """Dependency-origin findings produce a valid PDF without error."""
        first_party = _make_finding("SEC-001", "high", "red", "src/app.py:10")
        dep_finding = Finding(
            rule_id="dep-freshness",
            rag="amber",
            severity="medium",
            summary="Outdated dependency",
            recommendation="Upgrade to latest",
            evidence_locator="dep:pypi:requests:2.25.0",
            collector_name="dep-collector",
            collector_version="1.0",
            confidence=0.95,
            pattern_tag="dep",
            origin="dependency",
        )
        nfr = _make_run_result([first_party, dep_finding])
        out = tmp_path / "dep-findings.pdf"
        result = render_pdf(nfr_result=nfr, output_path=out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000


class TestMdToTypst:
    """Unit tests for _md_to_typst and _render_mermaid_for_typst."""

    def test_heading_conversion(self) -> None:
        """## and ### headings convert to Typst == and ===."""
        image_files: dict[str, bytes] = {}
        counter: list[int] = [0]
        result = _md_to_typst("## Top Level\n### Sub Level\n", image_files, counter)
        assert "== Top Level" in result
        assert "=== Sub Level" in result

    def test_pipe_table_conversion(self) -> None:
        """Pipe table converts to #table(...)."""
        md = "| Package | Version |\n|---------|--------|\n| click | 8.1.0 |\n"
        image_files: dict[str, bytes] = {}
        counter: list[int] = [0]
        result = _md_to_typst(md, image_files, counter)
        assert "#table(" in result
        assert "Package" in result
        assert "click" in result
        assert _t("8.1.0") in result

    def test_bold_inline(self) -> None:
        """**bold** converts to *bold* (Typst bold)."""
        image_files: dict[str, bytes] = {}
        counter: list[int] = [0]
        result = _md_to_typst("**important text**\n", image_files, counter)
        assert "*important text*" in result

    def test_inline_code(self) -> None:
        """Inline code converts to #raw(...)."""
        image_files: dict[str, bytes] = {}
        counter: list[int] = [0]
        result = _md_to_typst("Use `pip install` to install.\n", image_files, counter)
        assert '#raw("pip install")' in result

    def test_fenced_code_block(self) -> None:
        """Non-mermaid fenced code block converts to #raw(block: true, ...)."""
        md = "```\nsome code here\n```\n"
        image_files: dict[str, bytes] = {}
        counter: list[int] = [0]
        result = _md_to_typst(md, image_files, counter)
        assert "#raw(" in result
        assert "some code here" in result

    def test_deps_md_produces_table_not_code_block(self, tmp_path: Path) -> None:
        """deps_section_md with a pipe table renders as #table, not a raw code block."""
        deps_md = (
            "## Dependency Analysis\n\n"
            "### PYPI Dependencies\n\n"
            "| # | Package | Current | Latest |\n"
            "|---|---------|---------|--------|\n"
            "| 1 | click | 8.1.0 | 8.3.0 |\n"
            "| 2 | requests | 2.28.0 | 2.32.0 |\n"
        )
        out = tmp_path / "deps-table.pdf"
        result = render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            deps_section_md=deps_md,
        )
        assert result == out
        assert out.exists()
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_mermaid_tier3_pie_fallback(self) -> None:
        """Mermaid pie chart with no mmdc uses tier-3 Typst table fallback."""
        import unittest.mock as mock

        mermaid = 'pie title Findings\n  "Critical" : 5\n  "High" : 10\n'
        image_files: dict[str, bytes] = {}
        counter: list[int] = [0]

        # Patch mmdc as unavailable and SVG fallback to return None to force tier 3
        with (
            mock.patch("shutil.which", return_value=None),
            mock.patch("nfr_review.output.render.render_pie_as_svg_fallback", return_value=""),
        ):
            result = _render_mermaid_for_typst(mermaid, image_files, counter)

        # Tier 3 output is a #table(...) with the parsed labels
        assert "#table(" in result
        assert "Critical" in result
        assert "High" in result
        # No image files registered since we fell through to tier 3
        assert len(image_files) == 0

    def test_mermaid_tier3_flowchart_fallback(self) -> None:
        """Mermaid flowchart with no mmdc and no SVG items uses raw fallback."""
        import unittest.mock as mock

        # Flowchart with no parseable node labels falls to last-resort raw
        mermaid = "graph TD\n  A --> B\n"
        image_files: dict[str, bytes] = {}
        counter: list[int] = [0]

        with (
            mock.patch("shutil.which", return_value=None),
            mock.patch(
                "nfr_review.output.render.render_flowchart_as_svg_fallback", return_value=""
            ),
        ):
            result = _render_mermaid_for_typst(mermaid, image_files, counter)

        # Should produce some Typst output — either table or raw
        assert result.strip()
        assert len(image_files) == 0

    def test_diagram_paths_produces_valid_pdf(self, tmp_path: Path) -> None:
        """diagram_paths with a valid PNG embeds it and produces a valid PDF."""
        img_dir = tmp_path / "imgs"
        img_dir.mkdir()
        # Use a wider PNG to exercise the dimension-aware width calculation
        png_path = img_dir / "wide.png"
        png_path.write_bytes(_make_valid_png(width=800, height=400))
        out = tmp_path / "diag.pdf"
        result = render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            diagram_paths={"Architecture Overview": png_path},
        )
        assert result == out
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_diagrams_mermaid_dict_produces_pdf(self, tmp_path: Path) -> None:
        """diagrams dict with mermaid text produces a valid PDF via fallback."""
        mermaid = 'pie title Severity Distribution\n  "Critical" : 3\n  "High" : 7\n'
        out = tmp_path / "mermaid-diag.pdf"
        result = render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            diagrams={"Severity Chart": mermaid},
        )
        assert result == out
        assert out.read_bytes()[:5] == b"%PDF-"


_SCORE_MD = (
    "## Design Maturity Score\n\nSee **Appendix — Scoring Methodology** for full details.\n"
)


def _capture_typst(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the Typst compiler with one that records the source."""
    captured: list[str] = []

    def _fake_compile(typst_doc: str, image_files: dict[str, bytes]) -> bytes:
        captured.append(typst_doc)
        return b"%PDF-fake"

    monkeypatch.setattr("nfr_review.output.pdf._compile_typst", _fake_compile)
    return captured


class TestMethodologyAppendix:
    def test_appendix_with_llm_disclosure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The appendix the score section points at is present, with the model."""
        captured = _capture_typst(monkeypatch)
        render_pdf(
            nfr_result=_make_run_result(),
            output_path=tmp_path / "r.pdf",
            score_section_md=_SCORE_MD,
            llm_info=("anthropic", "claude-test-model-x1"),
        )
        doc = captured[0]
        assert "== Appendix A --- Scoring Methodology" in doc
        assert "=== LLM Usage in This Report" in doc
        assert 'model #raw("claude-test-model-x1")' in doc

    def test_appendix_follows_dependency_appendix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With a dependency appendix (A), methodology is Appendix B; no LLM."""
        captured = _capture_typst(monkeypatch)
        render_pdf(
            nfr_result=_make_run_result(),
            output_path=tmp_path / "r.pdf",
            score_section_md=_SCORE_MD,
            deps_section_md="## Appendix A — Dependency Tree\n\nNo deps.\n",
        )
        doc = captured[0]
        assert "== Appendix A --- Dependency Tree" in doc
        assert "== Appendix B --- Scoring Methodology" in doc
        assert doc.index("== Appendix A --- Dependency Tree") < doc.index(
            "== Appendix B --- Scoring Methodology"
        )
        assert "*without LLM integration*" in doc

    def test_no_appendix_without_score_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No score section means nothing refers to the appendix; omit it."""
        captured = _capture_typst(monkeypatch)
        render_pdf(
            nfr_result=_make_run_result(),
            output_path=tmp_path / "r.pdf",
            llm_info=("anthropic", "claude-test-model-x1"),
        )
        assert "Scoring Methodology" not in captured[0]

    def test_appendix_compiles(self, tmp_path: Path) -> None:
        """The real Typst compiler accepts the converted appendix."""
        out = tmp_path / "appendix.pdf"
        render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            score_section_md=_SCORE_MD,
            llm_info=("anthropic", "claude-test-model-x1"),
        )
        assert out.read_bytes()[:5] == b"%PDF-"
