# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0

# ── Stage 1: Build ──────────────────────────────────────────────────────
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir .
# pip is not needed at runtime, and it vendors its own copies of urllib3,
# setuptools (pkg_resources) and msgpack that lag upstream security fixes.
RUN pip uninstall --yes --root-user-action=ignore pip

# ── Stage 2: Runtime ────────────────────────────────────────────────────
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

LABEL org.opencontainers.image.source="https://github.com/JimAKennedy/nfr-review" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.documentation="https://github.com/JimAKennedy/nfr-review/blob/main/docs/install.md" \
      org.opencontainers.image.description="Automated non-functional requirements review for polyglot codebases"

# fonts-liberation provides Liberation Sans used by typst; git is needed for repo analysis.
# zlib1g is named so apt upgrades the base image's copy to the Debian
# security fix for CVE-2026-76844 and CVE-2026-85091.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       fonts-liberation \
       git \
       zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Drop the base image's system pip for the same reason as the venv's.
RUN python -m pip uninstall --yes --root-user-action=ignore pip

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 1000 nfr
USER nfr
WORKDIR /repo

ENTRYPOINT ["nfr-review"]
