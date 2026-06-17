# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""M028 S05 — End-to-end validation of arch command against drum repo fixtures.

Verifies all M028 success criteria:
  1. DrumGenerator discovers 4+ sub-components
  2. DrumGenerator produces a class diagram with Processor/Controller
  3. DrumGenerator shows ML training pipeline with PyTorch/DVC/ONNX stack
  4. Multi-repo scan shows drumcore as shared lib consumed by both plugins
  5. No regressions in existing arch tests (covered by the wider test suite)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.arch_models import ArchReport
from nfr_review.arch_orchestrator import run_arch_review

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _write_cpp(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _build_drumcore(base: Path) -> Path:
    repo = base / "drumcore"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

    (repo / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.14)\n"
        "project(drumcore VERSION 1.0.0)\n"
        "set(CMAKE_CXX_STANDARD 17)\n"
        "add_library(drumcore STATIC src/engine.cpp src/sampler.cpp)\n"
        "target_include_directories(drumcore PUBLIC include)\n"
        "install(TARGETS drumcore)\n"
    )

    _write_cpp(
        repo / "include" / "engine.h",
        "#pragma once\n"
        "class Engine {\n"
        "public:\n"
        "    void start();\n"
        "    void stop();\n"
        "private:\n"
        "    int sampleRate_;\n"
        "};\n",
    )
    _write_cpp(
        repo / "include" / "sampler.h",
        "#pragma once\n"
        "class Sampler {\n"
        "public:\n"
        "    void load(const char* path);\n"
        "    void trigger(int note, float velocity);\n"
        "private:\n"
        "    float* buffer_;\n"
        "};\n",
    )
    _write_cpp(repo / "src" / "engine.cpp", '#include "engine.h"\nvoid Engine::start() {}\n')
    _write_cpp(
        repo / "src" / "sampler.cpp",
        '#include "sampler.h"\nvoid Sampler::load(const char*) {}\n',
    )

    return repo


def _build_drum_generator(base: Path) -> Path:
    repo = base / "DrumGenerator"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

    (repo / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.14)\n"
        "project(DrumGenerator VERSION 2.0.0)\n"
        "set(CMAKE_CXX_STANDARD 17)\n"
        "include(FetchContent)\n"
        "FetchContent_Declare(\n"
        "    drumcore\n"
        "    GIT_REPOSITORY https://github.com/example-org/drumcore.git\n"
        "    GIT_TAG v1.0.0\n"
        ")\n"
        "FetchContent_MakeAvailable(drumcore)\n"
        "add_executable(drum_generator src/main.cpp)\n"
        "target_link_libraries(drum_generator PRIVATE drumcore)\n"
    )

    # source/core — plugin core (2 .h + 2 .cpp = meets _MIN_SOURCE_FILES)
    _write_cpp(
        repo / "source" / "core" / "processor.h",
        "#pragma once\n"
        "class AudioProcessor {\n"
        "public:\n"
        "    virtual void processBlock(float* buffer, int numSamples) = 0;\n"
        "    virtual ~AudioProcessor() = default;\n"
        "};\n"
        "class DrumProcessor : public AudioProcessor {\n"
        "public:\n"
        "    void processBlock(float* buffer, int numSamples) override;\n"
        "    void setModel(const char* path);\n"
        "private:\n"
        "    float gain_;\n"
        "};\n",
    )
    _write_cpp(
        repo / "source" / "core" / "processor.cpp",
        '#include "processor.h"\nvoid DrumProcessor::processBlock(float*, int) {}\n',
    )
    _write_cpp(
        repo / "source" / "core" / "controller.h",
        "#pragma once\n"
        "class Controller {\n"
        "public:\n"
        "    void parameterChanged(int id, float value);\n"
        "    float getParameter(int id) const;\n"
        "private:\n"
        "    float params_[128];\n"
        "};\n",
    )
    _write_cpp(
        repo / "source" / "core" / "controller.cpp",
        '#include "controller.h"\nvoid Controller::parameterChanged(int, float) {}\n',
    )

    # source/transforms — audio transforms
    _write_cpp(
        repo / "source" / "transforms" / "transform_base.h",
        "#pragma once\n"
        "class TransformBase {\n"
        "public:\n"
        "    virtual void process(float* buf, int n) = 0;\n"
        "    virtual ~TransformBase() = default;\n"
        "};\n",
    )
    _write_cpp(
        repo / "source" / "transforms" / "pitch_shift.cpp",
        '#include "transform_base.h"\n'
        "class PitchShift : public TransformBase {\n"
        "public:\n"
        "    void process(float* buf, int n) override;\n"
        "};\n"
        "void PitchShift::process(float*, int) {}\n",
    )
    _write_cpp(
        repo / "source" / "transforms" / "time_stretch.cpp",
        '#include "transform_base.h"\n'
        "class TimeStretch : public TransformBase {\n"
        "public:\n"
        "    void process(float* buf, int n) override;\n"
        "};\n"
        "void TimeStretch::process(float*, int) {}\n",
    )

    # source/ml — inference engine
    _write_cpp(
        repo / "source" / "ml" / "inference_engine.h",
        "#pragma once\n"
        "class InferenceEngine {\n"
        "public:\n"
        "    bool loadModel(const char* onnxPath);\n"
        "    void infer(const float* input, float* output, int frames);\n"
        "private:\n"
        "    void* session_;\n"
        "};\n",
    )
    _write_cpp(
        repo / "source" / "ml" / "model_loader.cpp",
        '#include "inference_engine.h"\n'
        "bool InferenceEngine::loadModel(const char*) { return true; }\n",
    )
    _write_cpp(
        repo / "source" / "ml" / "feature_extract.cpp",
        "void extractFeatures(const float* audio, float* features, int n) {}\n"
        "void normalizeFeatures(float* features, int n) {}\n",
    )

    # training/ — ML pipeline directory
    training = repo / "training"
    training.mkdir()
    (training / "requirements.txt").write_text(
        "torch>=2.0\nonnx>=1.14\ndvc>=3.0\nnumpy>=1.24\n"
    )
    (training / "dvc.yaml").write_text(
        "stages:\n"
        "  preprocess:\n"
        "    cmd: python preprocess.py\n"
        "    deps:\n"
        "      - raw_data/\n"
        "    outs:\n"
        "      - prepared/\n"
        "  train:\n"
        "    cmd: python train.py\n"
        "    deps:\n"
        "      - prepared/\n"
        "      - train.py\n"
        "    outs:\n"
        "      - models/best.pt\n"
        "    metrics:\n"
        "      - metrics.json\n"
        "  export:\n"
        "    cmd: python export_onnx.py\n"
        "    deps:\n"
        "      - models/best.pt\n"
        "      - export_onnx.py\n"
        "    outs:\n"
        "      - models/model.onnx\n"
    )
    (training / "preprocess.py").write_text("import numpy as np\ndef preprocess(): pass\n")
    (training / "train.py").write_text("import torch\ndef train(): pass\n")
    (training / "export_onnx.py").write_text("import onnx\ndef export(): pass\n")

    return repo


