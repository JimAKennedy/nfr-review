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
from nfr_review.config import Config, ConfigError, load_config
from nfr_review.detect import detect_technologies
from nfr_review.engine import Engine, EngineError, RunResult
from nfr_review.hygiene import hygiene_collector_registry, hygiene_rule_registry
from nfr_review.models import Severity
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
    total_findings: int
    nfr_count: int
    hygiene_count: int


_SEVERITY_ORDER: tuple[Severity, ...] = ("info", "low", "medium", "high", "critical")


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
) -> None:
    """Run command — load config, run engine, emit CSV+JSONL, print summary."""
    include_tests = not exclude_tests
    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)

    from nfr_review.tracing import init_tracing

    init_tracing()

    repo = _repo_name(target)
    if csv_path is None:
        csv_path = Path(f"{repo}-nfr-review.csv")
    if jsonl_path is None:
        jsonl_path = Path(f"{repo}-nfr-review.jsonl")
    if not target.exists():
        click.echo(f"error: target does not exist: {target}", err=True)
        raise click.exceptions.Exit(1)
    if not target.is_dir():
        click.echo(f"error: target is not a directory: {target}", err=True)
        raise click.exceptions.Exit(1)

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

    run_logger = logging.getLogger("nfr_review")

    t0 = _phase("Loading configuration", quiet=quiet)
    effective_config_path = config_path
    if effective_config_path is None:
        default = Path("nfr-review.yaml")
        if default.exists():
            effective_config_path = default

    run_logger.info("Loading config from %s", effective_config_path or "(defaults)")
    try:
        config: Config = load_config(effective_config_path)
    except ConfigError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    t0 = _phase("Detecting technologies", quiet=quiet)
    run_logger.info("Detecting technologies in %s", target)
    try:
        detected = detect_technologies(target)
    except Exception as e:  # noqa: BLE001
        logger.debug("Technology detection failed for %s: %s", target, e)
        detected = {}
    merged_tech = {**detected, **config.tech}
    updates: dict[str, Any] = {"tech": merged_tech, "exclude_test_paths": not include_tests}
    if otel_traces_path is not None:
        updates["otel_traces"] = otel_traces_path
    config = config.model_copy(update=updates)
    tech_detected = sum(1 for v in detected.values() if v)
    active_tech = [k for k, v in merged_tech.items() if v]
    if active_tech:
        _ts_echo(f"Technologies: {', '.join(sorted(active_tech))}", quiet=quiet)

    t0 = _phase("Running NFR scan (collect + evaluate)", quiet=quiet)
    run_logger.info("Starting NFR engine scan")
    try:
        result = Engine(workers=workers).run(target, config)
    except EngineError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("NFR scan", t0, quiet=quiet)

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
        result = RunResult(
            findings=active_findings,
            rule_results=result.rule_results,
            run_metadata=result.run_metadata,
            warnings=result.warnings,
            evidence=result.evidence,
        )

    classification = None
    if baseline_path is not None:
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
        result = RunResult(
            findings=new_findings,
            rule_results=result.rule_results,
            run_metadata=result.run_metadata,
            warnings=result.warnings,
            evidence=result.evidence,
        )

    if show_score:
        from nfr_review.scoring import (
            compute_maturity_score,
            compute_trend,
            load_baseline_score,
        )

        score = compute_maturity_score(
            result.findings,
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

    t0 = _phase("Writing output files", quiet=quiet)
    run_logger.info("Writing output files")
    try:
        write_csv(result, csv_path, suppressed_findings=suppressed_pairs or None)
        write_jsonl(
            result,
            jsonl_path,
            classification=classification,
            suppressed_findings=suppressed_pairs or None,
        )
    except OutputError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    metadata = result.run_metadata
    collectors_run = len(metadata.collector_versions) if metadata is not None else 0
    rules_run = len(metadata.rules_run) if metadata is not None else 0
    rules_skipped = len(metadata.rules_skipped) if metadata is not None else 0
    files_emitted = 2  # csv + jsonl

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
    for warning in result.warnings:
        _ts_echo(f"warning: {warning}")

    if metadata is not None and metadata.rules_skipped:
        _ts_echo(
            f"WARNING: {len(metadata.rules_skipped)} rules skipped (use -v to see details)"
        )
        for skip in metadata.rules_skipped:
            run_logger.info("rule %s skipped (%s)", skip["rule_id"], skip["reason"])

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

    if not target.exists():
        click.echo(f"error: target does not exist: {target}", err=True)
        raise click.exceptions.Exit(1)
    if not target.is_dir():
        click.echo(f"error: target is not a directory: {target}", err=True)
        raise click.exceptions.Exit(1)

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

    _phase("Loading configuration", quiet=quiet)
    effective_config_path = config_path
    if effective_config_path is None:
        default = Path("nfr-review.yaml")
        if default.exists():
            effective_config_path = default

    try:
        config: Config = load_config(effective_config_path)
    except ConfigError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    t0 = _phase("Detecting technologies", quiet=quiet)
    try:
        detected = detect_technologies(target)
    except Exception as e:  # noqa: BLE001
        logger.debug("Technology detection failed for %s: %s", target, e)
        detected = {}
    merged_tech = {**detected, **config.tech}
    config = config.model_copy(update={"tech": merged_tech})

    config = config.model_copy(update={"exclude_test_paths": not include_tests})

    active_tech = [k for k, v in merged_tech.items() if v]
    if active_tech:
        _ts_echo(f"Technologies: {', '.join(sorted(active_tech))}", quiet=quiet)

    from nfr_review.protocols import Rule as RuleProtocol

    if category is not None:
        requested = {c.strip() for c in category.split(",")}
        filtered: Registry[RuleProtocol] = Registry("hygiene-rule")
        for rule in hygiene_rule_registry.all():
            if getattr(rule, "category", None) in requested:
                filtered.register(rule.id, rule)
        effective_rules: Registry[RuleProtocol] = filtered
    else:
        effective_rules = hygiene_rule_registry

    t0 = _phase("Running hygiene scan (collect + evaluate)", quiet=quiet)
    try:
        result: RunResult = Engine(
            collectors=hygiene_collector_registry,
            rules=effective_rules,
        ).run(target, config)
    except EngineError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("Hygiene scan", t0, quiet=quiet)

    csv_name = f"{repo}-hygiene-report.csv"
    jsonl_name = f"{repo}-hygiene-report.jsonl"

    _phase("Writing output files", quiet=quiet)
    try:
        if output_format in ("csv", "both"):
            write_csv(result, output_dir / csv_name)
        if output_format in ("jsonl", "both"):
            write_jsonl(result, output_dir / jsonl_name)
    except OutputError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    metadata = result.run_metadata
    collectors_run = len(metadata.collector_versions) if metadata is not None else 0
    rules_run = len(metadata.rules_run) if metadata is not None else 0
    rules_skipped = len(metadata.rules_skipped) if metadata is not None else 0
    files_emitted = sum(
        [
            1 if output_format in ("csv", "both") else 0,
            1 if output_format in ("jsonl", "both") else 0,
        ]
    )
    output_paths: list[str] = []
    if output_format in ("csv", "both"):
        output_paths.append(str(output_dir / csv_name))
    if output_format in ("jsonl", "both"):
        output_paths.append(str(output_dir / jsonl_name))

    _ts_echo(
        f"nfr-review hygiene: collectors_run={collectors_run} "
        f"rules_run={rules_run} rules_skipped={rules_skipped} "
        f"findings={len(result.findings)} files_emitted={files_emitted} "
        f"output={', '.join(output_paths)}"
    )
    for warning in result.warnings:
        _ts_echo(f"warning: {warning}")

    if metadata is not None and metadata.rules_skipped:
        _ts_echo(
            f"WARNING: {len(metadata.rules_skipped)} rules skipped (use -v to see details)"
        )
        hygiene_logger = logging.getLogger("nfr_review")
        for skip in metadata.rules_skipped:
            hygiene_logger.info("rule %s skipped (%s)", skip["rule_id"], skip["reason"])

    if severity_threshold is not None:
        threshold: Severity = severity_threshold  # type: ignore[assignment]
        if _exceeds_threshold(result, threshold):
            raise click.exceptions.Exit(2)


def run_report_pipeline(
    target: Path,
    *,
    output_dir: Path = Path("reports"),
    config_path: Path | None = None,
    no_tests: bool = False,
    no_deps: bool = False,
    no_diagrams: bool = False,
    pdf: bool = True,
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
) -> ReportResult:
    """Run the full NFR + hygiene report pipeline and return structured results.

    This is the core pipeline extracted from the ``report`` CLI command so that
    callers (e.g. the ``all`` command) can invoke it without a Click context.
    """
    from nfr_review.output.jdepend_section import (
        build_adr_section,
        build_derived_adrs_section,
        build_jdepend_section,
    )
    from nfr_review.output.markdown import render_markdown_report
    from nfr_review.output.pytest_runner import run_pytest

    repo = _repo_name(target)
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
    _banner("report", repo, target, options=opts or None, phases=phases, quiet=quiet)

    _phase("Loading configuration", quiet=quiet)
    effective_config_path = config_path
    if effective_config_path is None:
        default = Path("nfr-review.yaml")
        if default.exists():
            effective_config_path = default

    try:
        config: Config = load_config(effective_config_path)
    except ConfigError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    # Merge repo-local scoring overrides when a central config is provided
    # and the target repo has its own nfr-review.yaml with scoring settings.
    repo_local_cfg_path = target / "nfr-review.yaml"
    if (
        effective_config_path is not None
        and repo_local_cfg_path.exists()
        and repo_local_cfg_path.resolve() != effective_config_path.resolve()
    ):
        try:
            repo_config = load_config(repo_local_cfg_path)
            config = config.with_repo_scoring(repo_config)
        except ConfigError:
            pass  # repo-local config is malformed — use central defaults

    _phase("Detecting technologies", quiet=quiet)
    try:
        detected = detect_technologies(target)
    except Exception as e:  # noqa: BLE001
        logger.debug("Technology detection failed for %s: %s", target, e)
        detected = {}
    merged_tech = {**detected, **config.tech}
    report_updates: dict[str, Any] = {
        "tech": merged_tech,
        "exclude_test_paths": not include_tests,
    }
    if otel_traces is not None:
        report_updates["otel_traces"] = otel_traces
    config = config.model_copy(update=report_updates)
    active_tech = [k for k, v in merged_tech.items() if v]
    if active_tech:
        _ts_echo(f"Technologies: {', '.join(sorted(active_tech))}", quiet=quiet)

    # NFR scan
    t0 = _phase("Running NFR scan (collect + evaluate)", quiet=quiet)
    try:
        nfr_result: RunResult = Engine(workers=workers).run(target, config)
    except EngineError as exc:
        click.echo(f"error: NFR scan failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("NFR scan", t0, quiet=quiet)

    # Hygiene scan
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

    # Suppressions
    from nfr_review.suppression import apply_suppressions

    all_findings = list(nfr_result.findings) + list(hygiene_result.findings)
    active_report_findings, suppressed_report_pairs = apply_suppressions(
        all_findings, target_root=target.resolve()
    )
    if suppressed_report_pairs:
        with_reason = sum(1 for _, info in suppressed_report_pairs if info.reason)
        _ts_echo(
            f"Suppressed: {len(suppressed_report_pairs)} finding(s) via inline markers"
            f" ({with_reason} with justification)",
            quiet=quiet,
        )

    # Pytest execution
    pytest_result = None
    if not no_tests:
        t0 = _phase(f"Running pytest (timeout: {test_timeout}s)", quiet=quiet)
        pytest_result = run_pytest(target, timeout=test_timeout)
        _phase_done("Pytest", t0, quiet=quiet)

    # Dependency analysis
    deps_section = ""
    deps_reports: list[Any] = []
    if not no_deps:
        from nfr_review.deps_analysis import analyze_deps
        from nfr_review.output.deps_report import render_deps_section

        t0 = _phase("Analyzing dependencies", quiet=quiet)

        def _progress(msg: str) -> None:
            _ts_echo(msg)

        try:
            deps_reports = analyze_deps(
                target,
                config,
                resolve_transitive=True,
                progress_callback=_progress,
                max_resolve_rounds=max_resolve_rounds,
            )
            deps_section = render_deps_section(deps_reports)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Dependency analysis failed: %s", exc, exc_info=True)
            _ts_echo(f"warning: dependency analysis failed: {exc}")
            deps_section = (
                f"## Appendix A — Dependency Tree\n\nDependency analysis failed: {exc}\n"
            )
        _phase_done("Dependency analysis", t0, quiet=quiet)

    # Build diagram sections
    diagrams: dict[str, str] | None = None
    if not no_diagrams:
        from nfr_review.output.diagrams import (
            render_mermaid_dep_graph,
            render_mermaid_severity_pie,
            render_mermaid_tech_overview,
        )

        _phase("Building diagrams", quiet=quiet)
        all_findings = list(nfr_result.findings) + list(hygiene_result.findings)
        diagrams = {}
        if all_findings:
            diagrams["Severity Distribution"] = render_mermaid_severity_pie(
                all_findings,
            )
        if merged_tech:
            diagrams["Technology Overview"] = render_mermaid_tech_overview(
                merged_tech,
            )
        if not no_deps and deps_reports:
            diagrams["Dependency Graph"] = render_mermaid_dep_graph(deps_reports)

    # Build evidence-aware report sections
    jdepend_section = build_jdepend_section(nfr_result.evidence)
    derived_adrs_section = build_derived_adrs_section(nfr_result.evidence)
    adr_section = build_adr_section(nfr_result.evidence)

    # Compute maturity score section for report
    score_section = ""
    if show_score:
        from nfr_review.output.markdown import render_score_section
        from nfr_review.scoring import compute_maturity_score

        all_report_findings = list(nfr_result.findings) + list(hygiene_result.findings)
        nfr_meta = nfr_result.run_metadata
        score = compute_maturity_score(
            all_report_findings,
            nfr_meta.rules_run if nfr_meta else [],
            nfr_meta.rules_skipped if nfr_meta else [],
            config.scoring,
        )
        score_section = render_score_section(score)

    # Build LLM provenance for methodology appendix.
    # Always check — collectors like adr-derive use the LLM independently
    # of the executive summary, so the disclosure must not be gated on
    # no_summary.  Use the no-args factory (same path collectors use) so
    # legacy env-var fallbacks (NFR_LLM_BACKEND) are also detected.
    from nfr_review.llm_client import (
        ClaudeCliClient,
        create_llm_client,
    )

    resolved_llm = config.llm.resolve()
    llm_info: tuple[str, str] | None = None
    _llm_client = create_llm_client(resolved_llm)
    if _llm_client.available:
        llm_info = (resolved_llm.provider, resolved_llm.model)
    else:
        _default_client = create_llm_client()
        if _default_client.available:
            _prov = "claude-cli" if isinstance(_default_client, ClaudeCliClient) else "openai"
            llm_info = (_prov, resolved_llm.model)

    # Generate report
    _phase("Rendering Markdown report", quiet=quiet)
    md_content = render_markdown_report(
        nfr_result=nfr_result,
        hygiene_result=hygiene_result,
        pytest_result=pytest_result,
        deps_section=deps_section,
        jdepend_section=jdepend_section,
        adr_section=adr_section,
        derived_adrs_section=derived_adrs_section,
        diagrams=diagrams,
        score_section=score_section,
        suppressed_findings=suppressed_report_pairs or None,
        llm_info=llm_info,
    )

    # Write output files
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    if stem is None:
        stem = f"{repo}-nfr-review-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{stem}.md"
    csv_path = output_dir / f"{stem}.csv"
    jsonl_path = output_dir / f"{stem}.jsonl"

    _phase("Writing output files", quiet=quiet)
    try:
        md_path.write_text(md_content, encoding="utf-8")

        combined_result = RunResult(
            findings=list(nfr_result.findings) + list(hygiene_result.findings),
            rule_results=(list(nfr_result.rule_results) + list(hygiene_result.rule_results)),
            run_metadata=nfr_result.run_metadata,
            warnings=list(nfr_result.warnings) + list(hygiene_result.warnings),
        )
        write_csv(
            combined_result,
            csv_path,
            suppressed_findings=suppressed_report_pairs or None,
        )
        write_jsonl(
            combined_result,
            jsonl_path,
            suppressed_findings=suppressed_report_pairs or None,
        )
        actual_sarif: Path | None = None
        if sarif_path is not None:
            from nfr_review.output.sarif import write_sarif

            write_sarif(combined_result, sarif_path)
            actual_sarif = sarif_path
    except (OSError, OutputError) as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    # PDF generation
    pdf_path: Path | None = None
    if pdf:
        try:
            from nfr_review.output.pdf import render_pdf
        except ImportError as exc:
            click.echo(
                "error: weasyprint is required for PDF output — "
                "install with 'pip install nfr-review[pdf]'",
                err=True,
            )
            raise click.exceptions.Exit(1) from exc

        # Render diagram images
        diagram_image_paths: dict[str, Path] | None = None
        if diagrams:
            from nfr_review.output.render import render_dot_to_png, render_mermaid_to_png

            _phase("Rendering diagram images", quiet=quiet)
            img_dir = output_dir / f"{stem}-images"
            diagram_image_paths = {}
            for dtitle, mermaid_text in diagrams.items():
                slug = dtitle.lower().replace(" ", "-")
                img = render_mermaid_to_png(mermaid_text, img_dir / f"{slug}.png", scale=3)
                if img is None and dtitle == "Dependency Graph" and deps_reports:
                    from nfr_review.output.dot import render_dot_dependency_graph

                    dot_text = render_dot_dependency_graph(deps_reports)
                    img = render_dot_to_png(dot_text, img_dir / f"{slug}.png", dpi=288)
                if img is not None:
                    diagram_image_paths[dtitle] = img
                elif not quiet:
                    _ts_echo(
                        f"warning: diagram '{dtitle}' could not be rendered"
                        " (mmdc/dot failed or not installed)"
                    )

        # Generate executive summary
        exec_summary = None
        if not no_summary:
            from nfr_review.output.summarize import generate_executive_summary

            t0 = _phase("Generating executive summary via LLM", quiet=quiet)
            exec_summary = generate_executive_summary(
                nfr_result, hygiene_result, pytest_result, deps_section
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
                pytest_result=pytest_result,
                deps_section_md=deps_section,
                jdepend_section_md=jdepend_section,
                adr_section_md=adr_section,
                derived_adrs_section_md=derived_adrs_section,
                diagram_paths=diagram_image_paths,
                score_section_md=score_section,
                llm_info=llm_info,
            )
            _phase_done("PDF generation", t0, quiet=quiet)
        # nfr-review:skip(bare-except-catch-all, python-broad-except-silent)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"error: PDF generation failed: {exc}", err=True)
            pdf_path = None

    nfr_count = len(nfr_result.findings)
    hygiene_count = len(hygiene_result.findings)
    total = nfr_count + hygiene_count

    if not quiet:
        click.echo("", err=True)
    summary_parts = [
        f"nfr-review report: findings={total}",
        f"output={md_path} csv={csv_path} jsonl={jsonl_path}",
    ]
    if pdf_path:
        summary_parts.append(f"pdf={pdf_path}")
    if actual_sarif is not None:
        summary_parts.append(f"sarif={actual_sarif}")
    _ts_echo(" ".join(summary_parts))

    return ReportResult(
        md_path=md_path,
        csv_path=csv_path,
        jsonl_path=jsonl_path,
        sarif_path=actual_sarif,
        pdf_path=pdf_path,
        total_findings=total,
        nfr_count=nfr_count,
        hygiene_count=hygiene_count,
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
    no_summary: bool,
    test_timeout: int,
    sarif_path: Path | None = None,
    no_score: bool = False,
    max_resolve_rounds: int | None = None,
    workers: int = 1,
    otel_traces_path: Path | None = None,
) -> None:
    """Report command — run NFR + hygiene scans, optional pytest, emit report."""
    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)

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
        no_summary=no_summary,
        test_timeout=test_timeout,
        sarif_path=sarif_path,
        show_score=not no_score,
        max_resolve_rounds=max_resolve_rounds,
        include_tests=not exclude_tests,
        quiet=quiet,
        workers=workers,
        otel_traces=otel_traces_path,
    )


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
    from nfr_review.output.deps_report import (
        render_deps_section,
        render_deps_terminal,
    )

    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)

    if not target.exists():
        click.echo(f"error: target does not exist: {target}", err=True)
        raise click.exceptions.Exit(1)
    if not target.is_dir():
        click.echo(f"error: target is not a directory: {target}", err=True)
        raise click.exceptions.Exit(1)

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

    _phase("Loading configuration", quiet=quiet)
    effective_config_path = config_path
    if effective_config_path is None:
        default = Path("nfr-review.yaml")
        if default.exists():
            effective_config_path = default

    try:
        config: Config = load_config(effective_config_path)
    except ConfigError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    _phase("Detecting technologies", quiet=quiet)
    try:
        detected = detect_technologies(target)
    except Exception as e:  # noqa: BLE001
        logger.debug("Technology detection failed for %s: %s", target, e)
        detected = {}
    merged_tech = {**detected, **config.tech}
    config = config.model_copy(update={"tech": merged_tech})

    t0 = _phase("Analyzing dependencies", quiet=quiet)

    def _progress(msg: str) -> None:
        _ts_echo(msg)

    try:
        reports = analyze_deps(
            target,
            config,
            resolve_transitive=not no_tree,
            progress_callback=_progress,
            max_resolve_rounds=max_resolve_rounds,
        )
    except Exception as exc:  # noqa: BLE001
        click.echo(f"error: dependency analysis failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("Dependency analysis", t0, quiet=quiet)

    if dot_path:
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
    elif render_diagrams:
        click.echo(
            "warning: --render-diagrams requires --dot <file>",
            err=True,
        )

    if output_path:
        md_content = render_deps_section(reports)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(md_content, encoding="utf-8")
            click.echo(f"deps report written to {output_path}", err=True)
        except OSError as exc:
            click.echo(f"error: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
    else:
        click.echo(render_deps_terminal(reports))

    total_deps = sum(len(r.upgrades) for r in reports)
    ecosystems = len(reports)
    _ts_echo(f"nfr-review deps: ecosystems={ecosystems} dependencies={total_deps}")


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
    import subprocess  # nosec B404 — args are hardcoded, not user input

    from nfr_review.issues import file_issues, filter_findings

    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)

    if not target.exists():
        click.echo(f"error: target does not exist: {target}", err=True)
        raise click.exceptions.Exit(1)
    if not target.is_dir():
        click.echo(f"error: target is not a directory: {target}", err=True)
        raise click.exceptions.Exit(1)

    # Resolve repo from git remote if not supplied
    if repo is None and not dry_run:
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
                repo = gh_result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        if not repo:
            click.echo(
                "error: could not detect GitHub repo"
                " — pass --repo owner/repo or use --dry-run",
                err=True,
            )
            raise click.exceptions.Exit(1)

    repo_name = _repo_name(target)
    _banner(
        "issues",
        repo_name,
        target,
        options={"dry_run": str(dry_run), "threshold": severity_threshold},
        phases=["config", "detect", "scan", "issues"],
        quiet=quiet,
    )

    # Load config
    _phase("Loading configuration", quiet=quiet)
    effective_config_path = config_path
    if effective_config_path is None:
        default = Path("nfr-review.yaml")
        if default.exists():
            effective_config_path = default

    try:
        config: Config = load_config(effective_config_path)
    except ConfigError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    # Detect technologies
    _phase("Detecting technologies", quiet=quiet)
    try:
        detected = detect_technologies(target)
    except Exception as e:  # noqa: BLE001
        logger.debug("Technology detection failed for %s: %s", target, e)
        detected = {}
    merged_tech = {**detected, **config.tech}
    config = config.model_copy(update={"tech": merged_tech})

    # Run NFR scan
    t0 = _phase("Running NFR scan", quiet=quiet)
    try:
        result = Engine().run(target, config)
    except EngineError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("NFR scan", t0, quiet=quiet)

    # Convert findings to dicts for issue filing
    finding_dicts = [f.model_dump() for f in result.findings]
    filtered = filter_findings(finding_dicts, severity_threshold)

    if not filtered:
        _ts_echo(f"No findings at severity >= {severity_threshold} — nothing to file.")
        return

    _ts_echo(f"Found {len(filtered)} findings at severity >= {severity_threshold}")

    # File or preview issues
    t0 = _phase("Filing issues" if not dry_run else "Previewing issues", quiet=quiet)
    issue_results = file_issues(
        finding_dicts,
        repo or "",
        dry_run=dry_run,
        severity_threshold=severity_threshold,
    )

    filed = sum(1 for r in issue_results if r["status"] == "filed")
    skipped = sum(1 for r in issue_results if r["status"] == "skipped")
    dry_count = sum(1 for r in issue_results if r["status"] == "dry_run")
    errors = sum(1 for r in issue_results if r["status"] == "error")

    for r in issue_results:
        status = r["status"]
        url = f" {r['url']}" if r.get("url") else ""
        _ts_echo(f"  [{status}] {r['title']}{url}")

    if dry_run:
        _ts_echo(f"dry run: {dry_count} issue(s) would be filed")
    else:
        _ts_echo(f"filed={filed} skipped={skipped} errors={errors}")


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
    import json as _json

    from nfr_review.issues import sync_issues

    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    if not dry_run and not repo:
        raise click.UsageError("--repo is required unless --dry-run is set")
    _configure_logging(verbose, quiet, None)

    # Load findings from JSONL
    findings: list[dict[str, Any]] = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = _json.loads(line)
            if rec.get("record_type") == "finding":
                findings.append(rec)

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
    type=click.Choice(["json", "md", "pdf"]),
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
def arch_cmd(
    targets: tuple[Path, ...],
    verbose: int,
    quiet: bool,
    log_file: Path | None,
    output_dir: Path,
    output_formats: tuple[str, ...],
    no_llm: bool,
    diagram_mode: str,
) -> None:
    """Generate architecture documentation report."""
    from nfr_review.arch_orchestrator import run_arch_review
    from nfr_review.arch_report_render import render_arch_report

    click.echo(
        "WARNING: The arch command is experimental and subject to change.",
        err=True,
    )

    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive")
    _configure_logging(verbose, quiet, log_file)

    target_list = list(targets)
    repo_names = [_repo_name(t) for t in target_list]
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

    _banner(
        "arch",
        primary_repo,
        target_list[0],
        options=opts or None,
        phases=phases,
        quiet=quiet,
    )

    def _progress(msg: str) -> None:
        _ts_echo(msg, quiet=quiet)

    t0 = _phase("Running architecture review", quiet=quiet)
    try:
        report = run_arch_review(
            target_list,
            repo_names=repo_names,
            skip_llm=no_llm,
            diagram_mode=diagram_mode,
            progress=_progress,
        )
    except Exception as exc:  # noqa: BLE001
        click.echo(f"error: architecture review failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("Architecture review", t0, quiet=quiet)

    # Determine formats
    formats = list(output_formats) if output_formats else None

    t0 = _phase("Rendering output files", quiet=quiet)
    try:
        results = render_arch_report(report, output_dir, formats=formats)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"error: report rendering failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    _phase_done("Output rendering", t0, quiet=quiet)

    # Summary
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

    output_dir.mkdir(parents=True, exist_ok=True)
    arch_result: dict[str, Any] | None = None

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
            stem = f"{repo}-nfr-review-{timestamp}"
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
                stem=stem,
                workers=workers,
            )
            results.append((repo, rr))
        return results

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

    # Summary
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


@cli.command("version", help="Print the nfr-review version and exit.")
def version_cmd() -> None:
    """Print version."""
    click.echo(__version__)


__all__ = ["ReportResult", "_DedupFilter", "_configure_logging", "cli", "run_report_pipeline"]


if __name__ == "__main__":
    cli()
