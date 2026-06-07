# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0

# ── Stage 1: Build ──────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

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
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/JimAKennedy/nfr-review" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.documentation="https://github.com/JimAKennedy/nfr-review/blob/main/docs/install.md" \
      org.opencontainers.image.description="Automated non-functional requirements review for polyglot codebases"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
       libharfbuzz0b libcairo2 libgdk-pixbuf-2.0-0 \
       libffi8 shared-mime-info \
       fonts-liberation \
       graphviz \
       git \
       curl ca-certificates gpg \
       nodejs npm \
       chromium \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && PUPPETEER_SKIP_DOWNLOAD=true npm install -g @mermaid-js/mermaid-cli puppeteer \
    && rm -rf /var/lib/apt/lists/* /root/.npm

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Point mermaid-cli / puppeteer at system Chromium (no bundled download)
RUN printf '{"executablePath":"/usr/bin/chromium","args":["--no-sandbox","--disable-gpu"]}\n' \
    > /etc/mmdc-puppeteer.json

RUN useradd --create-home --uid 1000 nfr
USER nfr
WORKDIR /repo

ENTRYPOINT ["nfr-review"]
