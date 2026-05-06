#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)/.regression-repos"
if [ -d "$REPO_DIR" ]; then
    SIZE=$(du -sh "$REPO_DIR" | cut -f1)
    rm -rf "$REPO_DIR"
    echo "Removed $REPO_DIR ($SIZE freed)"
else
    echo "No regression repos to clean up ($REPO_DIR does not exist)"
fi
