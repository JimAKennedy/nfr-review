"""Typst escaping, sandboxing and content tests for the PDF renderers.

These tests check what Typst actually *parses* (via ``typst.query``) rather
than substring-matching generated source, so they catch markup injection,
silently dropped text and missing report sections.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typst

import nfr_review.arch_report_render as arch_render
import nfr_review.output.pdf as pdf_mod
from nfr_review.arch_report_render import render_arch_pdf
from nfr_review.output.pdf import (
    _compile_typst,
    _raw_inline,
    _render_mermaid_for_typst,
    _t,
    render_pdf,
)
from tests.test_arch_report_render import _make_full_report
from tests.test_pdf import _make_exec_summary, _make_finding, _make_run_result

HOSTILE_STRINGS = [
    "Costs $5 per call",
    'price $upper("pwned")$ end',
    "a[0] and stray ] bracket",
    "see a // b this text must not vanish",
    "x], [INJECTED-CELL",
    "--flag ~tilde ... -? soft",
    '#read("secret.txt")',
    "C:\\repo\\src\\a.py:5",
    "src/my_module/__init__.py:10",
    "`tick` and ``double``",
    "@ref <label> * bold * _emph_",
    "= not a heading",
    "- not a list",
    "1. not an enum",
    "${DB_URL} from env",
    "trailing backslash \\",
    "/* not a comment */",
    "'single' \"double\" quotes",
]


def _query_text(markup: str, tmp_path: Path) -> str:
    """Compile *markup* inside a content block and return its plain text."""
    doc = tmp_path / "q.typ"
    doc.write_text(f"#metadata([{markup}]) <probe>\n", encoding="utf-8")
    value = json.loads(typst.query(str(doc), "<probe>", field="value", one=True))
    return _flatten(value)


def _flatten(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_flatten(n) for n in node)
    if isinstance(node, dict):
        func = node.get("func")
        if func == "space":
            return " "
        if func == "smartquote":
            return '"' if node.get("double", True) else "'"
        if "text" in node:
            return str(node["text"])
        if "children" in node:
            return _flatten(node["children"])
        if "body" in node:
            return _flatten(node["body"])
        raise AssertionError(f"unexpected markup element: {node}")
    raise AssertionError(f"unexpected node: {node!r}")


# ---------------------------------------------------------------------------
# Escaping round-trips
# ---------------------------------------------------------------------------


class TestEscaping:
    @pytest.mark.parametrize("text", HOSTILE_STRINGS)
    def test_markup_escape_round_trips_verbatim(self, text: str, tmp_path: Path) -> None:
        assert _query_text(_t(text), tmp_path) == text

    @pytest.mark.parametrize("text", HOSTILE_STRINGS)
    def test_raw_inline_round_trips_verbatim(self, text: str, tmp_path: Path) -> None:
        doc = tmp_path / "r.typ"
        doc.write_text(f"#metadata({_raw_inline(text)[1:]}) <probe>\n", encoding="utf-8")
        value = json.loads(typst.query(str(doc), "<probe>", field="value", one=True))
        assert value["func"] == "raw"
        assert value["text"] == text

    def test_raw_inline_preserves_newlines_and_tabs(self, tmp_path: Path) -> None:
        text = "line1\n\tline2\r\nend"
        doc = tmp_path / "r.typ"
        doc.write_text(f"#metadata({_raw_inline(text)[1:]}) <probe>\n", encoding="utf-8")
        value = json.loads(typst.query(str(doc), "<probe>", field="value", one=True))
        assert value["text"] == text


# ---------------------------------------------------------------------------
# Sandboxing
# ---------------------------------------------------------------------------


class TestSandbox:
    def test_compile_cannot_read_files_from_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "secret.txt").write_text("TOP-SECRET")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(Exception, match="(?i)not found|access denied|outside"):
            _compile_typst('#read("secret.txt")', {})

    def test_compile_can_read_supplied_images(self) -> None:
        pdf = _compile_typst('#read("note.txt")', {"note.txt": b"hello"})
        assert pdf.startswith(b"%PDF-")

    def test_mermaid_raw_fallback_is_not_injectable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import nfr_review.output.render as render_mod

        monkeypatch.setattr(render_mod, "render_mermaid_to_png", lambda *a, **k: None)
        (tmp_path / "secret.txt").write_text("TOP-SECRET")
        monkeypatch.chdir(tmp_path)
        mermaid = 'C4Context\n  Person(u, "x\\") #read("secret.txt") tail")'
        markup = _render_mermaid_for_typst(mermaid, {}, [0])
        doc = tmp_path / "m.typ"
        doc.write_text(f"#metadata({markup.strip()[1:]}) <probe>\n", encoding="utf-8")
        value = json.loads(typst.query(str(doc), "<probe>", field="value", one=True))
        assert value["func"] == "raw"
        assert value["text"] == mermaid


# ---------------------------------------------------------------------------
# Full documents: hostile content compiles and sections are present
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_docs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    docs: list[str] = []
    real = pdf_mod._compile_typst

    def _capture(doc: str, images: dict[str, bytes]) -> bytes:
        docs.append(doc)
        return real(doc, images)

    monkeypatch.setattr(pdf_mod, "_compile_typst", _capture)
    monkeypatch.setattr(arch_render, "_compile_typst", _capture)
    return docs


class TestReportPdfContent:
    def test_hostile_finding_text_renders(
        self, tmp_path: Path, captured_docs: list[str]
    ) -> None:
        findings = []
        for i, text in enumerate(HOSTILE_STRINGS):
            f = _make_finding(f"RULE-{i:03d}", "high", "red", locator=text)
            findings.append(f.model_copy(update={"summary": text, "recommendation": text}))
        out = tmp_path / "hostile.pdf"
        assert render_pdf(nfr_result=_make_run_result(findings), output_path=out) == out
        assert out.read_bytes().startswith(b"%PDF-")
        doc = captured_docs[-1]
        for text in HOSTILE_STRINGS:
            assert _t(text) in doc
            assert _raw_inline(text) in doc

    def test_findings_section_lists_each_rule(
        self, tmp_path: Path, captured_docs: list[str]
    ) -> None:
        render_pdf(nfr_result=_make_run_result(), output_path=tmp_path / "r.pdf")
        doc = captured_docs[-1]
        for rule_id in ("SEC-001", "DEP-002", "DOC-003", "STYLE-004"):
            assert _t(rule_id) in doc
            assert _t(f"Test finding for {rule_id}") in doc

    def test_exec_summary_content_present(
        self, tmp_path: Path, captured_docs: list[str]
    ) -> None:
        summary = _make_exec_summary()
        render_pdf(
            nfr_result=_make_run_result(),
            output_path=tmp_path / "r.pdf",
            exec_summary=summary,
        )
        doc = captured_docs[-1]
        assert _t(summary.verdict_explanation) in doc
        for item in summary.remediation_priorities:
            assert _t(item.title) in doc
            assert _t(item.description) in doc
        for risk in summary.risk_highlights:
            assert _t(risk) in doc


class TestArchPdfContent:
    def test_dollar_and_brackets_in_arch_text_render(
        self, tmp_path: Path, captured_docs: list[str]
    ) -> None:
        report = _make_full_report()
        comp = report.components[0].model_copy(
            update={"description": "Reads ${DB_URL}; costs ~$200/month [est]"}
        )
        risk = report.risk_findings[0].model_copy(update={"description": "list[int] ] $x"})
        report = report.model_copy(
            update={
                "components": [comp, *report.components[1:]],
                "risk_findings": [risk, *report.risk_findings[1:]],
            }
        )
        out = tmp_path / "arch.pdf"
        assert render_arch_pdf(report, out) == out
        doc = captured_docs[-1]
        assert _t(comp.description) in doc
        assert _t(risk.description) in doc
        assert _t(report.risk_findings[1].title) in doc
