# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Click command-line interface for nfr-review.

Wires the four user-facing commands (R010): ``run``, ``list-rules``,
``explain``, ``version``. The CLI is the only place that translates internal
exceptions (``ConfigError``, ``EngineError``, ``OutputError``) into exit codes;
library code never calls ``sys.exit``.

Exit-code matrix:

* ``0`` — success
* ``1`` — recoverable failure (bad target, ConfigError, EngineError, OutputError,
  unknown rule for ``explain``)
* ``2`` — at least one emitted finding has ``severity`` >= ``config.severity_threshold``

The ``run`` summary is printed to *stderr* so machine-readable artifacts (CSV,
JSONL) can be piped from stdout-equivalent file paths without contamination.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

import nfr_review.collectors  # noqa: F401  # side-effect: register built-ins
import nfr_review.hygiene.collectors  # noqa: F401  # side-effect: register hygiene collectors
import nfr_review.hygiene.rules  # noqa: F401  # side-effect: register hygiene rules
import nfr_review.rules  # noqa: F401  # side-effect: register built-ins
from nfr_review import __version__
from nfr_review.compliance_mapping import FRAMEWORK_LABELS, FRAMEWORK_SLUGS
from nfr_review.config import Config, ConfigError, load_config
from nfr_review.detect import detect_technologies
from nfr_review.engine import Engine, EngineError, RunResult
from nfr_review.hygiene import hygiene_collector_registry, hygiene_rule_registry
from nfr_review.models import Finding, Origin, Severity
from nfr_review.output import OutputError, write_csv, write_jsonl
from nfr_review.registry import Registry, rule_registry

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ReportResult:
    """Structured result from run_report_pipeline."""

    md_path: Path
    csv_path: Path
    jsonl_path: Path
    sarif_path: Path | None
    pdf_path: Path | None
    html_path: Path | None
    total_findings: int
    nfr_count: int
    hygiene_count: int


_SEVERITY_ORDER: tuple[Severity, ...] = ("info", "low", "medium", "high", "critical")


def _apply_framework_filter(
    findings: list[Finding], framework: str
) -> tuple[list[Finding], int]:
    """Filter findings to only those mapped to *framework*.

    Returns ``(filtered_findings, excluded_count)``.
    """
    from nfr_review.compliance_mapping import rules_for_framework

    mapped_rules = rules_for_framework(framework)
    filtered = [f for f in findings if f.rule_id in mapped_rules]
    return filtered, len(findings) - len(filtered)


def _with_findings(result: RunResult, findings: list[Finding]) -> RunResult:
    """Return a copy of *result* with replaced findings list."""
    return RunResult(
        findings=findings,
        rule_results=result.rule_results,
        run_metadata=result.run_metadata,
        warnings=result.warnings,
        evidence=result.evidence,
    )


def _severity_rank(sev: Severity) -> int:
    return _SEVERITY_ORDER.index(sev)


def _exceeds_threshold(run_result: RunResult, threshold: Severity | None) -> bool:
    if threshold is None:
        return False
    cutoff = _severity_rank(threshold)
    return any(_severity_rank(f.severity) >= cutoff for f in run_result.findings)


def _rule_summary(rule: object) -> str:
    doc = getattr(rule, "__doc__", None) or type(rule).__doc__
    if not doc:
        return "(no description)"
    return doc.strip().splitlines()[0]


def _rule_description(rule: object) -> str:
    doc = getattr(rule, "__doc__", None) or type(rule).__doc__
    if not doc:
        return "(no description)"
    # Dedent: take the docstring and trim leading/trailing blank lines.
    return "\n".join(line.rstrip() for line in doc.strip().splitlines())


def _repo_name(target: Path) -> str:
    """Extract a filesystem-safe repo name from the target directory."""
    return target.resolve().name


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _ts_echo(msg: str, *, quiet: bool = False) -> None:
    if not quiet:
        click.echo(f"[{_timestamp()}] {msg}", err=True)


def _print_collector_warnings(warnings: list[str], *, quiet: bool = False) -> None:
    """Print a summary line for collector/engine warnings visible without -v."""
    if not warnings:
        return
    _ts_echo(
        f"WARNING: {len(warnings)} collector(s) produced warnings — run with -v for details",
        quiet=quiet,
    )
    for w in warnings:
        logger.info("%s", w)


def _phase(name: str, *, quiet: bool = False) -> float:
    _ts_echo(name, quiet=quiet)
    return time.monotonic()


def _phase_done(name: str, t0: float, *, quiet: bool = False) -> None:
    elapsed = time.monotonic() - t0
    if not quiet:
        click.echo(f"[{_timestamp()}] {name} completed ({elapsed:.1f}s)", err=True)


def _banner(
    command: str,
    repo: str,
    target: Path,
    *,
    options: dict[str, str] | None = None,
    phases: list[str] | None = None,
    quiet: bool = False,
) -> None:
    if quiet:
        return
    click.echo(f"\nnfr-review {command} v{__version__}", err=True)
    click.echo(f"Repository: {repo} ({target.resolve()})", err=True)
    click.echo(f"Started:    {_timestamp()}", err=True)
    if options:
        parts = [f"{k}={v}" for k, v in options.items()]
        click.echo(f"Options:    {', '.join(parts)}", err=True)
    if phases:
        click.echo(f"Phases:     {' → '.join(phases)}", err=True)
    click.echo("", err=True)


# nfr-review:skip(python-dormant-classes) reason: added to handlers in _setup_logging
class _DedupFilter(logging.Filter):
    """Suppress duplicate log messages within a single run."""

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[str] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if msg in self._seen:
            return False
        self._seen.add(msg)
        return True

    def reset(self) -> None:
        self._seen.clear()


