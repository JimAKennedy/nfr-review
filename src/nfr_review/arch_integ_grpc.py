# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""gRPC proto service definition discovery (Strategy 7).

Parses ``.proto`` files to find gRPC service definitions and maps them
to architecture components by scanning application source code for
client-stub usage patterns.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from nfr_review.arch_models import Component, IntegrationPoint
from nfr_review.arch_utils import make_id, safe_read_text
from nfr_review.path_filter import should_exclude_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategy 7: gRPC proto service definitions
# ---------------------------------------------------------------------------


def discover_grpc_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Parse .proto files to find gRPC service definitions and map to components."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    try:
        proto_files = list(repo_path.rglob("*.proto"))
    except OSError:
        return []

    # Collect service definitions from proto files
    service_pattern = re.compile(r"^service\s+(\w+)\s*\{", re.MULTILINE)

    # Build proto service name -> component mapping
    proto_services: dict[str, str] = {}  # ProtoServiceName -> proto_file_path
    for pf in proto_files:
        rel_path = str(pf.relative_to(repo_path))
        if should_exclude_path(rel_path):
            continue
        content = safe_read_text(pf)
        if not content:
            continue
        for match in service_pattern.finditer(content):
            proto_services[match.group(1)] = rel_path

    if not proto_services:
        return []

    # Map proto service names to components
    comp_names_lower = {c.name.lower(): c for c in components}

    def _match_proto_to_component(proto_svc_name: str) -> Component | None:
        """Match a proto service name like 'CartService' to a component like 'cartservice'."""
        # Direct match
        lower = proto_svc_name.lower()
        if lower in comp_names_lower:
            return comp_names_lower[lower]
        # Strip 'Service' suffix
        stripped = lower.removesuffix("service")
        if stripped in comp_names_lower:
            return comp_names_lower[stripped]
        # Try with common naming patterns
        for comp_lower, comp in comp_names_lower.items():
            if comp_lower.replace("-", "").replace("_", "") == stripped:
                return comp
            if comp_lower.replace("-", "").replace("_", "") == lower:
                return comp
        return None

    # For each component's source code, check which proto services it calls.
    # Skip components whose boundary is the repo root — they'd scan every
    # file and produce false cartesian-product matches.
    for comp in components:
        scan_dir = _resolve_grpc_scan_dir(repo_path, comp)
        if scan_dir is None:
            continue

        called_services = _scan_for_grpc_clients(scan_dir, proto_services)
        for called_svc in called_services:
            target_comp = _match_proto_to_component(called_svc)
            if target_comp is None or target_comp.id == comp.id:
                continue

            intg_id = make_id(
                "intg",
                f"{effective_name}/grpc/{comp.name}->{called_svc}",
            )
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=comp.id,
                    target_component_id=target_comp.id,
                    style="rpc",
                    protocol="grpc",
                    description=(f"gRPC call from '{comp.name}' to '{called_svc}'"),
                )
            )

    # If no code-level client scanning found results, create integrations
    # from K8s/Compose env vars that reference proto service names
    if not integrations:
        # At minimum, register that these proto services exist as RPC endpoints
        for proto_svc_name in proto_services:
            target_comp = _match_proto_to_component(proto_svc_name)
            if target_comp is None:
                continue
            # Log it for visibility but don't create orphan integrations
            logger.debug(
                "gRPC service '%s' maps to component '%s'",
                proto_svc_name,
                target_comp.name,
            )

    if integrations:
        logger.info("Found %d gRPC integrations", len(integrations))
    return integrations


def _resolve_grpc_scan_dir(repo_path: Path, comp: Component) -> Path | None:
    """Find a specific source directory for gRPC client scanning.

    When a component's boundary is the repo root (``./`` or ``.``), scanning
    the entire tree produces false positives. Instead, probe for a service-
    specific subdirectory like ``src/<name>/`` or ``services/<name>/``.
    Returns None if no specific directory can be found.
    """
    for boundary in comp.boundaries:
        bp = boundary.path
        comp_dir = repo_path / bp

        # If boundary points to a specific (non-root) directory, use it
        if bp not in (".", "./", "") and comp_dir.is_dir():
            return comp_dir

    # Boundary is repo root — try common service directory patterns
    name = comp.name
    for prefix in ("src", "services", "apps", "cmd", "internal", "packages"):
        candidate = repo_path / prefix / name
        if candidate.is_dir():
            return candidate
        # Try with 'service' suffix: e.g. src/cartservice/
        candidate_svc = repo_path / prefix / f"{name}service"
        if candidate_svc.is_dir():
            return candidate_svc

    return None


_PROTO_GENERATED_PATTERNS = re.compile(
    r"(\.pb\.go$|_pb2\.py$|_pb2_grpc\.py$|\.pb\.java$|\.pb\.cs$|"
    r"\.pb\.ts$|\.pb\.js$|_grpc\.pb\.go$|\.grpc\.cs$|Grpc\.java$|"
    r"\.proto$)",
)


def _scan_for_grpc_clients(
    comp_dir: Path,
    proto_services: dict[str, str],
) -> set[str]:
    """Scan application source files for gRPC client stub usage.

    Skips proto-generated files (``*_pb2.py``, ``*.pb.go``, etc.) to avoid
    false positives from generated stubs that contain all service definitions.
    """
    called: set[str] = set()
    source_extensions = (".go", ".py", ".java", ".cs", ".js", ".ts", ".rb")

    try:
        source_files = [
            f
            for ext in source_extensions
            for f in comp_dir.rglob(f"*{ext}")
            if not _PROTO_GENERATED_PATTERNS.search(f.name)
        ]
    except OSError:
        return called

    # Only match explicit client/stub patterns — not bare service names.
    # gRPC clients: NewCartServiceClient (Go), CartServiceStub (Java),
    # cart_service_pb2_grpc.CartServiceStub (Python)
    for svc_name in proto_services:
        patterns = [
            re.compile(rf"\bNew{svc_name}Client\b"),
            re.compile(rf"\b{svc_name}Client\b"),
            re.compile(rf"\b{svc_name}Stub\b"),
            re.compile(rf"\b{svc_name.lower()}_pb2_grpc\b"),
        ]

        for src_file in source_files[:200]:
            content = safe_read_text(src_file)
            if not content:
                continue
            for pat in patterns:
                if pat.search(content):
                    called.add(svc_name)
                    break
            if svc_name in called:
                break

    return called