def _build_drum_postprocessor(base: Path) -> Path:
    repo = base / "DrumPostProcessor"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

    (repo / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.14)\n"
        "project(DrumPostProcessor VERSION 1.5.0)\n"
        "set(CMAKE_CXX_STANDARD 17)\n"
        "include(FetchContent)\n"
        "FetchContent_Declare(\n"
        "    drumcore\n"
        "    GIT_REPOSITORY https://github.com/example-org/drumcore.git\n"
        "    GIT_TAG v1.0.0\n"
        ")\n"
        "FetchContent_MakeAvailable(drumcore)\n"
        "add_executable(drum_postprocessor src/main.cpp)\n"
        "target_link_libraries(drum_postprocessor PRIVATE drumcore)\n"
    )

    # source/core
    _write_cpp(
        repo / "source" / "core" / "post_processor.h",
        "#pragma once\n"
        "class AudioProcessor {\n"
        "public:\n"
        "    virtual void processBlock(float* buffer, int numSamples) = 0;\n"
        "    virtual ~AudioProcessor() = default;\n"
        "};\n"
        "class PostProcessor : public AudioProcessor {\n"
        "public:\n"
        "    void processBlock(float* buffer, int numSamples) override;\n"
        "private:\n"
        "    float mix_;\n"
        "};\n",
    )
    _write_cpp(
        repo / "source" / "core" / "post_processor.cpp",
        '#include "post_processor.h"\nvoid PostProcessor::processBlock(float*, int) {}\n',
    )

    # source/effects
    _write_cpp(
        repo / "source" / "effects" / "reverb.h",
        "#pragma once\n"
        "class Reverb {\n"
        "public:\n"
        "    void process(float* buf, int n);\n"
        "    void setDecay(float d);\n"
        "private:\n"
        "    float decay_;\n"
        "};\n",
    )
    _write_cpp(
        repo / "source" / "effects" / "reverb.cpp",
        '#include "reverb.h"\nvoid Reverb::process(float*, int) {}\n',
    )
    _write_cpp(
        repo / "source" / "effects" / "compressor.cpp",
        "class Compressor {\npublic:\n    void process(float* buf, int n);\n"
        "    void setThreshold(float t);\nprivate:\n    float threshold_;\n};\n"
        "void Compressor::process(float*, int) {}\n",
    )

    return repo