def _configure_logging(verbose: int, quiet: bool, log_file: Path | None) -> None:
    """Configure the ``nfr_review`` logger hierarchy.

    Parameters
    ----------
    verbose:
        0 = WARNING (default), 1 = INFO, >=2 = DEBUG.
    quiet:
        If *True*, force ERROR level (overrides *verbose*).
    log_file:
        If set, write diagnostics to this file instead of stderr.
    """
    if quiet:
        level = logging.ERROR
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    logger = logging.getLogger("nfr_review")
    logger.handlers.clear()
    logger.setLevel(level)

    formatter = logging.Formatter(
        "[%(asctime)s UTC] %(levelname)s: %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    formatter.converter = time.gmtime

    if log_file is not None:
        try:
            handler: logging.Handler = logging.FileHandler(log_file)
        except OSError:
            click.echo(
                f"warning: cannot open log file {log_file}, falling back to stderr",
                err=True,
            )
            handler = logging.StreamHandler(sys.stderr)
    else:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(formatter)
    handler.addFilter(_DedupFilter())
    logger.addHandler(handler)
    logger.propagate = False


def _init_runtime() -> None:
    """One-time runtime setup: capabilities check and tracing init."""
    from nfr_review.capabilities import detect_capabilities, log_capabilities

    log_capabilities(detect_capabilities())

    from nfr_review.tracing import init_tracing

    init_tracing()


def _validate_target(target: Path) -> None:
    """Abort with exit 1 if *target* doesn't exist or isn't a directory."""
    if not target.exists():
        click.echo(f"error: target does not exist: {target}", err=True)
        raise click.exceptions.Exit(1)
    if not target.is_dir():
        click.echo(f"error: target is not a directory: {target}", err=True)
        raise click.exceptions.Exit(1)


def _load_effective_config(config_path: Path | None, *, quiet: bool = False) -> Config:
    """Load config from explicit path or default, with phase logging."""
    _phase("Loading configuration", quiet=quiet)
    effective = config_path
    if effective is None:
        default = Path("nfr-review.yaml")
        if default.exists():
            effective = default
    run_logger = logging.getLogger("nfr_review")
    run_logger.info("Loading config from %s", effective or "(defaults)")
    try:
        return load_config(effective)
    except ConfigError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc


def _detect_and_merge_tech(
    target: Path,
    config: Config,
    *,
    include_tests: bool = True,
    otel_traces_path: Path | None = None,
    quiet: bool = False,
) -> tuple[Config, dict[str, Any]]:
    """Detect technologies, merge with config, and return updated config + raw detected map."""
    _phase("Detecting technologies", quiet=quiet)
    run_logger = logging.getLogger("nfr_review")
    run_logger.info("Detecting technologies in %s", target)
    try:
        detected = detect_technologies(target)
    except Exception as e:  # noqa: BLE001
        logger.debug("Technology detection failed for %s: %s", target, e)
        detected = {}
    merged_tech = {**detected, **config.tech}
    updates: dict[str, Any] = {"tech": merged_tech, "exclude_test_paths": not include_tests}
    if otel_traces_path is not None:
        updates["otel_traces"] = otel_traces_path.resolve()
    config = config.model_copy(update=updates)
    active_tech = [k for k, v in merged_tech.items() if v]
    if active_tech:
        _ts_echo(f"Technologies: {', '.join(sorted(active_tech))}", quiet=quiet)
    return config, detected


def _create_collector_mgr(target: Path, collector: bool, *, quiet: bool = False) -> Any:
    """Create an OTel CollectorManager if requested, or return None."""
    if not collector:
        return None
    from nfr_review.collector_manager import CollectorManager, find_binary, resolve_config

    binary = find_binary()
    if binary is None:
        _ts_echo(
            "warning: OTel Collector binary not found on PATH, "
            "continuing without dynamic trace collection",
            quiet=quiet,
        )
        return None
    coll_config = resolve_config(target)
    return CollectorManager(binary, coll_config)


def _run_nfr_scan(
    target: Path,
    config: Config,
    workers: int,
    collector_mgr: Any,
    *,
    quiet: bool = False,
) -> RunResult:
    """Execute the NFR engine scan with optional OTel collector lifecycle."""
    try:
        if collector_mgr is not None:
            trace_path = collector_mgr.start()
            config = config.model_copy(update={"otel_traces": trace_path})
            _ts_echo(f"OTel Collector started: pid={collector_mgr.pid}", quiet=quiet)

        t0 = _phase("Running NFR scan (collect + evaluate)", quiet=quiet)
        run_logger = logging.getLogger("nfr_review")
        run_logger.info("Starting NFR engine scan")
        try:
            result = Engine(workers=workers).run(target, config)
        except EngineError as exc:
            click.echo(f"error: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        _phase_done("NFR scan", t0, quiet=quiet)
    finally:
        if collector_mgr is not None:
            collector_mgr.stop()
            collector_mgr.cleanup()
    return result


def _apply_suppressions(
    result: RunResult, target: Path, *, quiet: bool = False
) -> tuple[RunResult, list[tuple[Finding, Any]] | None]:
    """Apply inline suppression markers, returning updated result and suppressed pairs."""
    from nfr_review.suppression import apply_suppressions

    active_findings, suppressed_pairs = apply_suppressions(
        result.findings, target_root=target.resolve()
    )
    if suppressed_pairs:
        with_reason = sum(1 for _, info in suppressed_pairs if info.reason)
        _ts_echo(
            f"Suppressed: {len(suppressed_pairs)} finding(s) via inline markers"
            f" ({with_reason} with justification)",
            quiet=quiet,
        )
        result = _with_findings(result, active_findings)
    return result, suppressed_pairs or None


def _apply_baseline_filter(
    result: RunResult, baseline_path: Path | None, *, quiet: bool = False
) -> tuple[RunResult, Any]:
    """Filter findings against a baseline JSONL, returning classification info."""
    if baseline_path is None:
        return result, None
    from nfr_review.baseline import classify_findings, filter_new_findings, load_baseline

    baseline = load_baseline(baseline_path)
    classification = classify_findings(result.findings, baseline)
    new_findings = filter_new_findings(result.findings, baseline)
    _ts_echo(f"Baseline loaded: {baseline.finding_count} findings", quiet=quiet)
    _ts_echo(
        f"New findings: {len(new_findings)} "
        f"({len(classification.shifted)} shifted, "
        f"{len(classification.resolved)} resolved)",
        quiet=quiet,
    )
    return _with_findings(result, new_findings), classification


def _apply_optional_filters(
    result: RunResult,
    *,
    framework: str | None = None,
    origin: str | None = None,
    quiet: bool = False,
) -> RunResult:
    """Apply framework and/or origin filters to findings."""
    if framework is not None:
        filtered, excluded = _apply_framework_filter(result.findings, framework)
        _ts_echo(
            f"Framework filter ({FRAMEWORK_LABELS[framework]}): "
            f"{len(filtered)} mapped, {excluded} excluded",
            quiet=quiet,
        )
        result = _with_findings(result, filtered)

    if origin is not None:
        from nfr_review.output.classify import filter_findings_by_origin

        origin_val: Origin = origin  # type: ignore[assignment]
        before = len(result.findings)
        filtered_origin = filter_findings_by_origin(result.findings, origin_val)
        _ts_echo(
            f"Origin filter ({origin}): {len(filtered_origin)} kept, "
            f"{before - len(filtered_origin)} excluded",
            quiet=quiet,
        )
        result = _with_findings(result, filtered_origin)
    return result


def _handle_design_change(
    result: RunResult,
    target: Path,
    repo: str,
    config: Config,
    design_baseline_dir: Path | None,
    *,
    force_standard_config: bool = False,
) -> None:
    """Run structural baseline diff and append design-change findings."""
    if design_baseline_dir is None:
        return
    from nfr_review.design_change import (
        apply_thresholds,
        findings_from_diffs,
        format_diff_summary,
    )
    from nfr_review.design_change import build_baseline as _build_structural
    from nfr_review.design_change import diff_baselines as _diff_structural
    from nfr_review.design_change import load_baseline as _load_structural
    from nfr_review.design_change import save_baseline as _save_structural

    bl_file = design_baseline_dir / f"{repo}-structural-baseline.json"
    new_bl = _build_structural(result.evidence, str(target.resolve()))

    try:
        prev_bl = _load_structural(bl_file)
        diffs = _diff_structural(prev_bl, new_bl)
        if force_standard_config:
            from nfr_review.config import DesignChangeConfig

            effective_thresholds = DesignChangeConfig().thresholds
        else:
            effective_thresholds = config.design_change.thresholds
        diffs = apply_thresholds(diffs, effective_thresholds)
        if diffs:
            _ts_echo(format_diff_summary(diffs))
            dc_findings = findings_from_diffs(diffs, str(bl_file))
            result.findings.extend(dc_findings)
        else:
            _ts_echo("No structural changes since last baseline.")
    except FileNotFoundError:
        _ts_echo(f"No previous structural baseline found, saving initial: {bl_file}")

    _save_structural(new_bl, bl_file)


def _display_score(result: RunResult, config: Config, baseline_path: Path | None) -> None:
    """Compute and display the design maturity score."""
    from nfr_review.output.classify import partition_findings_by_origin
    from nfr_review.scoring import (
        compute_maturity_score,
        compute_trend,
        load_baseline_score,
    )

    first_party_findings, _dep = partition_findings_by_origin(result.findings)
    score = compute_maturity_score(
        first_party_findings,
        result.run_metadata.rules_run if result.run_metadata else [],
        result.run_metadata.rules_skipped if result.run_metadata else [],
        config.scoring,
    )
    click.echo("", err=True)
    _ts_echo(f"Design Maturity Score: {score.overall}/100 (Grade: {score.grade})")
    _ts_echo(f"Rules Coverage: {score.rules_coverage:.0%}")
    if score.category_scores:
        _ts_echo("Category Scores:")
        for cat, cat_score in sorted(score.category_scores.items()):
            click.echo(f"  {cat}: {cat_score}/100", err=True)

    if baseline_path is not None:
        bl_findings, bl_rules_run, bl_rules_skipped = load_baseline_score(baseline_path)
        trend = compute_trend(
            score, bl_findings, bl_rules_run, bl_rules_skipped, config.scoring
        )
        arrow = (
            "↑"
            if trend.direction == "improved"
            else "↓"
            if trend.direction == "regressed"
            else "→"
        )
        _ts_echo(f"Trend: {arrow} {trend.direction} (delta: {trend.delta:+d})")


def _write_run_outputs(
    result: RunResult,
    csv_path: Path,
    jsonl_path: Path,
    sarif_path: Path | None,
    *,
    suppressed_pairs: list[tuple[Finding, Any]] | None = None,
    classification: Any = None,
    tech_detected: int = 0,
    quiet: bool = False,
) -> None:
    """Write CSV/JSONL/SARIF output files and print the run summary."""
    run_logger = logging.getLogger("nfr_review")
    _phase("Writing output files", quiet=quiet)
    run_logger.info("Writing output files")
    try:
        write_csv(result, csv_path, suppressed_findings=suppressed_pairs)
        write_jsonl(
            result,
            jsonl_path,
            classification=classification,
            suppressed_findings=suppressed_pairs,
        )
    except OutputError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    metadata = result.run_metadata
    collectors_run = len(metadata.collector_versions) if metadata is not None else 0
    rules_run = len(metadata.rules_run) if metadata is not None else 0
    rules_skipped = len(metadata.rules_skipped) if metadata is not None else 0
    files_emitted = 2

    if sarif_path is not None:
        from nfr_review.output.sarif import write_sarif

        try:
            write_sarif(result, sarif_path)
            files_emitted += 1
        except OutputError as exc:
            click.echo(f"error: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc

    summary_parts = [
        f"nfr-review: tech_detected={tech_detected}",
        f"collectors_run={collectors_run}",
        f"rules_run={rules_run} rules_skipped={rules_skipped}",
        f"findings={len(result.findings)} files_emitted={files_emitted}",
        f"csv={csv_path} jsonl={jsonl_path}",
    ]
    if sarif_path is not None:
        summary_parts.append(f"sarif={sarif_path}")
    _ts_echo(" ".join(summary_parts))
    _print_collector_warnings(result.warnings)

    if metadata is not None and metadata.rules_skipped:
        _ts_echo(
            f"WARNING: {len(metadata.rules_skipped)} rules skipped (use -v to see details)"
        )
        for skip in metadata.rules_skipped:
            run_logger.info("rule %s skipped (%s)", skip["rule_id"], skip["reason"])


@click.group(help="Automated non-functional requirements review.")
@click.version_option(__version__, prog_name="nfr-review")
def cli() -> None:
    """Top-level command group."""


@cli.command("run", help="Run an NFR scan against TARGET (a repository directory).")
@click.argument("target", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (-v for INFO, -vv for DEBUG).",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress warnings (ERROR level only).",
)
@click.option(
    "--log-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write diagnostics to FILE instead of stderr.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to nfr-review.yaml. Defaults to ./nfr-review.yaml if present.",
)
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output path for the R007 CSV findings file. [default: {repo}-nfr-review.csv]",
)
@click.option(
    "--jsonl",
    "jsonl_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output path for the R018 JSONL run record. [default: {repo}-nfr-review.jsonl]",
)
@click.option(
    "--exclude-tests/--include-tests",
    default=True,
    help="Exclude test and fixture directories from analysis (default: exclude).",
)
@click.option(
    "--baseline",
    "baseline_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to a prior JSONL file. Suppress known findings; exit on regressions.",
)
@click.option(
    "--sarif",
    "sarif_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output path for SARIF 2.1.0 findings file.",
)
@click.option(
    "--score",
    "show_score",
    is_flag=True,
    default=False,
    help="Compute and display design maturity score.",
)
@click.option(
    "--workers",
    type=int,
    default=1,
    show_default=True,
    help="Number of parallel collector threads (1 = sequential).",
)
@click.option(
    "--otel-traces",
    "otel_traces_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to an OTLP JSON/NDJSON trace file for Band 3 dynamic analysis.",
)
@click.option(
    "--collector/--no-collector",
    default=False,
    help="Start/stop an OTel Collector subprocess to capture traces during the scan.",
)
@click.option(
    "--framework",
    type=click.Choice(FRAMEWORK_SLUGS, case_sensitive=False),
    default=None,
    help="Filter findings to rules mapped to a compliance framework.",
)
@click.option(
    "--design-baseline-dir",
    "design_baseline_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory for structural baseline snapshots (save after scan, diff on rerun).",
)
@click.option(
    "--force-standard-config",
    is_flag=True,
    default=False,
    help="Ignore project design-change threshold overrides; use built-in defaults.",
)
@click.option(
    "--origin",
    type=click.Choice(["first_party", "dependency"], case_sensitive=False),
    default=None,
    help="Filter findings by origin: first_party (direct repo issues) or dependency.",
)
def run_cmd(
    target: Path,
    verbose: int,
    quiet: bool,
    log_file: Path | None,
    config_path: Path | None,
    csv_path: Path | None,
    jsonl_path: Path | None,
    exclude_tests: bool,
    baseline_path: Path | None = None,
    sarif_path: Path | None = None,
    show_score: bool = False,
    workers: int = 1,
    otel_traces_path: Path | None = None,
    collector: bool = False,
    framework: str | None = None,
    design_baseline_dir: Path | None = None,
    force_standard_config: bool = False,
    origin: str | None = None,
) -> None:
    """Run command — load config, run engine, emit CSV+JSONL, print summary."""
    include_tests = not exclude_tests
    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    if collector and otel_traces_path is not None:
        raise click.UsageError("--collector and --otel-traces are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)
    _init_runtime()

    repo = _repo_name(target)
    if csv_path is None:
        csv_path = Path(f"{repo}-nfr-review.csv")
    if jsonl_path is None:
        jsonl_path = Path(f"{repo}-nfr-review.jsonl")
    _validate_target(target)

    opts: dict[str, str] = {}
    if not include_tests:
        opts["exclude_tests"] = "true"
    if config_path:
        opts["config"] = str(config_path)
    _banner(
        "run",
        repo,
        target,
        options=opts or None,
        phases=["config", "detect", "collect+evaluate", "output"],
        quiet=quiet,
    )

    config = _load_effective_config(config_path, quiet=quiet)
    config, detected = _detect_and_merge_tech(
        target,
        config,
        include_tests=include_tests,
        otel_traces_path=otel_traces_path,
        quiet=quiet,
    )
    tech_detected = sum(1 for v in detected.values() if v)

    collector_mgr = _create_collector_mgr(target, collector, quiet=quiet)
    result = _run_nfr_scan(target, config, workers, collector_mgr, quiet=quiet)
    result, suppressed_pairs = _apply_suppressions(result, target, quiet=quiet)
    result, classification = _apply_baseline_filter(result, baseline_path, quiet=quiet)
    result = _apply_optional_filters(result, framework=framework, origin=origin, quiet=quiet)
    _handle_design_change(
        result,
        target,
        repo,
        config,
        design_baseline_dir,
        force_standard_config=force_standard_config,
    )
    if show_score:
        _display_score(result, config, baseline_path)

    _write_run_outputs(
        result,
        csv_path,
        jsonl_path,
        sarif_path,
        suppressed_pairs=suppressed_pairs,
        classification=classification,
        tech_detected=tech_detected,
        quiet=quiet,
    )

    if baseline_path is not None and len(result.findings) > 0:
        raise click.exceptions.Exit(1)
    if _exceeds_threshold(result, config.severity_threshold):
        raise click.exceptions.Exit(2)


@cli.command("list-rules", help="List every registered rule (id, band, summary).")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (default: text).",
)
def list_rules_cmd(fmt: str) -> None:
    """List all registered rules."""
    from nfr_review.rule_metadata import get_metadata

    rules = rule_registry.all()
    if not rules:
        return

    if fmt == "json":
        entries = []
        for rule in rules:
            meta = get_metadata(rule.id)
            entry: dict[str, Any] = {
                "id": rule.id,
                "band": rule.band,
                "required_collectors": rule.required_collectors,
                "required_tech": getattr(rule, "required_tech", []),
            }
            if meta is not None:
                entry["severity"] = meta.severity
                entry["category"] = meta.category
                entry["tags"] = meta.tags
                entry["description"] = meta.description
                entry["compliance_refs"] = meta.compliance_refs
            entries.append(entry)
        click.echo(json.dumps(entries, indent=2))
    else:
        for rule in rules:
            click.echo(f"{rule.id}\tband={rule.band}\t{_rule_summary(rule)}")


@cli.command("explain", help="Print the full description of a single rule.")
@click.argument("rule_id")
def explain_cmd(rule_id: str) -> None:
    """Print rule description, exit 1 if not found."""
    if rule_id not in rule_registry:
        click.echo(f"error: no rule registered with id {rule_id!r}", err=True)
        raise click.exceptions.Exit(1)
    rule = rule_registry.get(rule_id)
    click.echo(f"rule_id: {rule.id}")
    click.echo(f"band: {rule.band}")
    click.echo(f"required_collectors: {', '.join(rule.required_collectors) or '(none)'}")
    click.echo("")
    click.echo(_rule_description(rule))


@cli.command("hygiene", help="Run a repository hygiene audit against TARGET.")
@click.argument(
    "target",
    required=False,
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (-v for INFO, -vv for DEBUG).",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress warnings (ERROR level only).",
)
@click.option(
    "--log-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write diagnostics to FILE instead of stderr.",
)
@click.option("--list-checks", is_flag=True, help="List registered hygiene checks and exit.")
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Directory where CSV and JSONL files are written.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "jsonl", "both"]),
    default="both",
    show_default=True,
    help="Output format(s) to produce.",
)
@click.option(
    "--severity-threshold",
    type=click.Choice(["info", "low", "medium", "high", "critical"]),
    default=None,
    help="Exit 2 if any finding meets or exceeds this severity.",
)
@click.option(
    "--category",
    default=None,
    help="Comma-separated category names to filter rules.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to nfr-review.yaml. Defaults to ./nfr-review.yaml if present.",
)
@click.option(
    "--exclude-tests/--include-tests",
    default=True,
    help="Exclude test and fixture directories from analysis (default: exclude).",
)
def hygiene_cmd(
    target: Path | None,
    verbose: int,
    quiet: bool,
    log_file: Path | None,
    list_checks: bool,
    output_dir: Path,
    output_format: str,
    severity_threshold: str | None,
    category: str | None,
    config_path: Path | None,
    exclude_tests: bool,
) -> None:
    """Hygiene command — run hygiene collectors and rules, emit output."""
    include_tests = not exclude_tests
    if list_checks:
        for rule in hygiene_rule_registry.all():
            cat = getattr(rule, "category", "uncategorized")
            click.echo(f"{rule.id}\tcategory={cat}\tband={rule.band}\t{_rule_summary(rule)}")
        return

    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)

    if target is None:
        click.echo("error: TARGET is required (unless --list-checks is set)", err=True)
        raise click.exceptions.Exit(1)
    _validate_target(target)

    repo = _repo_name(target)
    opts: dict[str, str] = {}
    if category:
        opts["category"] = category
    if not include_tests:
        opts["exclude_tests"] = "true"
    if output_format != "both":
        opts["format"] = output_format
    _banner(
        "hygiene",
        repo,
        target,
        options=opts or None,
        phases=["config", "detect", "collect+evaluate", "output"],
        quiet=quiet,
    )

    config = _load_effective_config(config_path, quiet=quiet)
    config, _detected = _detect_and_merge_tech(
        target,
        config,
        include_tests=include_tests,
        quiet=quiet,
    )

    effective_rules = _filter_hygiene_rules(category)
    result = _run_hygiene_scan(target, config, effective_rules, quiet=quiet)
    _write_hygiene_outputs(result, repo, output_dir, output_format)
    _print_run_summary(result, label="hygiene")

    if severity_threshold is not None:
        threshold: Severity = severity_threshold  # type: ignore[assignment]
        if _exceeds_threshold(result, threshold):
            raise click.exceptions.Exit(2)


