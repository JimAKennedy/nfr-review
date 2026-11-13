# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Architecture output must not depend on the filesystem's listing order.

``Path.glob``/``Path.rglob`` return entries in whatever order the filesystem
lists them: alphabetical on APFS, hash order on ext4. The nightly regression
job went red when a runner image update flipped two databases in the
awesome-compose DSL snapshot. Each test here runs one discovery function
twice — once with glob results in sorted order, once reversed — and asserts
identical output.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from nfr_review.arch_discovery import _discover_k8s_components
from nfr_review.arch_integ_compose import find_compose_files
from nfr_review.arch_integ_config import discover_config_integrations
from nfr_review.arch_integ_grpc import _scan_for_grpc_clients, discover_grpc_integrations
from nfr_review.arch_integ_k8s import discover_k8s_env_integrations, discover_k8s_integrations
from nfr_review.arch_integ_manifest import _scan_manifest_deps
from nfr_review.arch_models import Component, ComponentBoundary
from nfr_review.arch_utils import scan_component_build_deps

_ORIG_GLOB = Path.glob
_ORIG_RGLOB = Path.rglob


def _ordered(
    reverse: bool,
) -> tuple[Callable[..., Iterator[Path]], Callable[..., Iterator[Path]]]:
    def glob(self: Path, pattern: str, *args: Any, **kwargs: Any) -> Iterator[Path]:
        return iter(sorted(_ORIG_GLOB(self, pattern, *args, **kwargs), reverse=reverse))

    def rglob(self: Path, pattern: str, *args: Any, **kwargs: Any) -> Iterator[Path]:
        return iter(sorted(_ORIG_RGLOB(self, pattern, *args, **kwargs), reverse=reverse))

    return glob, rglob


def _both_orders(monkeypatch: pytest.MonkeyPatch, fn: Callable[[], Any]) -> tuple[Any, Any]:
    results = []
    for reverse in (False, True):
        glob, rglob = _ordered(reverse)
        monkeypatch.setattr(Path, "glob", glob)
        monkeypatch.setattr(Path, "rglob", rglob)
        results.append(fn())
    monkeypatch.undo()
    return results[0], results[1]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _comp(cid: str, name: str, path: str = ".") -> Component:
    return Component(
        id=cid,
        name=name,
        description=name,
        component_type="service",
        boundaries=[ComponentBoundary(boundary_type="directory", path=path)],
    )


_DEPLOYMENT = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {name}
  labels:
    app: {name}
spec:
  selector:
    matchLabels:
      app: {name}
  template:
    metadata:
      labels:
        app: {name}
    spec:
      containers:
        - name: {name}
          image: example/{name}:1
          env:
            - name: {peer_env}
              value: "{peer}:8080"
---
apiVersion: v1
kind: Service
metadata:
  name: {name}
spec:
  selector:
    app: {name}
  ports:
    - port: 8080
"""


def _k8s_repo(tmp_path: Path) -> Path:
    _write(
        tmp_path / "k8s" / "alpha.yaml",
        _DEPLOYMENT.format(name="alpha", peer="beta", peer_env="BETA_SERVICE_ADDR"),
    )
    _write(
        tmp_path / "k8s" / "beta.yaml",
        _DEPLOYMENT.format(name="beta", peer="alpha", peer_env="ALPHA_SERVICE_ADDR"),
    )
    return tmp_path


def test_config_integrations_order_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The awesome-compose failure: two Spring configs naming two databases."""
    _write(
        tmp_path / "a-app" / "application.properties",
        "spring.datasource.url=jdbc:mysql://mysql:3306/example\n",
    )
    _write(
        tmp_path / "b-app" / "application.properties",
        "spring.datasource.url=jdbc:postgresql://db:5432/example\n",
    )
    comps = [_comp("a", "a-app", "a-app"), _comp("b", "b-app", "b-app")]

    fwd, rev = _both_orders(
        monkeypatch,
        lambda: [i.target_component_id for i in discover_config_integrations(tmp_path, comps)],
    )
    assert len(set(fwd)) == 2
    assert fwd == rev


def test_compose_files_order_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for env in ("dev", "prod"):
        _write(tmp_path / f"docker-compose.{env}.yml", "services: {}\n")

    fwd, rev = _both_orders(
        monkeypatch, lambda: [p.name for p in find_compose_files(tmp_path)]
    )
    assert len(fwd) == 2
    assert fwd == rev