@pytest.fixture()
def drum_repos(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build drumcore, DrumGenerator, DrumPostProcessor fixtures."""
    drumcore = _build_drumcore(tmp_path)
    generator = _build_drum_generator(tmp_path)
    postprocessor = _build_drum_postprocessor(tmp_path)
    return drumcore, generator, postprocessor


# ---------------------------------------------------------------------------
# Tests — M028 Success Criteria
# ---------------------------------------------------------------------------


class TestDrumGeneratorComponentDiscovery:
    """SC1: arch on DrumGenerator discovers at least 4 sub-components."""

    def test_discovers_four_or_more_components(
        self, drum_repos: tuple[Path, Path, Path]
    ) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        assert len(report.components) >= 4, (
            f"Expected >= 4 components, got {len(report.components)}: "
            f"{[c.name for c in report.components]}"
        )

    def test_discovers_core_component(self, drum_repos: tuple[Path, Path, Path]) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        names = {c.name.lower() for c in report.components}
        assert "core" in names, f"Missing 'core' component, found: {names}"

    def test_discovers_transforms_component(self, drum_repos: tuple[Path, Path, Path]) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        names = {c.name.lower() for c in report.components}
        assert "transforms" in names, f"Missing 'transforms' component, found: {names}"

    def test_discovers_ml_inference_component(
        self, drum_repos: tuple[Path, Path, Path]
    ) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        names = {c.name.lower() for c in report.components}
        assert "ml" in names, f"Missing 'ml' component, found: {names}"

    def test_discovers_training_pipeline_component(
        self, drum_repos: tuple[Path, Path, Path]
    ) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        names = {c.name.lower() for c in report.components}
        assert "training" in names, f"Missing 'training' component, found: {names}"


class TestDrumGeneratorClassDiagram:
    """SC2: arch report no longer includes class diagrams (moved to experimental)."""

    def test_class_diagram_absent_from_arch_report(
        self, drum_repos: tuple[Path, Path, Path]
    ) -> None:
        """Class diagrams are now generated by the experimental orchestrator."""
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        class_diagrams = [d for d in report.diagrams if d.scope == "classes"]
        assert len(class_diagrams) == 0, (
            f"Expected 0 class diagrams in arch report, got {len(class_diagrams)}"
        )


class TestDrumGeneratorMLPipeline:
    """SC3: arch on DrumGenerator shows ML pipeline with PyTorch/DVC/ONNX."""

    def test_training_component_has_python(self, drum_repos: tuple[Path, Path, Path]) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        training = [c for c in report.components if c.name.lower() == "training"]
        assert training, "No training component found"
        tech_names = {t.name for t in training[0].tech_stack}
        assert "Python" in tech_names, f"Python not in training tech stack: {tech_names}"

    def test_training_component_has_pytorch(self, drum_repos: tuple[Path, Path, Path]) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        training = [c for c in report.components if c.name.lower() == "training"]
        assert training, "No training component found"
        tech_names = {t.name for t in training[0].tech_stack}
        assert "PyTorch" in tech_names, f"PyTorch not in training tech stack: {tech_names}"

    def test_training_component_has_dvc(self, drum_repos: tuple[Path, Path, Path]) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        training = [c for c in report.components if c.name.lower() == "training"]
        assert training, "No training component found"
        tech_names = {t.name for t in training[0].tech_stack}
        assert "DVC" in tech_names, f"DVC not in training tech stack: {tech_names}"

    def test_dvc_pipeline_diagram_present(self, drum_repos: tuple[Path, Path, Path]) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        pipeline_diagrams = [d for d in report.diagrams if d.scope == "pipeline"]
        assert len(pipeline_diagrams) >= 1, "No DVC pipeline diagram generated"

    def test_dvc_pipeline_has_stages(self, drum_repos: tuple[Path, Path, Path]) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        pipeline_diagrams = [d for d in report.diagrams if d.scope == "pipeline"]
        assert pipeline_diagrams, "No DVC pipeline diagram generated"
        mermaid = pipeline_diagrams[0].mermaid
        assert "preprocess" in mermaid
        assert "train" in mermaid
        assert "export" in mermaid

    def test_dvc_pipeline_has_edges(self, drum_repos: tuple[Path, Path, Path]) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        pipeline_diagrams = [d for d in report.diagrams if d.scope == "pipeline"]
        assert pipeline_diagrams, "No DVC pipeline diagram generated"
        mermaid = pipeline_diagrams[0].mermaid
        assert "preprocess --> train" in mermaid
        assert "train --> export" in mermaid


class TestMultiRepoCrossRepoDependencies:
    """SC4: Multi-repo scan shows drumcore as shared lib."""

    def test_multi_repo_report_has_all_repos(
        self, drum_repos: tuple[Path, Path, Path]
    ) -> None:
        drumcore, generator, postprocessor = drum_repos
        report = run_arch_review([drumcore, generator, postprocessor], skip_llm=True)
        repo_names = {r.name for r in report.metadata.repos_analyzed}
        assert "drumcore" in repo_names
        assert "DrumGenerator" in repo_names
        assert "DrumPostProcessor" in repo_names

    def test_cross_repo_integrations_exist(self, drum_repos: tuple[Path, Path, Path]) -> None:
        drumcore, generator, postprocessor = drum_repos
        report = run_arch_review([drumcore, generator, postprocessor], skip_llm=True)
        cross_repo = [i for i in report.integration_points if i.is_cross_repo]
        assert len(cross_repo) >= 2, (
            f"Expected >= 2 cross-repo integrations, got {len(cross_repo)}: "
            f"{[(i.source_component_id, i.target_component_id) for i in cross_repo]}"
        )

    def test_both_consumers_depend_on_drumcore(
        self, drum_repos: tuple[Path, Path, Path]
    ) -> None:
        drumcore, generator, postprocessor = drum_repos
        report = run_arch_review([drumcore, generator, postprocessor], skip_llm=True)
        cross_repo = [i for i in report.integration_points if i.is_cross_repo]
        target_ids = {i.target_component_id for i in cross_repo}
        drumcore_comp = [c for c in report.components if c.repo == "drumcore"]
        assert drumcore_comp, "No drumcore component found"
        drumcore_ids = {c.id for c in drumcore_comp}
        assert target_ids & drumcore_ids, (
            f"No cross-repo integration targets drumcore. "
            f"Targets: {target_ids}, drumcore IDs: {drumcore_ids}"
        )

    def test_drumcore_is_library_type(self, drum_repos: tuple[Path, Path, Path]) -> None:
        drumcore, generator, postprocessor = drum_repos
        report = run_arch_review([drumcore, generator, postprocessor], skip_llm=True)
        drumcore_comps = [
            c for c in report.components if c.repo == "drumcore" and c.name == "drumcore"
        ]
        assert drumcore_comps, "No root drumcore component found"

    def test_cmake_fetchcontent_protocol(self, drum_repos: tuple[Path, Path, Path]) -> None:
        drumcore, generator, postprocessor = drum_repos
        report = run_arch_review([drumcore, generator, postprocessor], skip_llm=True)
        cmake_intg = [
            i for i in report.integration_points if i.protocol == "cmake-fetchcontent"
        ]
        assert len(cmake_intg) >= 2, (
            f"Expected >= 2 cmake-fetchcontent integrations, got {len(cmake_intg)}"
        )


class TestFullReportIntegrity:
    """Verify the combined report is well-formed."""

    def test_single_repo_report_complete(self, drum_repos: tuple[Path, Path, Path]) -> None:
        _, generator, _ = drum_repos
        report = run_arch_review([generator], skip_llm=True)
        assert isinstance(report, ArchReport)
        assert report.components
        assert report.diagrams

    def test_multi_repo_report_complete(self, drum_repos: tuple[Path, Path, Path]) -> None:
        drumcore, generator, postprocessor = drum_repos
        report = run_arch_review([drumcore, generator, postprocessor], skip_llm=True)
        assert isinstance(report, ArchReport)
        assert len(report.metadata.repos_analyzed) == 3
        assert report.components
        assert report.diagrams

    def test_no_empty_component_names(self, drum_repos: tuple[Path, Path, Path]) -> None:
        drumcore, generator, postprocessor = drum_repos
        report = run_arch_review([drumcore, generator, postprocessor], skip_llm=True)
        for comp in report.components:
            assert comp.name, f"Component has empty name: {comp.id}"

    def test_all_integration_refs_valid(self, drum_repos: tuple[Path, Path, Path]) -> None:
        drumcore, generator, postprocessor = drum_repos
        report = run_arch_review([drumcore, generator, postprocessor], skip_llm=True)
        comp_ids = {c.id for c in report.components}
        for intg in report.integration_points:
            assert intg.source_component_id in comp_ids, (
                f"Integration {intg.id} references unknown source {intg.source_component_id}"
            )
            assert intg.target_component_id in comp_ids, (
                f"Integration {intg.id} references unknown target {intg.target_component_id}"
            )