def _filter_hygiene_rules(category: str | None) -> Registry[Any]:
    """Return the hygiene rule registry filtered by category, or the full registry."""
    if category is None:
        return hygiene_rule_registry
    from nfr_review.protocols import Rule as RuleProtocol

    requested = {c.strip() for c in category.split(",")}
    filtered: Registry[RuleProtocol] = Registry("hygiene-rule")
    for rule in hygiene_rule_registry.all():
        if getattr(rule, "category", None) in requested:
            filtered.register(rule.id, rule)
    return filtered


def _run_hygiene_scan(
    target: Path, config: Config, rules: Registry[Any], *, quiet: bool = False
) -> RunResult:
    """Execute the hygiene engine scan."""
    t0 = _phase("Running hygiene scan (collect + evaluate)", quiet=quiet)
    try:
        result: RunResult = Engine(
            collectors=hygiene_collector_registry,
            rules=rules,
        ).run(target, config)
    except EngineError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("Hygiene scan", t0, quiet=quiet)
    return result


def _write_hygiene_outputs(
    result: RunResult, repo: str, output_dir: Path, output_format: str
) -> None:
    """Write hygiene CSV/JSONL output files."""
    csv_name = f"{repo}-hygiene-report.csv"
    jsonl_name = f"{repo}-hygiene-report.jsonl"
    _phase("Writing output files")
    try:
        if output_format in ("csv", "both"):
            write_csv(result, output_dir / csv_name)
        if output_format in ("jsonl", "both"):
            write_jsonl(result, output_dir / jsonl_name)
    except OutputError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc


def _print_run_summary(result: RunResult, *, label: str = "run") -> None:
    """Print collectors/rules/findings summary and skipped-rule warnings."""
    metadata = result.run_metadata
    collectors_run = len(metadata.collector_versions) if metadata is not None else 0
    rules_run = len(metadata.rules_run) if metadata is not None else 0
    rules_skipped = len(metadata.rules_skipped) if metadata is not None else 0
    _ts_echo(
        f"nfr-review {label}: collectors_run={collectors_run} "
        f"rules_run={rules_run} rules_skipped={rules_skipped} "
        f"findings={len(result.findings)}"
    )
    _print_collector_warnings(result.warnings)
    if metadata is not None and metadata.rules_skipped:
        _ts_echo(
            f"WARNING: {len(metadata.rules_skipped)} rules skipped (use -v to see details)"
        )
        run_logger = logging.getLogger("nfr_review")
        for skip in metadata.rules_skipped:
            run_logger.info("rule %s skipped (%s)", skip["rule_id"], skip["reason"])


@dataclasses.dataclass
class _ReportSections:
    """Intermediate report sections produced by :func:`_build_report_sections`."""

    suppressed_pairs: list[tuple[Finding, Any]] | None
    pytest_result: Any
    deps_section: str
    deps_reports: list[Any]
    diagrams: dict[str, str] | None
    jdepend_section: str
    derived_adrs_section: str
    adr_section: str
    score_section: str
    llm_info: tuple[str, str] | None


