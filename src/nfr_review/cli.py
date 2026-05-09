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

from pathlib import Path

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


@click.group(help="Automated non-functional requirements review.")
@click.version_option(__version__, prog_name="nfr-review")
def cli() -> None:
    """Top-level command group."""


@cli.command("run", help="Run an NFR scan against TARGET (a repository directory).")
@click.argument("target", type=click.Path(file_okay=False, path_type=Path))
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
    default=Path("nfr-review.csv"),
    show_default=True,
    help="Output path for the R007 CSV findings file.",
)
@click.option(
    "--jsonl",
    "jsonl_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("nfr-review.jsonl"),
    show_default=True,
    help="Output path for the R018 JSONL run record.",
)
def run_cmd(
    target: Path,
    config_path: Path | None,
    csv_path: Path,
    jsonl_path: Path,
) -> None:
    """Run command — load config, run engine, emit CSV+JSONL, print summary."""
    if not target.exists():
        click.echo(f"error: target does not exist: {target}", err=True)
        raise click.exceptions.Exit(1)
    if not target.is_dir():
        click.echo(f"error: target is not a directory: {target}", err=True)
        raise click.exceptions.Exit(1)

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

    try:
        detected = detect_technologies(target)
    except Exception:
        detected = {}
    merged_tech = {**detected, **config.tech}
    config = config.model_copy(update={"tech": merged_tech})
    tech_detected = sum(1 for v in detected.values() if v)

    try:
        result = Engine().run(target, config)
    except EngineError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    try:
        write_csv(result, csv_path)
        write_jsonl(result, jsonl_path)
    except OutputError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    metadata = result.run_metadata
    collectors_run = len(metadata.collector_versions) if metadata is not None else 0
    rules_run = len(metadata.rules_run) if metadata is not None else 0
    rules_skipped = len(metadata.rules_skipped) if metadata is not None else 0
    files_emitted = 2  # csv + jsonl

    click.echo(
        (
            f"nfr-review: tech_detected={tech_detected} "
            f"collectors_run={collectors_run} "
            f"rules_run={rules_run} rules_skipped={rules_skipped} "
            f"findings={len(result.findings)} files_emitted={files_emitted} "
            f"csv={csv_path} jsonl={jsonl_path}"
        ),
        err=True,
    )
    for warning in result.warnings:
        click.echo(f"warning: {warning}", err=True)

    if _exceeds_threshold(result, config.severity_threshold):
        raise click.exceptions.Exit(2)


@cli.command("list-rules", help="List every registered rule (id, band, summary).")
def list_rules_cmd() -> None:
    """List all registered rules."""
    rules = rule_registry.all()
    if not rules:
        return
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
def hygiene_cmd(
    target: Path | None,
    list_checks: bool,
    output_dir: Path,
    output_format: str,
    severity_threshold: str | None,
    category: str | None,
    config_path: Path | None,
) -> None:
    """Hygiene command — run hygiene collectors and rules, emit output."""
    if list_checks:
        for rule in hygiene_rule_registry.all():
            cat = getattr(rule, "category", "uncategorized")
            click.echo(f"{rule.id}\tcategory={cat}\tband={rule.band}\t{_rule_summary(rule)}")
        return

    if target is None:
        click.echo("error: TARGET is required (unless --list-checks is set)", err=True)
        raise click.exceptions.Exit(1)

    if not target.exists():
        click.echo(f"error: target does not exist: {target}", err=True)
        raise click.exceptions.Exit(1)
    if not target.is_dir():
        click.echo(f"error: target is not a directory: {target}", err=True)
        raise click.exceptions.Exit(1)

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

    try:
        result: RunResult = Engine(
            collectors=hygiene_collector_registry,
            rules=effective_rules,
        ).run(target, config)
    except EngineError as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    try:
        if output_format in ("csv", "both"):
            write_csv(result, output_dir / "hygiene-report.csv")
        if output_format in ("jsonl", "both"):
            write_jsonl(result, output_dir / "hygiene-report.jsonl")
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
        output_paths.append(str(output_dir / "hygiene-report.csv"))
    if output_format in ("jsonl", "both"):
        output_paths.append(str(output_dir / "hygiene-report.jsonl"))

    click.echo(
        (
            f"nfr-review hygiene: collectors_run={collectors_run} "
            f"rules_run={rules_run} rules_skipped={rules_skipped} "
            f"findings={len(result.findings)} files_emitted={files_emitted} "
            f"output={', '.join(output_paths)}"
        ),
        err=True,
    )
    for warning in result.warnings:
        click.echo(f"warning: {warning}", err=True)

    if severity_threshold is not None:
        threshold: Severity = severity_threshold  # type: ignore[assignment]
        if _exceeds_threshold(result, threshold):
            raise click.exceptions.Exit(2)


@cli.command("report", help="Run NFR + hygiene scans and produce a timestamped report.")
@click.argument("target", type=click.Path(file_okay=False, path_type=Path))
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
def report_cmd(
    target: Path,
    config_path: Path | None,
    output_dir: Path,
    no_tests: bool,
) -> None:
    """Report command — run NFR + hygiene scans, optional pytest, emit report."""
    from datetime import UTC, datetime

    from nfr_review.output.markdown import render_markdown_report
    from nfr_review.output.pytest_runner import run_pytest

    if not target.exists():
        click.echo(f"error: target does not exist: {target}", err=True)
        raise click.exceptions.Exit(1)
    if not target.is_dir():
        click.echo(f"error: target is not a directory: {target}", err=True)
        raise click.exceptions.Exit(1)

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

    try:
        detected = detect_technologies(target)
    except Exception:
        detected = {}
    merged_tech = {**detected, **config.tech}
    config = config.model_copy(update={"tech": merged_tech})

    # NFR scan
    try:
        nfr_result: RunResult = Engine().run(target, config)
    except EngineError as exc:
        click.echo(f"error: NFR scan failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    # Hygiene scan
    try:
        hygiene_result: RunResult = Engine(
            collectors=hygiene_collector_registry,
            rules=hygiene_rule_registry,
        ).run(target, config)
    except EngineError as exc:
        click.echo(f"error: hygiene scan failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    # Pytest execution
    pytest_result = None
    if not no_tests:
        pytest_result = run_pytest(target)

    # Generate report
    md_content = render_markdown_report(
        nfr_result=nfr_result,
        hygiene_result=hygiene_result,
        pytest_result=pytest_result,
    )

    # Write output files
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    stem = f"nfr-review-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{stem}.md"
    csv_path = output_dir / f"{stem}.csv"
    jsonl_path = output_dir / f"{stem}.jsonl"

    try:
        md_path.write_text(md_content, encoding="utf-8")

        combined_result = RunResult(
            findings=list(nfr_result.findings) + list(hygiene_result.findings),
            rule_results=(list(nfr_result.rule_results) + list(hygiene_result.rule_results)),
            run_metadata=nfr_result.run_metadata,
            warnings=list(nfr_result.warnings) + list(hygiene_result.warnings),
        )
        write_csv(combined_result, csv_path)
        write_jsonl(combined_result, jsonl_path)
    except (OSError, OutputError) as exc:
        click.echo(f"error: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    total = len(nfr_result.findings) + len(hygiene_result.findings)
    click.echo(
        (
            f"nfr-review report: findings={total} "
            f"output={md_path} csv={csv_path} jsonl={jsonl_path}"
        ),
        err=True,
    )


@cli.command("version", help="Print the nfr-review version and exit.")
def version_cmd() -> None:
    """Print version."""
    click.echo(__version__)


__all__ = ["cli"]


if __name__ == "__main__":
    cli()
