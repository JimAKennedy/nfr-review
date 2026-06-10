# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0

# ── Stage 1: Build ──────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir .[pdf,diagrams,llm-anthropic,llm-openai]

# ── Stage 2: Runtime ────────────────────────────────────────────────────
FROM python:3.14-slim

LABEL org.opencontainers.image.source="https://github.com/JimAKennedy/nfr-review" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.documentation="https://github.com/JimAKennedy/nfr-review/blob/main/docs/install.md" \
      org.opencontainers.image.description="Automated non-functional requirements review for polyglot codebases"

# WeasyPrint needs Cairo/Pango; git is needed for repo analysis.
# No Node.js, Chromium, npm, or mermaid-cli — diagrams use bundled
# Mermaid.js (HTML) or pure-Python SVG fallbacks (PDF).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
       libharfbuzz0b libcairo2 libgdk-pixbuf-2.0-0 \
       libffi8 shared-mime-info \
       fonts-liberation \
       git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 1000 nfr
USER nfr
WORKDIR /repo

ENTRYPOINT ["nfr-review"]
