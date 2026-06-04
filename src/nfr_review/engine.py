# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Engine orchestration for nfr-review.

Wires the collector and rule registries into a runnable pipeline. The contract
is deliberately fault-tolerant (R012): a misbehaving collector or rule must
never abort the run. Failures surface as warnings and ``skipped`` RuleResults
so downstream emitters (CSV/JSONL in T06) can record them as auditable rows.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nfr_review.auditability import build_run_metadata
from nfr_review.config import Config
from nfr_review.models import Evidence, Finding, RuleResult, RunMetadata
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path
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
    evidence: list[Evidence] = field(default_factory=list)


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
        workers: int = 1,
    ) -> None:
        self._collectors: Registry[Collector] = (
            collectors if collectors is not None else _default_collector_registry
        )
        self._rules: Registry[Rule] = rules if rules is not None else _default_rule_registry
        self._workers = max(1, workers)

    @staticmethod
    def _run_one_collector(
        collector: Collector,
        target: Path,
        config: Config,
        exclude_pats: Any,
    ) -> tuple[str, list[Evidence], str | None]:
        """Run a single collector and return (name, evidence, error_msg | None)."""
        try:
            produced = collector.collect(target, config)
        # nfr-review:skip(bare-except-catch-all, python-broad-except-silent)
        except Exception as exc:  # noqa: BLE001  # R012: never abort the run
            return collector.name, [], f"collector {collector.name} failed: {exc}"
        produced = [
            e
            for e in produced
            if not should_exclude_path(
                e.locator,
                exclude_test_paths=config.exclude_test_paths,
                exclude_patterns=exclude_pats,
            )
        ]
        return collector.name, produced, None

    def _collect_sequential(
        self,
        collectors: list[Collector],
        target: Path,
        config: Config,
        exclude_pats: Any,
        evidence: list[Evidence],
        warnings: list[str],
        succeeded: set[str],
    ) -> None:
        total = len(collectors)
        for i, collector in enumerate(collectors, 1):
            logger.info("[%d/%d] Running collector: %s", i, total, collector.name)
            t0 = time.monotonic()
            name, produced, err = self._run_one_collector(
                collector,
                target,
                config,
                exclude_pats,
            )
            elapsed = time.monotonic() - t0
            if err:
                logger.warning("%s", err, exc_info=False)
                warnings.append(err)
                continue
            evidence.extend(produced)
            succeeded.add(name)
            logger.info(
                "  collector %s finished: %d evidence items in %.2fs",
                name,
                len(produced),
                elapsed,
            )

    def _collect_parallel(
        self,
        collectors: list[Collector],
        target: Path,
        config: Config,
        exclude_pats: Any,
        evidence: list[Evidence],
        warnings: list[str],
        succeeded: set[str],
    ) -> None:
        total = len(collectors)
        logger.info("Dispatching %d collectors across %d threads", total, self._workers)
        ordered_results: list[tuple[str, list[Evidence], str | None]] = [
            ("", [], None) for _ in range(total)
        ]
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            future_to_idx = {
                pool.submit(self._run_one_collector, c, target, config, exclude_pats): i
                for i, c in enumerate(collectors)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                ordered_results[idx] = future.result()

        for name, produced, err in ordered_results:
            if err:
                logger.warning("%s", err, exc_info=False)
                warnings.append(err)
                continue
            evidence.extend(produced)
            succeeded.add(name)
            logger.info(
                "  collector %s finished: %d evidence items",
                name,
                len(produced),
            )

    def run(self, target: Path, config: Config) -> RunResult:
        if not target.exists():
            raise EngineError(f"target does not exist: {target}")
        if not target.is_dir():
            raise EngineError(f"target is not a directory: {target}")

        config = config.model_copy(update={"target": target.resolve()})

        active_collectors = _select_collectors(self._collectors, config.collectors.skip)

        exclude_pats = (
            compile_exclude_patterns(config.exclude_paths) if config.exclude_paths else None
        )

        evidence: list[Evidence] = []
        warnings: list[str] = []
        succeeded_collectors: set[str] = set()

        n_collectors = len(active_collectors)
        logger.info(
            "Collection phase: %d collectors to run (workers=%d)",
            n_collectors,
            self._workers,
        )
        collection_t0 = time.monotonic()

        if self._workers <= 1:
            self._collect_sequential(
                active_collectors,
                target,
                config,
                exclude_pats,
                evidence,
                warnings,
                succeeded_collectors,
            )
        else:
            self._collect_parallel(
                active_collectors,
                target,
                config,
                exclude_pats,
                evidence,
                warnings,
                succeeded_collectors,
            )

        collection_elapsed = time.monotonic() - collection_t0
        logger.info(
            "Collection phase complete: %d/%d succeeded, %d evidence items, %.2fs total",
            len(succeeded_collectors),
            n_collectors,
            len(evidence),
            collection_elapsed,
        )

        rule_results: list[RuleResult] = []
        findings: list[Finding] = []
        rules_run: list[str] = []
        rules_skipped: list[dict[str, Any]] = []

        all_rules = self._rules.all()
        logger.info("Rules phase: %d rules registered", len(all_rules))
        rules_t0 = time.monotonic()

        for rule in all_rules:
            cfg_skip, cfg_reason = _classify_rule(
                rule, config.rules.skip, config.rules.include_only
            )
            if cfg_skip:
                assert cfg_reason is not None
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

            logger.info("  Evaluating rule: %s", rule.id)
            t0 = time.monotonic()
            try:
                result = rule.evaluate(evidence, config)
            # nfr-review:skip(bare-except-catch-all, python-broad-except-silent)
            except Exception as exc:  # noqa: BLE001  # R012: never abort the run
                reason = str(exc) or type(exc).__name__
                logger.warning("rule %s failed: %s", rule.id, exc, exc_info=False)
                rule_results.append(
                    RuleResult(rule_id=rule.id, skipped=True, skip_reason=reason)
                )
                rules_skipped.append({"rule_id": rule.id, "reason": reason})
                continue
            elapsed = time.monotonic() - t0

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
                if elapsed > 0.5:
                    logger.info(
                        "  rule %s: %d findings in %.2fs (slow)",
                        rule.id,
                        len(result.findings),
                        elapsed,
                    )

        rules_elapsed = time.monotonic() - rules_t0
        logger.info(
            "Rules phase complete: %d run, %d skipped, %d findings, %.2fs total",
            len(rules_run),
            len(rules_skipped),
            len(findings),
            rules_elapsed,
        )

        run_metadata = build_run_metadata(target, active_collectors, rules_run, rules_skipped)

        return RunResult(
            findings=findings,
            rule_results=rule_results,
            run_metadata=run_metadata,
            warnings=warnings,
            evidence=evidence,
        )


__all__ = ["Engine", "EngineError", "RunResult"]