def _run_scans(
    target: Path,
    config: Config,
    *,
    workers: int,
    collector_mgr: Any,
    quiet: bool,
) -> tuple[RunResult, RunResult]:
    """Execute NFR and hygiene scans with OTel collector lifecycle management."""
    try:
        if collector_mgr is not None:
            trace_path = collector_mgr.start()
            config = config.model_copy(update={"otel_traces": trace_path})
            _ts_echo(f"OTel Collector started: pid={collector_mgr.pid}", quiet=quiet)

        t0 = _phase("Running NFR scan (collect + evaluate)", quiet=quiet)
        try:
            nfr_result: RunResult = Engine(workers=workers).run(target, config)
        except EngineError as exc:
            click.echo(f"error: NFR scan failed: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        _phase_done("NFR scan", t0, quiet=quiet)

        t0 = _phase("Running hygiene scan (collect + evaluate)", quiet=quiet)
        try:
            hygiene_result: RunResult = Engine(
                collectors=hygiene_collector_registry,
                rules=hygiene_rule_registry,
                workers=workers,
            ).run(target, config)
        except EngineError as exc:
            click.echo(f"error: hygiene scan failed: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        _phase_done("Hygiene scan", t0, quiet=quiet)
    finally:
        if collector_mgr is not None:
            collector_mgr.stop()
            collector_mgr.cleanup()

    return nfr_result, hygiene_result


def _analyze_deps_section(
    target: Path, config: Config, max_resolve_rounds: int | None, *, quiet: bool
) -> tuple[str, list[Any]]:
    """Run dependency analysis and return (markdown_section, reports)."""
    from nfr_review.deps_analysis import analyze_deps
    from nfr_review.output.deps_report import render_deps_section

    t0 = _phase("Analyzing dependencies", quiet=quiet)
    try:
        reports = analyze_deps(
            target,
            config,
            resolve_transitive=True,
            progress_callback=lambda msg: _ts_echo(msg),
            max_resolve_rounds=max_resolve_rounds,
        )
        section = render_deps_section(reports)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Dependency analysis failed: %s", exc, exc_info=True)
        _ts_echo(f"warning: dependency analysis failed: {exc}")
        section = f"## Appendix A — Dependency Tree\n\nDependency analysis failed: {exc}\n"
        reports = []
    _phase_done("Dependency analysis", t0, quiet=quiet)
    return section, reports


def _build_diagrams(
    combined_findings: list[Finding],
    evidence: list[Any],
    merged_tech: dict[str, Any],
    deps_reports: list[Any],
) -> dict[str, str]:
    """Build all Mermaid diagrams from findings, tech, and deps."""
    from nfr_review.output.diagrams import (
        collect_dynamic_diagrams,
        render_mermaid_dep_graph,
        render_mermaid_severity_pie,
        render_mermaid_tech_overview,
    )

    _phase("Building diagrams")
    diagrams: dict[str, str] = {}
    if combined_findings:
        diagrams["Severity Distribution"] = render_mermaid_severity_pie(combined_findings)
    if merged_tech:
        diagrams["Technology Overview"] = render_mermaid_tech_overview(merged_tech)
    if deps_reports:
        diagrams["Dependency Graph"] = render_mermaid_dep_graph(deps_reports)
    dynamic = collect_dynamic_diagrams(combined_findings, evidence)
    if dynamic:
        diagrams.update(dynamic)
        logger.info("Added %d dynamic diagram(s): %s", len(dynamic), ", ".join(dynamic.keys()))
    return diagrams


def _build_report_sections(
    *,
    nfr_result: RunResult,
    hygiene_result: RunResult,
    combined_findings: list[Finding],
    target: Path,
    config: Config,
    merged_tech: dict[str, Any],
    no_tests: bool,
    no_deps: bool,
    no_diagrams: bool,
    show_score: bool,
    test_timeout: int,
    max_resolve_rounds: int | None,
    quiet: bool,
) -> _ReportSections:
    """Build all report sections from scan results."""
    from nfr_review.output.jdepend_section import (
        build_adr_section,
        build_derived_adrs_section,
        build_jdepend_section,
    )
    from nfr_review.output.pytest_runner import run_pytest
    from nfr_review.suppression import apply_suppressions

    _active, suppressed_pairs = apply_suppressions(
        combined_findings, target_root=target.resolve()
    )
    if suppressed_pairs:
        with_reason = sum(1 for _, info in suppressed_pairs if info.reason)
        _ts_echo(
            f"Suppressed: {len(suppressed_pairs)} finding(s) via inline markers"
            f" ({with_reason} with justification)",
            quiet=quiet,
        )

    pytest_result = None
    if not no_tests:
        t0 = _phase(f"Running pytest (timeout: {test_timeout}s)", quiet=quiet)
        pytest_result = run_pytest(target, timeout=test_timeout)
        _phase_done("Pytest", t0, quiet=quiet)

    deps_section, deps_reports = (
        _analyze_deps_section(target, config, max_resolve_rounds, quiet=quiet)
        if not no_deps
        else ("", [])
    )

    diagrams = (
        _build_diagrams(combined_findings, nfr_result.evidence, merged_tech, deps_reports)
        if not no_diagrams
        else None
    )

    return _ReportSections(
        suppressed_pairs=suppressed_pairs or None,
        pytest_result=pytest_result,
        deps_section=deps_section,
        deps_reports=deps_reports,
        diagrams=diagrams,
        jdepend_section=build_jdepend_section(nfr_result.evidence),
        derived_adrs_section=build_derived_adrs_section(nfr_result.evidence),
        adr_section=build_adr_section(nfr_result.evidence),
        score_section=_compute_score(combined_findings, nfr_result, config)
        if show_score
        else "",
        llm_info=_resolve_llm_info(config),
    )


def _compute_score(
    combined_findings: list[Finding],
    nfr_result: RunResult,
    config: Config,
) -> str:
    """Compute maturity score and return the rendered Markdown section.

    Only first-party findings contribute to the score; dependency findings
    are excluded so that vendored/third-party code does not distort the
    project's own maturity assessment.
    """
    from nfr_review.output.classify import partition_findings_by_origin
    from nfr_review.output.markdown import render_score_section
    from nfr_review.scoring import compute_maturity_score

    first_party, _dep = partition_findings_by_origin(combined_findings)
    nfr_meta = nfr_result.run_metadata
    score = compute_maturity_score(
        first_party,
        nfr_meta.rules_run if nfr_meta else [],
        nfr_meta.rules_skipped if nfr_meta else [],
        config.scoring,
    )
    return render_score_section(score)


def _resolve_llm_info(config: Config) -> tuple[str, str] | None:
    """Detect available LLM for methodology appendix disclosure."""
    from nfr_review.llm_client import ClaudeCliClient, create_llm_client

    resolved_llm = config.llm.resolve()
    _llm_client = create_llm_client(resolved_llm)
    if _llm_client.available:
        return (resolved_llm.provider, resolved_llm.model)
    _default_client = create_llm_client()
    if _default_client.available:
        _prov = "claude-cli" if isinstance(_default_client, ClaudeCliClient) else "openai"
        return (_prov, resolved_llm.model)
    return None


def _render_html(md_content: str, output_dir: Path, stem: str, *, quiet: bool) -> Path | None:
    """Render HTML report from Markdown content."""
    from nfr_review.output.html import render_html_report

    _phase("Rendering HTML report", quiet=quiet)
    html_content = render_html_report(md_content)
    html_path = output_dir / f"{stem}.html"
    try:
        html_path.write_text(html_content, encoding="utf-8")
        return html_path
    except OSError as exc:
        click.echo(f"error: HTML generation failed: {exc}", err=True)
        return None


def _render_pdf(
    *,
    nfr_result: RunResult,
    hygiene_result: RunResult,
    sections: _ReportSections,
    output_dir: Path,
    stem: str,
    no_summary: bool,
    quiet: bool,
) -> Path | None:
    """Generate PDF report with optional LLM executive summary."""
    try:
        from nfr_review.output.pdf import render_pdf
    except ImportError as exc:
        click.echo(
            "error: weasyprint is required for PDF output — "
            "install with 'pip install nfr-review[pdf]'",
            err=True,
        )
        raise click.exceptions.Exit(1) from exc

    exec_summary = None
    if not no_summary:
        from nfr_review.output.summarize import generate_executive_summary

        t0 = _phase("Generating executive summary via LLM", quiet=quiet)
        exec_summary = generate_executive_summary(
            nfr_result,
            hygiene_result,
            sections.pytest_result,
            sections.deps_section,
        )
        if exec_summary is None:
            _ts_echo("skipped (LLM not configured or unavailable)")
        else:
            _phase_done("Executive summary", t0, quiet=quiet)

    pdf_path = output_dir / f"{stem}.pdf"
    t0 = _phase("Generating PDF report", quiet=quiet)
    try:
        render_pdf(
            nfr_result=nfr_result,
            output_path=pdf_path,
            hygiene_result=hygiene_result,
            exec_summary=exec_summary,
            pytest_result=sections.pytest_result,
            deps_section_md=sections.deps_section,
            jdepend_section_md=sections.jdepend_section,
            adr_section_md=sections.adr_section,
            derived_adrs_section_md=sections.derived_adrs_section,
            diagrams=sections.diagrams,
            score_section_md=sections.score_section,
            llm_info=sections.llm_info,
        )
        _phase_done("PDF generation", t0, quiet=quiet)
        return pdf_path
    # nfr-review:skip(bare-except-catch-all, python-broad-except-silent)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"error: PDF generation failed: {exc}", err=True)
        return None


def _write_format_files(
    *,
    md_content: str,
    combined_result: RunResult,
    suppressed_pairs: list[tuple[Finding, Any]] | None,
    output_dir: Path,
    stem: str,
    sarif_path: Path | None,
    quiet: bool,
) -> tuple[Path, Path, Path, Path | None]:
    """Write Markdown, CSV, JSONL, and optionally SARIF files. Returns paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f"{stem}.md"
    csv_path = output_dir / f"{stem}.csv"
    jsonl_path = output_dir / f"{stem}.jsonl"

    _phase("Writing output files", quiet=quiet)
    try:
        md_path.write_text(md_content, encoding="utf-8")
        write_csv(combined_result, csv_path, suppressed_findings=suppressed_pairs)
        write_jsonl(combined_result, jsonl_path, suppressed_findings=suppressed_pairs)
        actual_sarif: Path | None = None
        if sarif_path is not None:
            from nfr_review.output.sarif import write_sarif

            write_sarif(combined_result, sarif_path)
            actual_sarif = sarif_path
    except (OSError, OutputError) as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    return md_path, csv_path, jsonl_path, actual_sarif


def _write_outputs(
    *,
    nfr_result: RunResult,
    hygiene_result: RunResult,
    combined_result: RunResult,
    sections: _ReportSections,
    output_dir: Path,
    stem: str,
    sarif_path: Path | None,
    html_flag: bool,
    pdf_flag: bool,
    no_summary: bool,
    quiet: bool,
    framework: str | None = None,
) -> ReportResult:
    """Render and write all output formats (Markdown, CSV, JSONL, SARIF, HTML, PDF)."""
    from nfr_review.output.markdown import render_markdown_report

    _phase("Rendering Markdown report", quiet=quiet)
    md_content = render_markdown_report(
        nfr_result=nfr_result,
        hygiene_result=hygiene_result,
        pytest_result=sections.pytest_result,
        deps_section=sections.deps_section,
        jdepend_section=sections.jdepend_section,
        adr_section=sections.adr_section,
        derived_adrs_section=sections.derived_adrs_section,
        diagrams=sections.diagrams,
        score_section=sections.score_section,
        suppressed_findings=sections.suppressed_pairs,
        llm_info=sections.llm_info,
        framework=framework,
    )

    md_path, csv_path, jsonl_path, actual_sarif = _write_format_files(
        md_content=md_content,
        combined_result=combined_result,
        suppressed_pairs=sections.suppressed_pairs,
        output_dir=output_dir,
        stem=stem,
        sarif_path=sarif_path,
        quiet=quiet,
    )

    html_path = _render_html(md_content, output_dir, stem, quiet=quiet) if html_flag else None
    pdf_path = (
        _render_pdf(
            nfr_result=nfr_result,
            hygiene_result=hygiene_result,
            sections=sections,
            output_dir=output_dir,
            stem=stem,
            no_summary=no_summary,
            quiet=quiet,
        )
        if pdf_flag
        else None
    )

    nfr_count = len(nfr_result.findings)
    hygiene_count = len(hygiene_result.findings)
    total = nfr_count + hygiene_count
    if not quiet:
        click.echo("", err=True)
    parts = [
        f"nfr-review report: findings={total}",
        f"output={md_path} csv={csv_path} jsonl={jsonl_path}",
    ]
    if html_path:
        parts.append(f"html={html_path}")
    if pdf_path:
        parts.append(f"pdf={pdf_path}")
    if actual_sarif is not None:
        parts.append(f"sarif={actual_sarif}")
    _ts_echo(" ".join(parts))
    _print_collector_warnings(combined_result.warnings)

    return ReportResult(
        md_path=md_path,
        csv_path=csv_path,
        jsonl_path=jsonl_path,
        sarif_path=actual_sarif,
        pdf_path=pdf_path,
        html_path=html_path,
        total_findings=total,
        nfr_count=nfr_count,
        hygiene_count=hygiene_count,
    )


def _report_phases_and_opts(
    *,
    no_tests: bool,
    no_deps: bool,
    no_diagrams: bool,
    pdf: bool,
    no_summary: bool,
    include_tests: bool,
    test_timeout: int,
) -> tuple[list[str], dict[str, str]]:
    """Build the phase list and options dict for the report banner."""
    phases = ["config", "detect", "nfr-scan", "hygiene-scan"]
    opts: dict[str, str] = {}
    if not no_tests:
        phases.append("pytest")
        opts["test_timeout"] = f"{test_timeout}s"
    else:
        opts["tests"] = "skipped"
    if not no_deps:
        phases.append("deps")
    else:
        opts["deps"] = "skipped"
    if not no_diagrams:
        phases.append("diagrams")
    if pdf:
        phases.append("pdf")
        if not no_summary:
            phases.append("llm-summary")
    phases.append("output")
    if not include_tests:
        opts["exclude_tests"] = "true"
    return phases, opts


def _merge_repo_local_config(config: Config, config_path: Path | None, target: Path) -> Config:
    """Merge repo-local nfr-review.yaml scoring overrides into *config*."""
    if config_path is None:
        return config
    repo_local = target / "nfr-review.yaml"
    if repo_local.exists() and repo_local.resolve() != config_path.resolve():
        try:
            repo_config = load_config(repo_local)
            return config.with_repo_scoring(repo_config)
        except ConfigError:
            pass
    return config


def _apply_dual_filters(
    nfr_result: RunResult,
    hygiene_result: RunResult,
    *,
    framework: str | None = None,
    origin: str | None = None,
    quiet: bool = False,
) -> tuple[RunResult, RunResult]:
    """Apply framework and/or origin filters to both NFR and hygiene results."""
    if framework is not None:
        nfr_filtered, nfr_excl = _apply_framework_filter(
            list(nfr_result.findings),
            framework,
        )
        hyg_filtered, hyg_excl = _apply_framework_filter(
            list(hygiene_result.findings),
            framework,
        )
        _ts_echo(
            f"Framework filter ({FRAMEWORK_LABELS[framework]}): "
            f"{len(nfr_filtered) + len(hyg_filtered)} mapped, "
            f"{nfr_excl + hyg_excl} excluded",
            quiet=quiet,
        )
        nfr_result = _with_findings(nfr_result, nfr_filtered)
        hygiene_result = _with_findings(hygiene_result, hyg_filtered)

    if origin is not None:
        from nfr_review.output.classify import filter_findings_by_origin

        origin_val: Origin = origin  # type: ignore[assignment]
        nfr_before = len(nfr_result.findings)
        hyg_before = len(hygiene_result.findings)
        nfr_origin = filter_findings_by_origin(list(nfr_result.findings), origin_val)
        hyg_origin = filter_findings_by_origin(list(hygiene_result.findings), origin_val)
        _ts_echo(
            f"Origin filter ({origin}): {len(nfr_origin) + len(hyg_origin)} kept, "
            f"{(nfr_before - len(nfr_origin)) + (hyg_before - len(hyg_origin))} excluded",
            quiet=quiet,
        )
        nfr_result = _with_findings(nfr_result, nfr_origin)
        hygiene_result = _with_findings(hygiene_result, hyg_origin)

    return nfr_result, hygiene_result


def run_report_pipeline(
    target: Path,
    *,
    output_dir: Path = Path("reports"),
    config_path: Path | None = None,
    no_tests: bool = False,
    no_deps: bool = False,
    no_diagrams: bool = False,
    pdf: bool = True,
    html: bool = False,
    no_summary: bool = False,
    test_timeout: int = 900,
    sarif_path: Path | None = None,
    show_score: bool = True,
    max_resolve_rounds: int | None = None,
    include_tests: bool = True,
    quiet: bool = False,
    stem: str | None = None,
    workers: int = 1,
    otel_traces: Path | None = None,
    collector: bool = False,
    framework: str | None = None,
    origin: str | None = None,
) -> ReportResult:
    """Run the full NFR + hygiene report pipeline and return structured results.

    This is the core pipeline extracted from the ``report`` CLI command so that
    callers (e.g. the ``all`` command) can invoke it without a Click context.
    """
    repo = _repo_name(target)
    phases, opts = _report_phases_and_opts(
        no_tests=no_tests,
        no_deps=no_deps,
        no_diagrams=no_diagrams,
        pdf=pdf,
        no_summary=no_summary,
        include_tests=include_tests,
        test_timeout=test_timeout,
    )
    _banner("report", repo, target, options=opts or None, phases=phases, quiet=quiet)

    config = _load_effective_config(config_path, quiet=quiet)
    config = _merge_repo_local_config(config, config_path, target)
    config, _detected = _detect_and_merge_tech(
        target,
        config,
        include_tests=include_tests,
        otel_traces_path=otel_traces,
        quiet=quiet,
    )

    collector_mgr = _create_collector_mgr(target, collector, quiet=quiet)
    nfr_result, hygiene_result = _run_scans(
        target,
        config,
        workers=workers,
        collector_mgr=collector_mgr,
        quiet=quiet,
    )

    nfr_result, hygiene_result = _apply_dual_filters(
        nfr_result,
        hygiene_result,
        framework=framework,
        origin=origin,
        quiet=quiet,
    )
    combined_findings = list(nfr_result.findings) + list(hygiene_result.findings)
    combined_result = RunResult(
        findings=combined_findings,
        rule_results=list(nfr_result.rule_results) + list(hygiene_result.rule_results),
        run_metadata=nfr_result.run_metadata,
        warnings=list(nfr_result.warnings) + list(hygiene_result.warnings),
    )

    merged_tech = config.tech
    sections = _build_report_sections(
        nfr_result=nfr_result,
        hygiene_result=hygiene_result,
        combined_findings=combined_findings,
        target=target,
        config=config,
        merged_tech=merged_tech,
        no_tests=no_tests,
        no_deps=no_deps,
        no_diagrams=no_diagrams,
        show_score=show_score,
        test_timeout=test_timeout,
        max_resolve_rounds=max_resolve_rounds,
        quiet=quiet,
    )

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    if stem is None:
        stem = f"{repo}-nfr-review-{timestamp}"

    return _write_outputs(
        nfr_result=nfr_result,
        hygiene_result=hygiene_result,
        combined_result=combined_result,
        sections=sections,
        output_dir=output_dir,
        stem=stem,
        sarif_path=sarif_path,
        html_flag=html,
        pdf_flag=pdf,
        no_summary=no_summary,
        quiet=quiet,
        framework=framework,
    )


@cli.command(
    "report",
    help="Run NFR + hygiene scans and produce a timestamped report. "
    "All features (PDF, score, test-path inclusion) are enabled by default; "
    "use --no-* / --exclude-* flags to opt out.",
)
@click.argument("target", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (-v for INFO, -vv for DEBUG).",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress warnings (ERROR level only).",
)
@click.option(
    "--log-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write diagnostics to FILE instead of stderr.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to nfr-review.yaml. Defaults to ./nfr-review.yaml if present.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("reports"),
    show_default=True,
    help="Directory where report files are written.",
)
@click.option(
    "--no-tests",
    is_flag=True,
    default=False,
    help="Skip pytest execution.",
)
@click.option(
    "--no-deps",
    is_flag=True,
    default=False,
    help="Skip dependency tree analysis.",
)
@click.option(
    "--no-diagrams",
    is_flag=True,
    default=False,
    help="Suppress Mermaid diagram sections in the report.",
)
@click.option(
    "--exclude-tests/--include-tests",
    default=True,
    help="Exclude test and fixture directories from analysis (default: exclude).",
)
@click.option(
    "--no-pdf",
    is_flag=True,
    default=False,
    help="Skip PDF report generation.",
)
@click.option(
    "--html",
    is_flag=True,
    default=False,
    help="Also produce a self-contained HTML report with interactive diagrams.",
)
@click.option(
    "--no-summary",
    is_flag=True,
    default=False,
    help="Skip LLM executive summary generation (PDF will omit summary section).",
)
@click.option(
    "--test-timeout",
    type=int,
    default=900,
    show_default=True,
    help="Maximum seconds to wait for pytest to complete.",
)
@click.option(
    "--sarif",
    "sarif_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output path for SARIF 2.1.0 findings file.",
)
@click.option(
    "--no-score",
    is_flag=True,
    default=False,
    help="Skip design maturity score computation.",
)
@click.option(
    "--max-resolve-rounds",
    type=int,
    default=None,
    help="Maximum resolver iterations for dependency analysis (default: 2000).",
)
@click.option(
    "--workers",
    type=int,
    default=1,
    show_default=True,
    help="Number of parallel collector threads (1 = sequential).",
)
@click.option(
    "--otel-traces",
    "otel_traces_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to an OTLP JSON/NDJSON trace file for Band 3 dynamic analysis.",
)
@click.option(
    "--collector/--no-collector",
    default=False,
    help="Start/stop an OTel Collector subprocess to capture traces during the scan.",
)
@click.option(
    "--framework",
    type=click.Choice(FRAMEWORK_SLUGS, case_sensitive=False),
    default=None,
    help="Filter findings to rules mapped to a compliance framework.",
)
@click.option(
    "--origin",
    type=click.Choice(["first_party", "dependency"], case_sensitive=False),
    default=None,
    help="Filter findings by origin: first_party (direct repo issues) or dependency.",
)
def report_cmd(
    target: Path,
    verbose: int,
    quiet: bool,
    log_file: Path | None,
    config_path: Path | None,
    output_dir: Path,
    no_tests: bool,
    no_deps: bool,
    no_diagrams: bool,
    exclude_tests: bool,
    no_pdf: bool,
    html: bool,
    no_summary: bool,
    test_timeout: int,
    sarif_path: Path | None = None,
    no_score: bool = False,
    max_resolve_rounds: int | None = None,
    workers: int = 1,
    otel_traces_path: Path | None = None,
    collector: bool = False,
    framework: str | None = None,
    origin: str | None = None,
) -> None:
    """Report command — run NFR + hygiene scans, optional pytest, emit report."""
    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    if collector and otel_traces_path is not None:
        raise click.UsageError("--collector and --otel-traces are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)

    from nfr_review.capabilities import detect_capabilities, log_capabilities

    log_capabilities(detect_capabilities())

    if not target.exists():
        click.echo(f"error: target does not exist: {target}", err=True)
        raise click.exceptions.Exit(1)
    if not target.is_dir():
        click.echo(f"error: target is not a directory: {target}", err=True)
        raise click.exceptions.Exit(1)

    run_report_pipeline(
        target,
        output_dir=output_dir,
        config_path=config_path,
        no_tests=no_tests,
        no_deps=no_deps,
        no_diagrams=no_diagrams,
        pdf=not no_pdf,
        html=html,
        no_summary=no_summary,
        test_timeout=test_timeout,
        sarif_path=sarif_path,
        show_score=not no_score,
        max_resolve_rounds=max_resolve_rounds,
        include_tests=not exclude_tests,
        quiet=quiet,
        workers=workers,
        otel_traces=otel_traces_path,
        collector=collector,
        framework=framework,
        origin=origin,
    )


def _write_dot_output(
    reports: list[Any], dot_path: Path | None, render_diagrams: bool
) -> None:
    """Write DOT graph and optionally render to SVG."""
    if not dot_path:
        if render_diagrams:
            click.echo("warning: --render-diagrams requires --dot <file>", err=True)
        return
    from nfr_review.output.dot import render_dot_dependency_graph

    dot_content = render_dot_dependency_graph(reports)
    try:
        dot_path.parent.mkdir(parents=True, exist_ok=True)
        dot_path.write_text(dot_content, encoding="utf-8")
        click.echo(f"DOT graph written to {dot_path}", err=True)
    except OSError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    if render_diagrams:
        from nfr_review.output.dot import render_dot_to_file

        rendered = render_dot_to_file(dot_content, str(dot_path))
        if rendered:
            click.echo(f"SVG rendered to {rendered}", err=True)
        else:
            click.echo(
                "info: graphviz not available — install with "
                "'pip install nfr-review[diagrams]' and ensure the "
                "'dot' binary is on PATH",
                err=True,
            )


def _write_deps_report(
    reports: list[Any],
    output_path: Path | None,
    render_section: Any,
    render_terminal: Any,
) -> None:
    """Write deps markdown report to file or print terminal summary."""
    if output_path:
        md_content = render_section(reports)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(md_content, encoding="utf-8")
            click.echo(f"deps report written to {output_path}", err=True)
        except OSError as exc:
            click.echo(f"error: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
    else:
        click.echo(render_terminal(reports))


@cli.command("deps", help="Analyze dependency tree and show upgrade recommendations.")
@click.argument("target", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (-v for INFO, -vv for DEBUG).",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress warnings (ERROR level only).",
)
@click.option(
    "--log-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write diagnostics to FILE instead of stderr.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to nfr-review.yaml. Defaults to ./nfr-review.yaml if present.",
)
@click.option(
    "--no-tree",
    is_flag=True,
    default=False,
    help="Skip transitive resolution and dependency tree (faster).",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write markdown report to FILE.",
)
@click.option(
    "--dot",
    "dot_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write Graphviz DOT dependency graph to FILE.",
)
@click.option(
    "--render-diagrams",
    is_flag=True,
    default=False,
    help="Render DOT graph to SVG (requires graphviz).",
)
@click.option(
    "--max-resolve-rounds",
    type=int,
    default=None,
    help="Maximum resolver iterations for dependency analysis (default: 2000).",
)
def deps_cmd(
    target: Path,
    verbose: int,
    quiet: bool,
    log_file: Path | None,
    config_path: Path | None,
    no_tree: bool,
    output_path: Path | None,
    dot_path: Path | None,
    render_diagrams: bool,
    max_resolve_rounds: int | None = None,
) -> None:
    """Analyze dependencies: upgrade summary table and transitive tree."""
    from nfr_review.deps_analysis import analyze_deps
    from nfr_review.output.deps_report import render_deps_section, render_deps_terminal

    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)
    _validate_target(target)

    repo = _repo_name(target)
    opts: dict[str, str] = {}
    if no_tree:
        opts["transitive"] = "skipped"
    _banner(
        "deps",
        repo,
        target,
        options=opts or None,
        phases=["config", "detect", "analyze"],
        quiet=quiet,
    )

    config = _load_effective_config(config_path, quiet=quiet)
    config, _detected = _detect_and_merge_tech(target, config, quiet=quiet)

    t0 = _phase("Analyzing dependencies", quiet=quiet)
    try:
        reports = analyze_deps(
            target,
            config,
            resolve_transitive=not no_tree,
            progress_callback=lambda msg: _ts_echo(msg),
            max_resolve_rounds=max_resolve_rounds,
        )
    except Exception as exc:  # noqa: BLE001
        click.echo(f"error: dependency analysis failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("Dependency analysis", t0, quiet=quiet)

    _write_dot_output(reports, dot_path, render_diagrams)
    _write_deps_report(reports, output_path, render_deps_section, render_deps_terminal)
    total_deps = sum(len(r.upgrades) for r in reports)
    _ts_echo(f"nfr-review deps: ecosystems={len(reports)} dependencies={total_deps}")


# nfr-review:skip(python-dormant-classes) reason: used by @cli.group(cls=_IssuesGroup)
class _IssuesGroup(click.Group):
    """Issues group that falls back to 'scan' subcommand for backward compat.

    ``nfr-review issues <dir>`` is rewritten to ``nfr-review issues scan <dir>``
    so the old CLI keeps working after the command was promoted to a group.
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args:
            positional = [a for a in args if not a.startswith("-")]
            has_subcommand = any(a in self.commands for a in positional)
            if not has_subcommand and positional:
                args = ["scan", *args]
        return super().parse_args(ctx, args)


@cli.group(
    "issues",
    cls=_IssuesGroup,
    help="File or sync GitHub issues for NFR findings.",
)
def issues_group() -> None:
    """Issue management group."""


def _resolve_gh_repo(repo: str | None, target: Path, dry_run: bool) -> str | None:
    """Resolve GitHub owner/repo from git remote if not supplied."""
    if repo is not None or dry_run:
        return repo
    import subprocess  # nosec B404

    try:
        gh_result = subprocess.run(  # nosec B603 B607
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(target),
            check=False,
        )
        if gh_result.returncode == 0 and gh_result.stdout.strip():
            return gh_result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    click.echo(
        "error: could not detect GitHub repo — pass --repo owner/repo or use --dry-run",
        err=True,
    )
    raise click.exceptions.Exit(1)


def _file_and_report_issues(
    finding_dicts: list[dict[str, Any]],
    repo: str,
    *,
    dry_run: bool,
    severity_threshold: str,
    quiet: bool = False,
) -> None:
    """File or preview GitHub issues and print summary."""
    from nfr_review.issues import file_issues

    _phase("Filing issues" if not dry_run else "Previewing issues", quiet=quiet)
    issue_results = file_issues(
        finding_dicts,
        repo,
        dry_run=dry_run,
        severity_threshold=severity_threshold,
    )

    filed = sum(1 for r in issue_results if r["status"] == "filed")
    skipped = sum(1 for r in issue_results if r["status"] == "skipped")
    dry_count = sum(1 for r in issue_results if r["status"] == "dry_run")
    errors = sum(1 for r in issue_results if r["status"] == "error")

    for r in issue_results:
        url = f" {r['url']}" if r.get("url") else ""
        _ts_echo(f"  [{r['status']}] {r['title']}{url}")

    if dry_run:
        _ts_echo(f"dry run: {dry_count} issue(s) would be filed")
    else:
        _ts_echo(f"filed={filed} skipped={skipped} errors={errors}")


@issues_group.command(
    "scan",
    help="Run an NFR scan and file issues for red/high-severity findings (original behavior).",
)
@click.argument("target", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview issues without filing to GitHub.",
)
@click.option(
    "--repo",
    default=None,
    help="GitHub owner/repo (e.g. org/repo). Auto-detected from git remote if omitted.",
)
@click.option(
    "--severity-threshold",
    type=click.Choice(["critical", "high", "medium", "low", "info"]),
    default="high",
    show_default=True,
    help="Minimum severity for filing issues.",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (-v for INFO, -vv for DEBUG).",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress warnings (ERROR level only).",
)
@click.option(
    "--log-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write diagnostics to FILE instead of stderr.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to nfr-review.yaml. Defaults to ./nfr-review.yaml if present.",
)
def issues_scan_cmd(
    target: Path,
    dry_run: bool,
    repo: str | None,
    severity_threshold: str,
    verbose: int,
    quiet: bool,
    log_file: Path | None,
    config_path: Path | None,
) -> None:
    """Run an NFR scan and file GitHub issues for red/high-severity findings."""
    from nfr_review.issues import filter_findings

    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)
    _validate_target(target)

    repo = _resolve_gh_repo(repo, target, dry_run)
    repo_name = _repo_name(target)
    _banner(
        "issues",
        repo_name,
        target,
        options={"dry_run": str(dry_run), "threshold": severity_threshold},
        phases=["config", "detect", "scan", "issues"],
        quiet=quiet,
    )

    config = _load_effective_config(config_path, quiet=quiet)
    config, _detected = _detect_and_merge_tech(target, config, quiet=quiet)

    t0 = _phase("Running NFR scan", quiet=quiet)
    try:
        result = Engine().run(target, config)
    except EngineError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("NFR scan", t0, quiet=quiet)

    finding_dicts = [f.model_dump() for f in result.findings]
    filtered = filter_findings(finding_dicts, severity_threshold)
    if not filtered:
        _ts_echo(f"No findings at severity >= {severity_threshold} — nothing to file.")
        return
    _ts_echo(f"Found {len(filtered)} findings at severity >= {severity_threshold}")

    _file_and_report_issues(
        finding_dicts,
        repo or "",
        dry_run=dry_run,
        severity_threshold=severity_threshold,
        quiet=quiet,
    )


@issues_group.command(
    "sync",
    help="Sync GitHub issues from a JSONL scan file: create, update, and close.",
)
@click.argument(
    "jsonl_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--repo",
    default=None,
    help="GitHub owner/repo (e.g. org/repo). Required unless --dry-run.",
)
@click.option(
    "--extra-labels",
    "extra_labels",
    default=None,
    help="Comma-separated extra labels to apply (e.g. 'team:platform,sprint:23').",
)
@click.option(
    "--rag-min",
    type=click.Choice(["red", "amber", "green"]),
    default="amber",
    show_default=True,
    help="Minimum RAG level for filing issues.",
)
@click.option(
    "--severity-threshold",
    type=click.Choice(["critical", "high", "medium", "low", "info"]),
    default="high",
    show_default=True,
    help="Minimum severity for filing issues.",
)
@click.option(
    "--first-run-cap",
    type=int,
    default=25,
    show_default=True,
    help="Max issues to create when no prior nfr-review issues exist.",
)
@click.option(
    "--close-resolved/--no-close-resolved",
    default=True,
    show_default=True,
    help="Close open issues whose findings are no longer present.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview create/update/close decisions without calling GitHub.",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (-v for INFO, -vv for DEBUG).",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress warnings (ERROR level only).",
)
def _load_jsonl_findings(jsonl_path: Path) -> list[dict[str, Any]]:
    """Load finding records from a JSONL scan file."""
    import json as _json

    findings: list[dict[str, Any]] = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = _json.loads(line)
            if rec.get("record_type") == "finding":
                findings.append(rec)
    return findings


def _print_sync_summary(results: list[dict[str, Any]], *, quiet: bool = False) -> None:
    """Print per-action detail and totals for issue sync results."""
    created = updated = closed = skipped = unchanged = errors = 0
    for r in results:
        action = r["action"]
        url = f" {r['url']}" if r.get("url") else ""
        reason = f" ({r['reason']})" if r.get("reason") else ""
        _ts_echo(f"  [{action}] {r['title']}{url}{reason}", quiet=quiet)
        if action == "create":
            created += 1
        elif action == "update":
            updated += 1
        elif action == "close":
            closed += 1
        elif action == "skip":
            skipped += 1
        elif action == "unchanged":
            unchanged += 1
        elif action == "error":
            errors += 1

    _ts_echo(
        f"sync: created={created} updated={updated} closed={closed} "
        f"skipped={skipped} unchanged={unchanged} errors={errors}",
        quiet=quiet,
    )


def issues_sync_cmd(
    jsonl_path: Path,
    repo: str | None,
    extra_labels: str | None,
    rag_min: str,
    severity_threshold: str,
    first_run_cap: int,
    close_resolved: bool,
    dry_run: bool,
    verbose: int,
    quiet: bool,
) -> None:
    """Sync GitHub issues from a JSONL scan file."""
    from nfr_review.issues import sync_issues

    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    if not dry_run and not repo:
        raise click.UsageError("--repo is required unless --dry-run is set")
    _configure_logging(verbose, quiet, None)

    findings = _load_jsonl_findings(jsonl_path)
    _ts_echo(
        f"Loaded {len(findings)} findings from {jsonl_path}",
        quiet=quiet,
    )

    label_list: list[str] | None = None
    if extra_labels:
        label_list = [lbl.strip() for lbl in extra_labels.split(",") if lbl.strip()]

    results = sync_issues(
        findings,
        repo or "",
        dry_run=dry_run,
        rag_min=rag_min,
        severity_threshold=severity_threshold,
        extra_labels=label_list,
        first_run_cap=first_run_cap,
        close_resolved=close_resolved,
    )

    _print_sync_summary(results, quiet=quiet)


@cli.command("init", help="Detect technologies and generate an nfr-review.yaml config.")
@click.argument("target", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print generated config to stdout instead of writing a file.",
)
def init_cmd(target: Path, dry_run: bool) -> None:
    """Detect technologies in TARGET and write an nfr-review.yaml config."""
    if not target.exists():
        click.echo(f"error: target does not exist: {target}", err=True)
        raise click.exceptions.Exit(1)
    if not target.is_dir():
        click.echo(f"error: target is not a directory: {target}", err=True)
        raise click.exceptions.Exit(1)

    click.echo("Detecting technologies...", err=True)
    try:
        detected = detect_technologies(target)
    except Exception as e:  # noqa: BLE001
        click.echo(f"error: technology detection failed: {e}", err=True)
        raise click.exceptions.Exit(1) from e

    active_tech = {k: True for k, v in detected.items() if v}

    config_data: dict[str, Any] = {"version": 1}
    if active_tech:
        config_data["tech"] = active_tech

    from io import StringIO

    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.default_flow_style = False
    buf = StringIO()
    yaml.dump(config_data, buf)
    yaml_text = buf.getvalue()

    if dry_run:
        click.echo(yaml_text, nl=False)
    else:
        out_path = target / "nfr-review.yaml"
        out_path.write_text(yaml_text, encoding="utf-8")
        click.echo(f"Wrote {out_path}", err=True)

    # Summary of detected technologies
    if active_tech:
        click.echo(
            f"Detected: {', '.join(sorted(active_tech.keys()))}",
            err=True,
        )
    else:
        click.echo("No technologies detected.", err=True)


def _banner_arch(
    target_list: list[Path],
    repo_names: list[str],
    no_llm: bool,
    output_formats: tuple[str, ...],
    evidence_dir: Path | None,
    quiet: bool,
) -> None:
    """Print the arch command banner."""
    primary_repo = repo_names[0] if repo_names else "unknown"
    opts: dict[str, str] = {}
    if no_llm:
        opts["llm"] = "skipped"
    if len(target_list) > 1:
        opts["repos"] = str(len(target_list))
    if output_formats:
        opts["formats"] = ",".join(output_formats)
    phases = ["discover", "integrate", "coverage", "diagrams", "risks"]
    if not no_llm:
        phases.extend(["domain-model", "market"])
    phases.extend(["recommend", "output"])
    if evidence_dir:
        phases.insert(0, "evidence")
    _banner(
        "arch", primary_repo, target_list[0], options=opts or None, phases=phases, quiet=quiet
    )


@cli.command(
    "arch",
    help=(
        "[EXPERIMENTAL] Generate architecture documentation for TARGET"
        " repository/repositories."
    ),
    epilog="This command is experimental and its output format may change.",
)
@click.argument(
    "targets",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (-v for INFO, -vv for DEBUG).",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress warnings (ERROR level only).",
)
@click.option(
    "--log-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write diagnostics to FILE instead of stderr.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("reports"),
    show_default=True,
    help="Directory where report files are written.",
)
@click.option(
    "--format",
    "output_formats",
    multiple=True,
    type=click.Choice(["json", "md", "pdf", "dsl"]),
    help="Output format(s). Repeat for multiple. Default: json + md + pdf.",
)
@click.option(
    "--no-llm",
    is_flag=True,
    default=False,
    help="Skip LLM-based analysis (domain model enhancement, market comparison).",
)
@click.option(
    "--diagram-mode",
    type=click.Choice(["hierarchical", "flat"]),
    default="hierarchical",
    show_default=True,
    help="Component diagram layout: hierarchical (overview + detail) or flat.",
)
@click.option(
    "--evidence-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Directory containing evidence JSONL files (e.g. OTel traces).",
)
def arch_cmd(
    targets: tuple[Path, ...],
    verbose: int,
    quiet: bool,
    log_file: Path | None,
    output_dir: Path,
    output_formats: tuple[str, ...],
    no_llm: bool,
    diagram_mode: str,
    evidence_dir: Path | None,
) -> None:
    """Generate architecture documentation report."""
    from nfr_review.arch_orchestrator import run_arch_review
    from nfr_review.arch_report_render import render_arch_report

    click.echo("WARNING: The arch command is experimental and subject to change.", err=True)
    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)

    target_list = list(targets)
    repo_names = [_repo_name(t) for t in target_list]
    _banner_arch(target_list, repo_names, no_llm, output_formats, evidence_dir, quiet)

    evidence_list = None
    if evidence_dir:
        evidence_list = _load_evidence_from_dir(evidence_dir)
        _ts_echo(
            f"[evidence] Loaded {len(evidence_list)} evidence items from {evidence_dir}",
            quiet=quiet,
        )

    t0 = _phase("Running architecture review", quiet=quiet)
    try:
        report = run_arch_review(
            target_list,
            repo_names=repo_names,
            skip_llm=no_llm,
            diagram_mode=diagram_mode,
            evidence=evidence_list,
            progress=lambda msg: _ts_echo(msg, quiet=quiet),
        )
    except Exception as exc:  # noqa: BLE001
        click.echo(f"error: architecture review failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("Architecture review", t0, quiet=quiet)

    t0 = _phase("Rendering output files", quiet=quiet)
    try:
        results = render_arch_report(report, output_dir, formats=list(output_formats) or None)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"error: report rendering failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("Output rendering", t0, quiet=quiet)

    produced = {k: v for k, v in results.items() if v is not None}
    parts = [
        f"nfr-review arch: components={len(report.components)}",
        f"integrations={len(report.integration_points)}",
        f"risks={len(report.risk_findings)}",
        f"recommendations={len(report.recommendations)}",
        f"files_emitted={len(produced)}",
    ]
    for fmt, path in produced.items():
        parts.append(f"{fmt}={path}")
    _ts_echo(" ".join(parts))


def _warn_llm_cost(no_arch: bool, no_llm: bool, quiet: bool) -> None:
    """Warn about LLM cost if architecture analysis will use LLM calls."""
    if no_arch or no_llm or quiet:
        return
    from nfr_review.llm_client import create_llm_client

    if create_llm_client().available:
        click.echo(
            "NOTE: Architecture analysis uses LLM calls which may incur "
            "cost and take significant time.\n"
            "      Use --no-arch to skip architecture analysis entirely, "
            "or --no-llm to run without LLM features.",
            err=True,
        )
        click.echo("", err=True)


def _execute_all_pipelines(  # noqa: PLR0913
    *,
    target_list: list[Path],
    repo_names: list[str],
    timestamp: str,
    output_dir: Path,
    config_path: Path | None,
    no_arch: bool,
    no_tests: bool,
    no_deps: bool,
    no_diagrams: bool,
    no_pdf: bool,
    no_summary: bool,
    test_timeout: int,
    no_score: bool,
    max_resolve_rounds: int | None,
    no_llm: bool,
    diagram_mode: str,
    exclude_tests: bool,
    workers: int,
    quiet: bool,
) -> tuple[dict[str, Any] | None, list[tuple[str, ReportResult]]]:
    """Run arch review + NFR reports, concurrently when workers > 1."""

    def _run_arch() -> dict[str, Any]:
        from nfr_review.arch_orchestrator import run_arch_review
        from nfr_review.arch_report_render import render_arch_report

        t0 = _phase("Running architecture review (all targets)", quiet=quiet)
        report = run_arch_review(
            target_list,
            repo_names=repo_names,
            skip_llm=no_llm,
            diagram_mode=diagram_mode,
            progress=lambda msg: _ts_echo(msg, quiet=quiet),
        )
        _phase_done("Architecture review", t0, quiet=quiet)

        t0 = _phase("Rendering architecture output", quiet=quiet)
        arch_files = render_arch_report(report, output_dir, formats=None)
        _phase_done("Architecture output", t0, quiet=quiet)

        return {
            "components": len(report.components),
            "integrations": len(report.integration_points),
            "risks": len(report.risk_findings),
            "recommendations": len(report.recommendations),
            "files": {k: v for k, v in arch_files.items() if v is not None},
        }

    def _run_nfr_reports() -> list[tuple[str, ReportResult]]:
        results: list[tuple[str, ReportResult]] = []
        for t, repo in zip(target_list, repo_names, strict=True):
            if not quiet:
                click.echo("", err=True)
            _phase(f"Running NFR report for {repo}", quiet=quiet)
            rr = run_report_pipeline(
                t,
                output_dir=output_dir,
                config_path=config_path,
                no_tests=no_tests,
                no_deps=no_deps,
                no_diagrams=no_diagrams,
                pdf=not no_pdf,
                no_summary=no_summary,
                test_timeout=test_timeout,
                show_score=not no_score,
                max_resolve_rounds=max_resolve_rounds,
                include_tests=not exclude_tests,
                quiet=quiet,
                stem=f"{repo}-nfr-review-{timestamp}",
                workers=workers,
            )
            results.append((repo, rr))
        return results

    arch_result: dict[str, Any] | None = None
    if not no_arch and workers > 1:
        from concurrent.futures import ThreadPoolExecutor

        _phase("Running arch + NFR pipelines concurrently", quiet=quiet)
        with ThreadPoolExecutor(max_workers=2) as pool:
            arch_future = pool.submit(_run_arch)
            nfr_future = pool.submit(_run_nfr_reports)
            try:
                arch_result = arch_future.result()
            except Exception as exc:  # noqa: BLE001
                click.echo(f"error: architecture review failed: {exc}", err=True)
                raise click.exceptions.Exit(1) from exc
            try:
                report_results = nfr_future.result()
            except Exception as exc:  # noqa: BLE001
                click.echo(f"error: NFR report failed: {exc}", err=True)
                raise click.exceptions.Exit(1) from exc
    else:
        if not no_arch:
            try:
                arch_result = _run_arch()
            except Exception as exc:  # noqa: BLE001
                click.echo(f"error: architecture review failed: {exc}", err=True)
                raise click.exceptions.Exit(1) from exc
        report_results = _run_nfr_reports()
    return arch_result, report_results


def _print_all_summary(
    arch_result: dict[str, Any] | None,
    report_results: list[tuple[str, ReportResult]],
    *,
    quiet: bool = False,
) -> None:
    """Print the combined summary for the 'all' command."""
    if not quiet:
        click.echo("", err=True)
    click.echo("=" * 60, err=True)
    _ts_echo("nfr-review all — complete")
    if arch_result:
        _ts_echo(
            f"  arch: components={arch_result['components']} "
            f"integrations={arch_result['integrations']} "
            f"risks={arch_result['risks']} "
            f"recommendations={arch_result['recommendations']}"
        )
        for fmt, path in arch_result["files"].items():
            _ts_echo(f"    {fmt}={path}")
    for repo, rr in report_results:
        _ts_echo(
            f"  {repo}: findings={rr.total_findings} "
            f"(nfr={rr.nfr_count} hygiene={rr.hygiene_count})"
        )
        _ts_echo(f"    md={rr.md_path} csv={rr.csv_path}")
        if rr.pdf_path:
            _ts_echo(f"    pdf={rr.pdf_path}")
    click.echo("=" * 60, err=True)


@cli.command(
    "all",
    help="Run architecture review (cross-repo) + NFR report (per-repo) in one go. "
    "Accepts one or more target directories.",
)
@click.argument(
    "targets",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (-v for INFO, -vv for DEBUG).",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress warnings (ERROR level only).",
)
@click.option(
    "--log-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write diagnostics to FILE instead of stderr.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("reports"),
    show_default=True,
    help="Directory where all output files are written.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to nfr-review.yaml (used for each NFR report). "
    "Defaults to per-repo auto-detection.",
)
@click.option("--no-arch", is_flag=True, default=False, help="Skip the architecture report.")
@click.option("--no-tests", is_flag=True, default=False, help="Skip pytest execution.")
@click.option("--no-deps", is_flag=True, default=False, help="Skip dependency tree analysis.")
@click.option(
    "--no-diagrams",
    is_flag=True,
    default=False,
    help="Suppress Mermaid diagram sections in NFR reports.",
)
@click.option("--no-pdf", is_flag=True, default=False, help="Skip PDF report generation.")
@click.option(
    "--no-summary",
    is_flag=True,
    default=False,
    help="Skip LLM executive summary generation.",
)
@click.option(
    "--test-timeout",
    type=int,
    default=900,
    show_default=True,
    help="Maximum seconds to wait for pytest per repo.",
)
@click.option(
    "--no-score",
    is_flag=True,
    default=False,
    help="Skip design maturity score computation.",
)
@click.option(
    "--max-resolve-rounds",
    type=int,
    default=None,
    help="Maximum resolver iterations for dependency analysis.",
)
@click.option(
    "--no-llm",
    is_flag=True,
    default=False,
    help="Skip LLM-based analysis in architecture report.",
)
@click.option(
    "--diagram-mode",
    type=click.Choice(["hierarchical", "flat"]),
    default="hierarchical",
    show_default=True,
    help="Architecture diagram layout.",
)
@click.option(
    "--exclude-tests/--include-tests",
    default=True,
    help="Exclude test and fixture directories from NFR analysis (default: exclude).",
)
@click.option(
    "--workers",
    type=int,
    default=1,
    show_default=True,
    help="Number of parallel collector threads (1 = sequential).",
)
def all_cmd(
    targets: tuple[Path, ...],
    verbose: int,
    quiet: bool,
    log_file: Path | None,
    output_dir: Path,
    config_path: Path | None,
    no_arch: bool,
    no_tests: bool,
    no_deps: bool,
    no_diagrams: bool,
    no_pdf: bool,
    no_summary: bool,
    test_timeout: int,
    no_score: bool,
    max_resolve_rounds: int | None,
    no_llm: bool,
    diagram_mode: str,
    exclude_tests: bool,
    workers: int = 1,
) -> None:
    """Run architecture review across all targets, then NFR report per target."""
    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)

    target_list = list(targets)
    repo_names = [_repo_name(t) for t in target_list]
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")

    if not quiet:
        click.echo(f"\nnfr-review all v{__version__}", err=True)
        click.echo(f"Targets:    {', '.join(str(t) for t in target_list)}", err=True)
        click.echo(f"Started:    {_timestamp()}", err=True)
        click.echo("", err=True)

    _warn_llm_cost(no_arch, no_llm, quiet)
    output_dir.mkdir(parents=True, exist_ok=True)

    arch_result, report_results = _execute_all_pipelines(
        target_list=target_list,
        repo_names=repo_names,
        timestamp=timestamp,
        output_dir=output_dir,
        config_path=config_path,
        no_arch=no_arch,
        no_tests=no_tests,
        no_deps=no_deps,
        no_diagrams=no_diagrams,
        no_pdf=no_pdf,
        no_summary=no_summary,
        test_timeout=test_timeout,
        no_score=no_score,
        max_resolve_rounds=max_resolve_rounds,
        no_llm=no_llm,
        diagram_mode=diagram_mode,
        exclude_tests=exclude_tests,
        workers=workers,
        quiet=quiet,
    )
    _print_all_summary(arch_result, report_results, quiet=quiet)


