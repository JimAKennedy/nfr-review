#!/usr/bin/env bash
set -euo pipefail

# System tools
sudo apt-get update -q
sudo apt-get install -y -q graphviz

# Python dependencies
pip install --upgrade pip
pip install -e ".[dev,otel,scancode]"

# Mermaid CLI (matches nightly MMDC_VERSION)
npm install -g @mermaid-js/mermaid-cli@12.2.0

# jk-standards delivery workflow commands
pip install "git+https://github.com/JimAKennedy/jk-standards.git@v0.19.0"
jk-standards install-commands --root /workspaces/nfr-review
