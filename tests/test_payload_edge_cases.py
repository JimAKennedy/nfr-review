# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Edge-case tests for the most complex typed payload models.

Covers: CppAstFilePayload, GoAstFilePayload, ServiceMesh payloads,
PythonAstFilePayload -- boundary values, optional defaults, extra-field
rejection, round-trip serialisation, and required-field validation.
"""

from __future__ import annotations

import sys

import pytest
from pydantic import ValidationError

from nfr_review.collectors.payloads.cpp_ast import (
    CppAstFilePayload,
    CppBaseClass,
    CppClassInfo,
    CppField,
    CppFunction,
    CppInclude,
    CppMethod,
    CppNewExpression,
    CppParameter,
)
from nfr_review.collectors.payloads.go_ast import (
    GoAstFilePayload,
    GoBaseClass,
    GoDeferStatement,
    GoErrorAssignment,
    GoField,
    GoGoroutineLaunch,
    GoHttpCall,
    GoMethod,
    GoParameter,
    GoStruct,
)
from nfr_review.collectors.payloads.python_ast import (
    PythonAstFilePayload,
    PythonAsyncCall,
    PythonBaseClass,
    PythonCatchBlock,
    PythonClassInfo,
    PythonDefaultArg,
    PythonField,
    PythonFunction,
    PythonImport,
    PythonMethod,
    PythonParameter,
)
from nfr_review.collectors.payloads.service_mesh import (
    ServiceMeshAnalysisArg,
    ServiceMeshAnalysisMetric,
    ServiceMeshDestinationRulePayload,
    ServiceMeshHttpRoute,
    ServiceMeshRetries,
    ServiceMeshRolloutPayload,
    ServiceMeshRouteDestination,
    ServiceMeshSubset,
    ServiceMeshSummaryPayload,
    ServiceMeshVirtualServicePayload,
)

# ---------------------------------------------------------------------------
# Helpers: minimal valid instances for deeply nested payloads
# ---------------------------------------------------------------------------


def _cpp_file_payload(**overrides) -> CppAstFilePayload:
    """Build a CppAstFilePayload with all required lists empty by default."""
    defaults = dict(
        file_path="main.cpp",
        functions=[],
        classes=[],
        namespaces=[],
        type_aliases=[],
        includes=[],
        new_expressions=[],
        delete_expressions=[],
        smart_pointers=[],
        raw_pointers=[],
        malloc_calls=[],
        catch_blocks=[],
        has_pragma_once=False,
        has_include_guard=False,
    )
    defaults.update(overrides)
    return CppAstFilePayload(**defaults)


def _go_file_payload(**overrides) -> GoAstFilePayload:
    defaults = dict(
        file_path="main.go",
        package="main",
        structs=[],
        catch_blocks=[],
        log_statements=[],
        functions=[],
        error_assignments=[],
        goroutine_launches=[],
        http_calls=[],
        defer_statements=[],
    )
    defaults.update(overrides)
    return GoAstFilePayload(**defaults)


def _python_file_payload(**overrides) -> PythonAstFilePayload:
    defaults = dict(
        file_path="app.py",
        module_path="app",
        classes=[],
        catch_blocks=[],
        log_statements=[],
        functions=[],
        imports=[],
        async_calls=[],
    )
    defaults.update(overrides)
    return PythonAstFilePayload(**defaults)


def _vs_payload(**overrides) -> ServiceMeshVirtualServicePayload:
    defaults = dict(
        file_path="vs.yaml",
        name="my-vs",
        hosts=["svc.default.svc.cluster.local"],
        http_routes=[],
        has_weighted_routing=False,
        total_routes=0,
    )
    defaults.update(overrides)
    return ServiceMeshVirtualServicePayload(**defaults)


# ===================================================================
# 1. CppAstFilePayload edge cases
# ===================================================================


def test_cpp_file_all_empty_lists():
    """All list fields default to empty -- minimal construction works."""
    p = _cpp_file_payload()
    assert p.functions == []
    assert p.classes == []
    assert p.log_statements == []
    assert p.has_pragma_once is False


def test_cpp_file_rejects_extra_field():
    with pytest.raises(ValidationError, match="extra_field"):
        _cpp_file_payload(extra_field="boom")


def test_cpp_file_roundtrip():
    cls = CppClassInfo(
        name="Foo",
        line=10,
        has_destructor=True,
        is_struct=False,
        base_classes=[CppBaseClass(name="Bar", access="public")],
        methods=[
            CppMethod(
                name="run",
                return_type="void",
                access="public",
                is_virtual=True,
                is_pure_virtual=False,
                line=12,
                parameters=[CppParameter(name="n", type="int")],
            )
        ],
        fields=[CppField(name="x_", type="int", access="private", line=11)],
        is_abstract=False,
        namespace="ns",
        friends=["Baz"],
        outer_class="",
    )
    p = _cpp_file_payload(
        classes=[cls],
        includes=[CppInclude(path="<vector>", is_system=True, line=1)],
        new_expressions=[
            CppNewExpression(
                line=20,
                file="main.cpp",
                expression="new Foo()",
                parent_call="",
                line_comment="",
            )
        ],
        has_pragma_once=True,
    )
    dumped = p.model_dump()
    restored = CppAstFilePayload.model_validate(dumped)
    assert restored == p


def test_cpp_line_boundary_zero():
    """Line 0 is technically valid (no constraint in the model)."""
    f = CppFunction(name="f", return_type="void", line=0, is_noexcept=False)
    assert f.line == 0


def test_cpp_line_boundary_large():
    f = CppFunction(name="f", return_type="void", line=sys.maxsize, is_noexcept=True)
    assert f.line == sys.maxsize


def test_cpp_class_empty_nested_lists():
    """A class with no methods, fields, bases, or friends."""
    cls = CppClassInfo(
        name="Empty",
        line=1,
        has_destructor=False,
        is_struct=True,
        base_classes=[],
        methods=[],
        fields=[],
        is_abstract=False,
        namespace="",
        friends=[],
        outer_class="",
    )
    assert cls.methods == []
    assert cls.friends == []


def test_cpp_method_missing_parameters_raises():
    """parameters is required -- omitting it must fail."""
    with pytest.raises(ValidationError, match="parameters"):
        CppMethod(
            name="f",
            return_type="void",
            access="public",
            is_virtual=False,
            is_pure_virtual=False,
            line=1,
            # parameters intentionally omitted
        )


# ===================================================================
# 2. GoAstFilePayload edge cases
# ===================================================================


def test_go_file_minimal():
    p = _go_file_payload()
    assert p.package == "main"
    assert p.http_calls == []


def test_go_file_rejects_extra_field():
    with pytest.raises(ValidationError, match="bogus"):
        _go_file_payload(bogus=True)


def test_go_file_roundtrip_with_nested():
    struct = GoStruct(
        name="Server",
        line=5,
        is_struct=True,
        is_abstract=False,
        is_interface=False,
        base_classes=[GoBaseClass(name="io.Reader", access="public")],
        fields=[GoField(name="port", type="int", access="public", line=6)],
        methods=[
            GoMethod(
                name="Start",
                return_type="error",
                access="public",
                is_virtual=False,
                is_pure_virtual=False,
                line=10,
                parameters=[GoParameter(name="ctx", type="context.Context")],
            )
        ],
        namespace="server",
        outer_class="",
    )
    p = _go_file_payload(
        structs=[struct],
        error_assignments=[
            GoErrorAssignment(call="os.Open(f)", error_ignored=True, line=20, file="main.go")
        ],
        goroutine_launches=[
            GoGoroutineLaunch(expression="go serve()", line=30, file="main.go")
        ],
        http_calls=[
            GoHttpCall(call="http.Get(url)", has_timeout=False, line=40, file="main.go")
        ],
        defer_statements=[
            GoDeferStatement(
                expression="defer f.Close()", in_loop=True, line=22, file="main.go"
            )
        ],
    )
    dumped = p.model_dump()
    restored = GoAstFilePayload.model_validate(dumped)
    assert restored == p


def test_go_error_assignment_ignored_flag():
    ea = GoErrorAssignment(call="db.Query()", error_ignored=False, line=1, file="db.go")
    assert ea.error_ignored is False


def test_go_defer_in_loop_boundary():
    d = GoDeferStatement(expression="defer mu.Unlock()", in_loop=False, line=1, file="x.go")
    assert d.in_loop is False


# ===================================================================
# 3. ServiceMesh payload edge cases
# ===================================================================


def test_vs_optional_defaults():
    p = _vs_payload()
    assert p.namespace is None
    assert p.total_routes == 0


def test_vs_rejects_extra_field():
    with pytest.raises(ValidationError, match="extra"):
        _vs_payload(extra="x")


def test_vs_requires_hosts():
    with pytest.raises(ValidationError, match="hosts"):
        ServiceMeshVirtualServicePayload(
            file_path="vs.yaml",
            name="x",
            http_routes=[],
            has_weighted_routing=False,
            total_routes=0,
            # hosts intentionally omitted
        )


def test_vs_roundtrip_with_routes():
    route = ServiceMeshHttpRoute(
        destinations=[
            ServiceMeshRouteDestination(host="svc-a", subset="v1", weight=80),
            ServiceMeshRouteDestination(host="svc-a", subset="v2", weight=20),
        ],
        timeout="5s",
        retries=ServiceMeshRetries(attempts=3, per_try_timeout="2s", retry_on="5xx"),
        fault={"delay": {"percentage": {"value": 10}, "fixedDelay": "5s"}},
        match=[{"uri": {"prefix": "/api"}}],
    )
    p = _vs_payload(
        http_routes=[route],
        has_weighted_routing=True,
        total_routes=1,
        namespace="prod",
    )
    dumped = p.model_dump()
    restored = ServiceMeshVirtualServicePayload.model_validate(dumped)
    assert restored == p


def test_destination_rule_optional_defaults():
    dr = ServiceMeshDestinationRulePayload(
        file_path="dr.yaml",
        name="my-dr",
        host="reviews.default.svc.cluster.local",
        subsets=[],
        has_connection_pool=False,
        has_outlier_detection=False,
    )
    assert dr.namespace is None
    assert dr.connection_pool is None
    assert dr.outlier_detection is None
    assert dr.tls_mode is None


def test_destination_rule_roundtrip_with_subsets():
    dr = ServiceMeshDestinationRulePayload(
        file_path="dr.yaml",
        name="reviews-dr",
        host="reviews",
        namespace="default",
        connection_pool={"tcp": {"maxConnections": 100}},
        outlier_detection={"consecutiveErrors": 5, "interval": "10s"},
        tls_mode="ISTIO_MUTUAL",
        subsets=[
            ServiceMeshSubset(
                name="v1",
                labels={"version": "v1"},
                traffic_policy={"connectionPool": {"http": {"h2UpgradePolicy": "UPGRADE"}}},
            )
        ],
        has_connection_pool=True,
        has_outlier_detection=True,
    )
    dumped = dr.model_dump()
    restored = ServiceMeshDestinationRulePayload.model_validate(dumped)
    assert restored == dr


def test_rollout_optional_defaults():
    r = ServiceMeshRolloutPayload(
        file_path="rollout.yaml",
        name="web",
        strategy_type="canary",
        analysis_refs=[],
        has_analysis=False,
    )
    assert r.replicas is None
    assert r.canary_steps is None
    assert r.canary_max_surge is None
    assert r.anti_affinity is None


def test_rollout_negative_replicas_accepted():
    """No ge/le constraint on replicas -- model accepts negative values."""
    r = ServiceMeshRolloutPayload(
        file_path="rollout.yaml",
        name="web",
        strategy_type="canary",
        replicas=-1,
        analysis_refs=[],
        has_analysis=False,
    )
    assert r.replicas == -1


def test_analysis_metric_count_zero():
    m = ServiceMeshAnalysisMetric(name="success-rate", count=0)
    assert m.count == 0
    assert m.provider is None
    assert m.success_condition is None


def test_summary_payload_boundary_zero_counts():
    s = ServiceMeshSummaryPayload(
        virtual_services=0,
        destination_rules=0,
        rollouts=0,
        analysis_templates=0,
        files_parsed=0,
        files_failed=0,
    )
    assert s.virtual_services == 0


def test_analysis_arg_none_value():
    """ServiceMeshAnalysisArg.value defaults to None (Any type)."""
    arg = ServiceMeshAnalysisArg(name="service-name")
    assert arg.value is None


def test_analysis_arg_complex_value():
    """value is typed Any -- accepts dicts, lists, etc."""
    arg = ServiceMeshAnalysisArg(name="threshold", value={"min": 0.95, "window": "5m"})
    assert arg.value["min"] == 0.95


# ===================================================================
# 4. PythonAstFilePayload edge cases
# ===================================================================


def test_python_file_minimal():
    p = _python_file_payload()
    assert p.file_path == "app.py"
    assert p.classes == []


def test_python_file_rejects_extra_field():
    with pytest.raises(ValidationError, match="nope"):
        _python_file_payload(nope=1)


def test_python_file_roundtrip_nested():
    cls = PythonClassInfo(
        name="MyClass",
        line=5,
        is_abstract=True,
        is_interface=False,
        base_classes=[PythonBaseClass(name="ABC", access="public")],
        fields=[PythonField(name="name", type="str", access="public", line=6)],
        methods=[
            PythonMethod(
                name="run",
                return_type="None",
                access="public",
                is_virtual=False,
                is_pure_virtual=False,
                line=8,
                parameters=[PythonParameter(name="self", type="MyClass")],
                decorators=["abstractmethod"],
            )
        ],
        namespace="mymodule",
        outer_class="",
    )
    p = _python_file_payload(
        classes=[cls],
        catch_blocks=[
            PythonCatchBlock(
                caught_type="ValueError",
                rethrows=True,
                has_logging=True,
                line=20,
                file="app.py",
            )
        ],
        functions=[
            PythonFunction(
                name="helper",
                line=30,
                is_async=True,
                decorators=["retry"],
                default_args=[PythonDefaultArg(name="timeout", default_type="int", line=30)],
            )
        ],
        imports=[
            PythonImport(module="os", names=["path"], is_star=False, line=1),
            PythonImport(module="typing", names=["*"], is_star=True, line=2),
        ],
        async_calls=[PythonAsyncCall(call="await fetch()", line=35, stored=True)],
    )
    dumped = p.model_dump()
    restored = PythonAstFilePayload.model_validate(dumped)
    assert restored == p


def test_python_method_empty_decorators():
    m = PythonMethod(
        name="plain",
        return_type="int",
        access="public",
        is_virtual=False,
        is_pure_virtual=False,
        line=1,
        parameters=[],
        decorators=[],
    )
    assert m.decorators == []


def test_python_import_star():
    imp = PythonImport(module="os", names=[], is_star=True, line=1)
    assert imp.is_star is True
    assert imp.names == []