@cli.group("baseline", help="Manage interaction baselines for production monitoring.")
def baseline_group() -> None:
    """Interaction baseline management."""


@baseline_group.command("create", help="Create an interaction baseline from OTel trace data.")
@click.option(
    "--otel-traces",
    "otel_traces_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to an OTLP JSON/NDJSON trace file.",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output path for the baseline JSON file.",
)
def baseline_create_cmd(otel_traces_path: Path, output_path: Path) -> None:
    """Extract interaction fingerprints from OTel traces and write a baseline file."""
    from nfr_review.collectors.otel_trace import _parse_otlp_file
    from nfr_review.monitor.baseline import InteractionBaseline, save_baseline
    from nfr_review.monitor.fingerprint import extract_fingerprints

    try:
        text = otel_traces_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise click.ClickException(f"cannot read trace file: {exc}") from exc

    spans = _parse_otlp_file(text)
    if not spans:
        raise click.ClickException("no spans found in trace file")

    fingerprints = extract_fingerprints(spans)
    trace_ids = {s.trace_id for s in spans if s.trace_id}
    services = {s.service_name for s in spans if s.service_name}

    baseline = InteractionBaseline(
        source=str(otel_traces_path),
        trace_count=len(trace_ids),
        span_count=len(spans),
        fingerprints=sorted(fingerprints, key=lambda fp: fp.fingerprint_hash),
    )
    save_baseline(baseline, output_path)

    click.echo(
        f"Baseline created: {len(fingerprints)} fingerprints "
        f"from {len(trace_ids)} traces across {len(services)} services",
        err=True,
    )
    click.echo(str(output_path))


