# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-08

### Added

- Multi-language AST analysis for Java, Python, Go, C#, and Node.js
- Infrastructure scanning: Kubernetes manifests, Helm charts, Terraform,
  Dockerfiles, Istio service mesh, OpenTelemetry, Skaffold, and Protobuf
- CI/CD pipeline analysis (GitHub Actions)
- ADR (Architecture Decision Record) lifecycle checks
- LLM-assisted rules via Anthropic API: PII detection, ADR drift analysis
- Spring Boot configuration and API Management policy analysis
- CSV and JSONL output formats
- YAML-based project configuration with tech auto-detection
- Pluggable collector/rule architecture with registry-based discovery
- Evidence-based findings with RAG severity rating (Red/Amber/Green)
