"""Tests for HYG-LIC-004: SPDX license expression validation rule."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from nfr_review.hygiene.rules.lic_spdx import SpdxValidationRule


class TestRegistration:
    def test_rule_registered(self) -> None:
        import nfr_review.hygiene.rules  # noqa: F401
        from nfr_review.hygiene import hygiene_rule_registry

        assert "HYG-LIC-004" in hygiene_rule_registry


class TestNoContext:
    def test_skipped_when_no_context(self) -> None:
        rule = SpdxValidationRule()
        result = rule.evaluate([], None)
        assert result.skipped is True


class TestNoMetadataFiles:
    def test_skipped_when_no_files(self, tmp_path: Path) -> None:
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)
        assert result.skipped is True


class TestValidSpdx:
    def test_apache_green(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nlicense = "Apache-2.0"\n',
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "Apache-2.0" in result.findings[0].summary

    def test_mit_green(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nlicense = "MIT"\n',
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        assert result.findings[0].rag == "green"

    def test_compound_expression_green(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nlicense = "MIT AND Apache-2.0"\n',
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        assert result.findings[0].rag == "green"

    def test_license_text_dict(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nlicense = {text = "Apache-2.0"}\n',
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        assert result.findings[0].rag == "green"


class TestInvalidSpdx:
    def test_unknown_identifier_red(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nlicense = "PROPRIETARY"\n',
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        assert result.findings[0].rag == "red"
        assert "PROPRIETARY" in result.findings[0].summary

    def test_partial_invalid_red(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nlicense = "MIT AND FAKELIC"\n',
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        assert result.findings[0].rag == "red"
        assert "FAKELIC" in result.findings[0].summary


class TestDeprecatedSpdx:
    def test_deprecated_id_amber(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nlicense = "GPL-3.0"\n',
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        assert result.findings[0].rag == "amber"
        assert "GPL-3.0" in result.findings[0].summary


class TestPackageJson:
    def test_valid_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            '{"license": "ISC"}',
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        assert result.findings[0].rag == "green"


class TestCommonNameNormalization:
    def test_pom_mit_license_normalized(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text(
            '<?xml version="1.0"?>'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">'
            "<licenses><license><name>MIT License</name></license></licenses>"
            "</project>",
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        assert result.findings[0].rag == "green"

    def test_pom_apache_license_normalized(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text(
            '<?xml version="1.0"?>'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">'
            "<licenses><license>"
            "<name>The Apache Software License, Version 2.0</name>"
            "</license></licenses></project>",
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        assert result.findings[0].rag == "green"

    def test_unmapped_name_stays_invalid(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text(
            '<?xml version="1.0"?>'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">'
            "<licenses><license><name>Some Custom License</name>"
            "</license></licenses></project>",
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        assert result.findings[0].rag == "red"


class TestMultipleFiles:
    def test_both_pyproject_and_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nlicense = "MIT"\n',
            encoding="utf-8",
        )
        (tmp_path / "package.json").write_text(
            '{"license": "PROPRIETARY"}',
            encoding="utf-8",
        )
        context = SimpleNamespace(target=str(tmp_path))
        rule = SpdxValidationRule()
        result = rule.evaluate([], context)

        rags = {f.rag for f in result.findings}
        assert "green" in rags
        assert "red" in rags