def _render_baseline_diff(
    findings: list[Any],
    baseline: Any,
    otel_traces_path: Path,
    observed: set[Any] | list[Any],
    fmt: str,
) -> str:
    """Render baseline diff findings as JSON or Markdown."""
    novel_count = sum(1 for f in findings if f.rule_id == "mon-novel-interaction")
    disappeared_count = sum(1 for f in findings if f.rule_id == "mon-disappeared-interaction")

    if fmt == "json":
        lines = [f.model_dump_json() for f in findings]
        return "\n".join(lines) + ("\n" if lines else "")

    parts = ["# Baseline Diff Report\n"]
    parts.append(f"Baseline: {baseline.source} ({len(baseline.fingerprints)} fingerprints)\n")
    parts.append(f"Observed: {otel_traces_path} ({len(observed)} fingerprints)\n")
    if novel_count:
        parts.append(f"\n## Novel Interactions ({novel_count})\n")
        for f in findings:
            if f.rule_id == "mon-novel-interaction":
                parts.append(f"- **{f.severity}**: {f.summary}\n")
    if disappeared_count:
        parts.append(f"\n## Disappeared Interactions ({disappeared_count})\n")
        for f in findings:
            if f.rule_id == "mon-disappeared-interaction":
                parts.append(f"- {f.summary}\n")
    if not findings:
        parts.append("\nNo differences found — production matches UAT baseline.\n")
    return "\n".join(parts)