def test_k8s_components_order_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _k8s_repo(tmp_path)
    fwd, rev = _both_orders(
        monkeypatch, lambda: [c.id for c in _discover_k8s_components(repo)]
    )
    assert len(fwd) == 2
    assert fwd == rev


def test_k8s_integrations_order_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _k8s_repo(tmp_path)
    comps = [_comp("alpha", "alpha"), _comp("beta", "beta")]

    def run() -> list[tuple[str, str]]:
        return [
            (i.source_component_id, i.target_component_id)
            for i in discover_k8s_integrations(repo, comps)
            + discover_k8s_env_integrations(repo, comps)
        ]

    fwd, rev = _both_orders(monkeypatch, run)
    assert len(fwd) >= 2
    assert fwd == rev


def test_grpc_integrations_order_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for svc in ("Alpha", "Beta"):
        _write(
            tmp_path / svc.lower() / f"{svc.lower()}.proto",
            f'syntax = "proto3";\nservice {svc}Service {{ rpc Get (Req) returns (Resp); }}\n',
        )
    _write(tmp_path / "client" / "main.go", "c := NewAlphaServiceClient(conn)\n")
    _write(tmp_path / "client" / "other.go", "d := NewBetaServiceClient(conn)\n")
    comps = [_comp("alpha", "alpha", "alpha"), _comp("beta", "beta", "beta")]
    comps.append(_comp("client", "client", "client"))

    fwd, rev = _both_orders(
        monkeypatch,
        lambda: [
            (i.source_component_id, i.target_component_id)
            for i in discover_grpc_integrations(tmp_path, comps)
        ],
    )
    assert fwd == rev


def test_grpc_client_scan_window_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the first 200 source files are scanned, so which 200 must not vary."""
    for i in range(200):
        _write(tmp_path / f"f{i:03d}.go", "package main\n")
    _write(tmp_path / "z_client.go", "c := NewCartServiceClient(conn)\n")

    fwd, rev = _both_orders(
        monkeypatch, lambda: _scan_for_grpc_clients(tmp_path, {"CartService": "cart"})
    )
    assert fwd == rev


_CSPROJ = """\
<Project Sdk="Microsoft.NET.Sdk">
  <ItemGroup>
    <PackageReference Include="{pkg}" Version="{ver}" />
  </ItemGroup>
</Project>
"""


def _csproj_dir(tmp_path: Path) -> Path:
    _write(tmp_path / "svc" / "A.csproj", _CSPROJ.format(pkg="Npgsql", ver="8.0.0"))
    _write(
        tmp_path / "svc" / "B.csproj", _CSPROJ.format(pkg="StackExchange.Redis", ver="2.7.0")
    )
    return tmp_path / "svc"


def test_manifest_csproj_order_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    comp_dir = _csproj_dir(tmp_path)
    fwd, rev = _both_orders(monkeypatch, lambda: _scan_manifest_deps(comp_dir))
    assert len(fwd) == 2
    assert fwd == rev


def test_build_deps_csproj_order_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _csproj_dir(tmp_path)
    comp = _comp("svc", "svc", "svc")

    fwd, rev = _both_orders(
        monkeypatch,
        lambda: [
            i.target_component_id
            for i in scan_component_build_deps(tmp_path, comp, tmp_path.name, set())
        ],
    )
    assert len(fwd) == 2
    assert fwd == rev


def test_k8s_service_only_manifest_does_not_hide_workload(tmp_path: Path) -> None:
    """A Service-only file listed first must not suppress the same-named Deployment.

    microservices-demo has ``.github/release-cluster/frontend-service.yaml``
    (a lone Service), which sorts before ``kubernetes-manifests/frontend.yaml``.
    """
    _write(
        tmp_path / "a-service-only" / "frontend-service.yaml",
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: frontend\nspec: {}\n",
    )
    _write(
        tmp_path / "kubernetes-manifests" / "frontend.yaml",
        _DEPLOYMENT.format(name="frontend", peer="cart", peer_env="CART_SERVICE_ADDR"),
    )

    names = [c.name for c in _discover_k8s_components(tmp_path)]
    assert names == ["frontend"]
