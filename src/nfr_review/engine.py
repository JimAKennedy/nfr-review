"""Engine orchestration for nfr-review.

Wires the collector and rule registries into a runnable pipeline. The contract
is deliberately fault-tolerant (R012): a misbehaving collector or rule must
never abort the run. Failures surface as warnings and ``skipped`` RuleResults
so downstream emitters (CSV/JSONL in T06) can record them as auditable rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nfr_review.auditability import build_run_metadata
from nfr_review.config import Config
from nfr_review.models import Evidence, Finding, RuleResult, RunMetadata
from nfr_review.protocols import Collector, Rule
from nfr_review.registry import Registry
from nfr_review.registry import collector_registry as _default_collector_registry
from nfr_review.registry import rule_registry as _default_rule_registry

logger = logging.getLogger(__name__)


class EngineError(Exception):
    """Raised when the engine cannot proceed at all (e.g., target missing)."""


@dataclass
class RunResult:
    """Aggregate output of a single nfr-review scan."""

    findings: list[Finding] = field(default_factory=list)
    rule_results: list[RuleResult] = field(default_factory=list)
    run_metadata: RunMetadata | None = None
    warnings: list[str] = field(default_factory=list)


def _select_collectors(registry: Registry[Collector], skip: list[str]) -> list[Collector]:
    skip_set = set(skip)
    return [c for c in registry.all() if c.name not in skip_set]


def _classify_rule(
    rule: Rule, skip: list[str], include_only: list[str] | None
) -> tuple[bool, str | None]:
    """Decide whether a rule should run. Returns (skip?, reason)."""
    if rule.id in set(skip):
        return True, "excluded by config.rules.skip"
    if include_only is not None and rule.id not in set(include_only):
        return True, "not present in config.rules.include_only"
    return False, None


class Engine:
    """Run collectors then rules against a target repository.

    The engine never aborts mid-run on collector or rule errors. Such errors
    are demoted to log warnings and recorded as ``skipped`` RuleResults / run
    warnings so they remain visible in downstream output.
    """

    def __init__(
        self,
        *,
        collectors: Registry[Collector] | None = None,
        rules: Registry[Rule] | None = None,
    ) -> None:
        self._collectors: Registry[Collector] = (
            collectors if collectors is not None else _default_collector_registry
        )
        self._rules: Registry[Rule] = rules if rules is not None else _default_rule_registry

    def run(self, target: Path, config: Config) -> RunResult:
        if not target.exists():
            raise EngineError(f"target does not exist: {target}")
        if not target.is_dir():
            raise EngineError(f"target is not a directory: {target}")

        active_collectors = _select_collectors(self._collectors, config.collectors.skip)

        evidence: list[Evidence] = []
        warnings: list[str] = []
        succeeded_collectors: set[str] = set()

        for collector in active_collectors:
            try:
                produced = collector.collect(target, config)
            except Exception as exc:  # R012: never abort the run
                logger.warning("collector %s failed: %s", collector.name, exc, exc_info=False)
                warnings.append(f"collector {collector.name} failed: {exc}")
                continue
            evidence.extend(produced)
            succeeded_collectors.add(collector.name)

        rule_results: list[RuleResult] = []
        findings: list[Finding] = []
        rules_run: list[str] = []
        rules_skipped: list[dict[str, Any]] = []

        for rule in self._rules.all():
            cfg_skip, cfg_reason = _classify_rule(
                rule, config.rules.skip, config.rules.include_only
            )
            if cfg_skip:
                assert cfg_reason is not None  # nosec B101
                rule_results.append(
                    RuleResult(rule_id=rule.id, skipped=True, skip_reason=cfg_reason)
                )
                rules_skipped.append({"rule_id": rule.id, "reason": cfg_reason})
                continue

            required_tech: list[str] = getattr(rule, "required_tech", [])
            missing_tech = [t for t in required_tech if not config.tech.get(t, False)]
            if missing_tech:
                reason = f"tech not declared: {', '.join(missing_tech)}"
                rule_results.append(
                    RuleResult(rule_id=rule.id, skipped=True, skip_reason=reason)
                )
                rules_skipped.append({"rule_id": rule.id, "reason": reason})
                continue

            missing = [c for c in rule.required_collectors if c not in succeeded_collectors]
            if missing:
                reason = f"missing required collectors: {', '.join(missing)}"
                rule_results.append(
                    RuleResult(rule_id=rule.id, skipped=True, skip_reason=reason)
                )
                rules_skipped.append({"rule_id": rule.id, "reason": reason})
                continue

            try:
                result = rule.evaluate(evidence, config)
            except Exception as exc:  # R012: never abort the run
                reason = str(exc) or type(exc).__name__
                logger.warning("rule %s failed: %s", rule.id, exc, exc_info=False)
                rule_results.append(
                    RuleResult(rule_id=rule.id, skipped=True, skip_reason=reason)
                )
                rules_skipped.append({"rule_id": rule.id, "reason": reason})
                continue

            rule_results.append(result)
            if result.skipped:
                rules_skipped.append(
                    {
                        "rule_id": rule.id,
                        "reason": result.skip_reason or "rule reported skipped",
                    }
                )
            else:
                rules_run.append(rule.id)
                findings.extend(result.findings)

        run_metadata = build_run_metadata(target, active_collectors, rules_run, rules_skipped)

        return RunResult(
            findings=findings,
            rule_results=rule_results,
            run_metadata=run_metadata,
            warnings=warnings,
        )


__all__ = ["Engine", "EngineError", "RunResult"]