@baseline_group.command("diff", help="Compare production traces against a UAT baseline.")
@click.option(
    "--baseline",
    "baseline_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a baseline JSON file (from `baseline create`).",
)
@click.option(
    "--otel-traces",
    "otel_traces_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to an OTLP JSON/NDJSON trace file to compare.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["md", "json"]),
    default="md",
    show_default=True,
    help="Output format: md (Markdown summary) or json (JSONL findings).",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output file (default: stdout).",
)
def baseline_diff_cmd(
    baseline_path: Path,
    otel_traces_path: Path,
    fmt: str,
    output_path: Path | None,
) -> None:
    """Diff production traces against a UAT baseline and emit findings."""
    from nfr_review.collectors.otel_trace import _parse_otlp_file
    from nfr_review.monitor.baseline import load_baseline as load_interaction_baseline
    from nfr_review.monitor.diff import generate_diff_findings
    from nfr_review.monitor.fingerprint import extract_fingerprints

    baseline = load_interaction_baseline(baseline_path)

    try:
        text = otel_traces_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise click.ClickException(f"cannot read trace file: {exc}") from exc

    spans = _parse_otlp_file(text)
    if not spans:
        raise click.ClickException("no spans found in trace file")

    observed = extract_fingerprints(spans)
    findings = generate_diff_findings(baseline, observed)

    novel_count = sum(1 for f in findings if f.rule_id == "mon-novel-interaction")
    disappeared_count = sum(1 for f in findings if f.rule_id == "mon-disappeared-interaction")
    click.echo(
        f"Diff: {novel_count} novel, {disappeared_count} disappeared, "
        f"{len(observed)} total observed fingerprints",
        err=True,
    )

    content = _render_baseline_diff(findings, baseline, otel_traces_path, observed, fmt)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        click.echo(str(output_path))
    else:
        click.echo(content, nl=False)


