"""Tests for Spring config Band 1 rules — positive, negative, and no-evidence fixtures."""

from __future__ import annotations

import pytest

from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.spring_actuator import ActuatorExposureRiskRule
from nfr_review.rules.spring_logging import LoggingConfigMissingRule
from nfr_review.rules.spring_profile import SpringProfileMisconfigurationRule


def _spring_evidence(payload: dict, locator: str = "application.yaml") -> Evidence:
    return Evidence(
        collector_name="spring-config",
        collector_version="0.1.0",
        locator=locator,
        kind="spring-config-file",
        payload=payload,
    )


# ---------------------------------------------------------------------------
# actuator-exposure-risk
# ---------------------------------------------------------------------------


class TestActuatorExposureRiskRule:
    def setup_method(self) -> None:
        self.rule = ActuatorExposureRiskRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no spring-config evidence available"

    def test_wildcard_include_amber(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {"endpoints": {"web": {"exposure": {"include": "*"}}}},
                "logging": {},
                "server": {},
                "spring_security": {},
                "actuator": {"include": "*"},
                "raw_keys": ["management"],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        amber_or_red = [f for f in result.findings if f.rag in ("amber", "red")]
        assert len(amber_or_red) >= 1
        assert amber_or_red[0].severity in ("medium", "high")
        assert amber_or_red[0].pattern_tag == "actuator-exposure"

    def test_wildcard_include_prod_profile_red(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application-prod.yaml",
                "profile": "prod",
                "management": {
                    "endpoints": {"web": {"exposure": {"include": "*"}}},
                    "server": {"port": "8080"},
                },
                "logging": {},
                "server": {"port": "8080"},
                "spring_security": {},
                "actuator": {"include": "*"},
                "raw_keys": ["management", "server"],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        red_findings = [f for f in result.findings if f.rag == "red"]
        assert len(red_findings) >= 1
        assert red_findings[0].severity == "high"

    def test_restricted_include_green(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {
                    "endpoints": {"web": {"exposure": {"include": "health,info"}}},
                },
                "logging": {},
                "server": {},
                "spring_security": {},
                "actuator": {"include": "health,info"},
                "raw_keys": ["management"],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_no_actuator_config_green(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {},
                "logging": {},
                "server": {},
                "spring_security": {},
                "actuator": {},
                "raw_keys": [],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_wildcard_with_exclude_covers_sensitive(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {
                    "endpoints": {
                        "web": {
                            "exposure": {
                                "include": "*",
                                "exclude": (
                                    "env,configprops,beans,heapdump,threaddump,mappings"
                                ),
                            }
                        }
                    },
                },
                "logging": {},
                "server": {},
                "spring_security": {},
                "actuator": {
                    "include": "*",
                    "exclude": "env,configprops,beans,heapdump,threaddump,mappings",
                },
                "raw_keys": ["management"],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# logging-config-missing
# ---------------------------------------------------------------------------


class TestLoggingConfigMissingRule:
    def setup_method(self) -> None:
        self.rule = LoggingConfigMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no spring-config evidence available"

    def test_no_structured_logging_amber(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {},
                "logging": {"level": {"root": "INFO"}},
                "server": {},
                "spring_security": {},
                "actuator": {},
                "raw_keys": ["logging"],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "low"
        assert result.findings[0].pattern_tag == "logging-config"

    def test_json_encoder_green(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {},
                "logging": {
                    "pattern": {"console": "%d{yyyy-MM-dd} JSON %msg%n"},
                },
                "server": {},
                "spring_security": {},
                "actuator": {},
                "raw_keys": ["logging"],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_logback_reference_green(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {},
                "logging": {"config": "classpath:logback-spring.xml"},
                "server": {},
                "spring_security": {},
                "actuator": {},
                "raw_keys": ["logging"],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_logstash_encoder_green(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {},
                "logging": {
                    "appender": {"encoder": "logstash"},
                },
                "server": {},
                "spring_security": {},
                "actuator": {},
                "raw_keys": ["logging"],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# spring-profile-misconfiguration
# ---------------------------------------------------------------------------


class TestSpringProfileMisconfigurationRule:
    def setup_method(self) -> None:
        self.rule = SpringProfileMisconfigurationRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no spring-config evidence available"

    def test_prod_debug_logging_amber(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application-prod.yaml",
                "profile": "prod",
                "management": {},
                "logging": {"level": {"root": "DEBUG"}},
                "server": {},
                "spring_security": {},
                "actuator": {},
                "raw_keys": ["logging"],
            },
            locator="src/main/resources/application-prod.yaml",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) >= 1
        assert amber[0].severity == "medium"
        assert amber[0].pattern_tag == "profile-config"

    def test_prod_inmemory_db_red(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application-prod.yaml",
                "profile": "prod",
                "management": {},
                "logging": {},
                "server": {},
                "spring_security": {},
                "actuator": {},
                "raw_keys": ["spring"],
                "spring": {
                    "datasource": {"url": "jdbc:h2:mem:testdb"},
                },
            },
            locator="src/main/resources/application-prod.yaml",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        red = [f for f in result.findings if f.rag == "red"]
        assert len(red) >= 1
        assert red[0].severity == "high"

    def test_prod_show_sql_amber(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application-prod.yaml",
                "profile": "prod",
                "management": {},
                "logging": {},
                "server": {},
                "spring_security": {},
                "actuator": {},
                "raw_keys": ["spring"],
                "spring": {
                    "jpa": {"show-sql": "true"},
                },
            },
            locator="src/main/resources/application-prod.yaml",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) >= 1

    def test_prod_clean_config_green(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application-prod.yaml",
                "profile": "prod",
                "management": {},
                "logging": {"level": {"root": "WARN"}},
                "server": {"port": "8080"},
                "spring_security": {},
                "actuator": {},
                "raw_keys": ["logging", "server"],
            },
            locator="src/main/resources/application-prod.yaml",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_no_prod_profile_green(self) -> None:
        ev = _spring_evidence(
            {
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {},
                "logging": {},
                "server": {},
                "spring_security": {},
                "actuator": {},
                "raw_keys": [],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_base_debug_not_overridden_amber(self) -> None:
        base = _spring_evidence(
            {
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {},
                "logging": {"level": {"root": "DEBUG"}},
                "server": {},
                "spring_security": {},
                "actuator": {},
                "raw_keys": ["logging"],
            }
        )
        prod = _spring_evidence(
            {
                "file_path": "src/main/resources/application-prod.yaml",
                "profile": "prod",
                "management": {},
                "logging": {},
                "server": {},
                "spring_security": {},
                "actuator": {},
                "raw_keys": [],
            },
            locator="src/main/resources/application-prod.yaml",
        )
        result = self.rule.evaluate([base, prod], None)
        assert not result.skipped
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) >= 1
        assert "debug" in amber[0].summary.lower() or "inherit" in amber[0].summary.lower()


# ---------------------------------------------------------------------------
# Cross-cutting: protocol compliance and R007 field completeness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_class",
    [
        ActuatorExposureRiskRule,
        LoggingConfigMissingRule,
        SpringProfileMisconfigurationRule,
    ],
)
def test_rule_protocol_compliance(rule_class: type) -> None:
    rule = rule_class()
    assert hasattr(rule, "id")
    assert hasattr(rule, "band")
    assert hasattr(rule, "required_collectors")
    assert hasattr(rule, "required_tech")
    assert rule.band == 1
    assert rule.required_collectors == ["spring-config"]
    assert rule.required_tech == ["spring_boot"]
    result = rule.evaluate([], None)
    assert isinstance(result, RuleResult)
    assert result.skipped is True


@pytest.mark.parametrize(
    "rule_class",
    [
        ActuatorExposureRiskRule,
        LoggingConfigMissingRule,
        SpringProfileMisconfigurationRule,
    ],
)
def test_finding_has_all_r007_fields(rule_class: type) -> None:
    """Verify that when a rule fires, findings have all 10 R007 fields."""
    ev = _spring_evidence(
        {
            "file_path": "src/main/resources/application.yaml",
            "profile": None,
            "management": {},
            "logging": {"level": {"root": "INFO"}},
            "server": {},
            "spring_security": {},
            "actuator": {},
            "raw_keys": ["logging"],
        }
    )
    rule = rule_class()
    result = rule.evaluate([ev], None)
    assert not result.skipped
    for finding in result.findings:
        assert finding.rule_id
        assert finding.rag in ("red", "amber", "green")
        assert finding.severity
        assert finding.summary
        assert finding.recommendation
        assert finding.evidence_locator
        assert finding.collector_name == "spring-config"
        assert finding.collector_version == "0.1.0"
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.pattern_tag