@cli.command(
    "monitor", help="Run a live production monitor comparing traces against a UAT baseline."
)
@click.option(
    "--baseline",
    "baseline_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a baseline JSON file (from `baseline create`).",
)
@click.option(
    "--port",
    type=int,
    default=4318,
    show_default=True,
    help="Port for the OTLP HTTP receiver.",
)
@click.option(
    "--host",
    type=str,
    default="0.0.0.0",  # nosec B104
    show_default=True,
    help="Host to bind the OTLP HTTP receiver.",
)
@click.option(
    "--window-seconds",
    type=float,
    default=60.0,
    show_default=True,
    help="Time window in seconds for grouping spans before comparison.",
)
def monitor_cmd(
    baseline_path: Path,
    port: int,
    host: str,
    window_seconds: float,
) -> None:
    """Start a long-lived OTLP HTTP receiver that compares production
    traces against a UAT baseline and emits JSON alerts for novel
    interactions to stdout.
    """
    try:
        from nfr_review.monitor.engine import MonitorConfig, MonitorEngine
    except ImportError as err:
        raise click.ClickException(
            "monitor requires the [monitor] extra: pip install nfr-review[monitor]"
        ) from err

    import asyncio

    config = MonitorConfig(
        baseline_path=baseline_path,
        host=host,
        port=port,
        window_seconds=window_seconds,
    )
    engine = MonitorEngine(config)

    click.echo(
        f"Starting monitor on {host}:{port} "
        f"(window={window_seconds}s, baseline={baseline_path})",
        err=True,
    )
    asyncio.run(engine.run())


def _load_evidence_from_dir(evidence_dir: Path) -> list:
    """Load Evidence objects from JSONL files in a directory."""
    import json as _json

    from nfr_review.models import Evidence

    logger = logging.getLogger(__name__)
    items: list = []
    for jsonl_file in sorted(evidence_dir.glob("*.jsonl")):
        for line in jsonl_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = _json.loads(line)
                items.append(Evidence.model_validate(data))
            except Exception:  # noqa: BLE001
                logger.debug("Skipping unparseable JSONL line in %s", jsonl_file)
    for json_file in sorted(evidence_dir.glob("*.json")):
        try:
            data = _json.loads(json_file.read_text())
            if isinstance(data, list):
                for item in data:
                    items.append(Evidence.model_validate(item))
            elif isinstance(data, dict):
                items.append(Evidence.model_validate(data))
        except Exception:  # noqa: BLE001
            logger.debug("Skipping unparseable JSON file %s", json_file)
    return items


@cli.command(
    "experimental",
    help=(
        "[DEPRECATED] Use 'arch' instead.  Generates a class-diagram-focused"
        " report for TARGET repository/repositories."
    ),
    epilog="Deprecated: use 'nfr-review arch' which now includes class diagrams.",
    deprecated=True,
)
@click.argument(
    "targets",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (-v for INFO, -vv for DEBUG).",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress warnings (ERROR level only).",
)
@click.option(
    "--log-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write diagnostics to FILE instead of stderr.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("reports"),
    show_default=True,
    help="Directory where report files are written.",
)
@click.option(
    "--format",
    "output_formats",
    multiple=True,
    type=click.Choice(["json", "md", "both"]),
    help="Output format(s). Repeat for multiple. Default: both (json + md).",
)
@click.option(
    "--evidence-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Directory containing evidence JSONL files (e.g. OTel traces).",
)
def experimental_cmd(
    targets: tuple[Path, ...],
    verbose: int,
    quiet: bool,
    log_file: Path | None,
    output_dir: Path,
    output_formats: tuple[str, ...],
    evidence_dir: Path | None,
) -> None:
    """Generate an experimental class-diagram-focused report.

    .. deprecated::
        Use ``nfr-review arch`` instead.  The arch command now includes
        class diagrams, cross-repo edge detection, and OTel dynamic analysis.
    """
    click.echo(
        "WARNING: 'experimental' is deprecated — use 'nfr-review arch' instead. "
        "All experimental features are now part of the arch command.",
        err=True,
    )

    # Translate formats: experimental used "both" => json+md
    arch_formats: tuple[str, ...] = ()
    if output_formats:
        fmt_set: set[str] = set()
        for f in output_formats:
            if f == "both":
                fmt_set.update(("json", "md"))
            else:
                fmt_set.add(f)
        arch_formats = tuple(sorted(fmt_set))

    # Delegate to the arch command via its click context
    ctx = click.get_current_context()
    ctx.invoke(
        arch_cmd,
        targets=targets,
        verbose=verbose,
        quiet=quiet,
        log_file=log_file,
        output_dir=output_dir,
        output_formats=arch_formats,
        no_llm=True,
        diagram_mode="hierarchical",
        evidence_dir=evidence_dir,
    )


@cli.command("version", help="Print the nfr-review version and exit.")
def version_cmd() -> None:
    """Print version."""
    click.echo(__version__)


__all__ = ["ReportResult", "_DedupFilter", "_configure_logging", "cli", "run_report_pipeline"]


if __name__ == "__main__":
    cli()
