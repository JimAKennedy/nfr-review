#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"

supports_color() {
  [[ -t 1 ]] && [[ "${TERM:-}" != "dumb" ]]
}

info()    { echo "==> $*"; }
success() { if supports_color; then echo -e "\033[32m==> $*\033[0m"; else echo "==> $*"; fi; }
warn()    { if supports_color; then echo -e "\033[33m==> WARNING: $*\033[0m"; else echo "==> WARNING: $*"; fi; }
error()   { echo "==> ERROR: $*" >&2; }

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
      local ver
      ver="$("$candidate" -c 'import sys; print(sys.version_info[:2] >= (3, 11))' 2>/dev/null)" || continue
      if [[ "$ver" == "True" ]]; then
        echo "$candidate"
        return
      fi
    fi
  done
  error "Python 3.11+ is required but not found. Install it and retry."
  exit 1
}

PYTHON="$(find_python)"
VENV_DIR="$PROJECT_ROOT/.venv"

# --- Venv creation / reuse ---
if [[ -d "$VENV_DIR" ]]; then
  info "Reusing existing venv at $VENV_DIR"
else
  info "Creating venv at $VENV_DIR (using $PYTHON)"
  "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# --- Upgrade pip ---
info "Upgrading pip"
pip install --upgrade pip --quiet

# --- Editable install with all optional extras ---
info "Installing nfr-review in editable mode with ALL extras (dev, scancode, diagrams)"
pip install -e "$PROJECT_ROOT[dev,scancode,diagrams]" --quiet

# --- External binaries ---
MISSING_BINS=()

if command -v brew &>/dev/null; then
  if ! command -v helm &>/dev/null; then
    info "Installing helm via Homebrew"
    brew install helm
  else
    info "helm already installed: $(helm version --short 2>/dev/null || echo 'unknown')"
  fi

  if ! command -v dot &>/dev/null; then
    info "Installing graphviz (dot) via Homebrew"
    brew install graphviz
  else
    info "graphviz already installed: $(dot -V 2>&1 || echo 'unknown')"
  fi
else
  if ! command -v helm &>/dev/null; then
    MISSING_BINS+=("helm")
  fi
  if ! command -v dot &>/dev/null; then
    MISSING_BINS+=("graphviz (dot)")
  fi
fi

# --- Source validation ---
info "Validating install"

NFR_BIN="$(which nfr-review)"
if [[ "$NFR_BIN" != "$VENV_DIR"/* ]]; then
  error "nfr-review binary resolved to $NFR_BIN (expected under $VENV_DIR/)"
  exit 1
fi

NFR_PKG="$(python -c "import nfr_review; print(nfr_review.__file__)")"
EXPECTED_PKG="$PROJECT_ROOT/src/nfr_review/__init__.py"
if [[ "$NFR_PKG" != "$EXPECTED_PKG" ]]; then
  error "nfr_review package resolved to $NFR_PKG (expected $EXPECTED_PKG)"
  exit 1
fi

# --- Stale worktree detection ---
if [[ "$NFR_BIN" == *".gsd/worktrees/"* ]] || [[ "$NFR_PKG" == *".gsd/worktrees/"* ]]; then
  warn "Install points at a GSD worktree path."
  warn "This may cause unexpected behavior. Consider reinstalling from the main project root."
fi

# --- Verify optional Python packages ---
info "Verifying optional Python packages"
MISSING_PKGS=()

if python -c "from scancode.api import get_licenses" 2>/dev/null; then
  success "scancode-toolkit: OK"
else
  MISSING_PKGS+=("scancode-toolkit")
fi

if python -c "import graphviz" 2>/dev/null; then
  success "graphviz (Python): OK"
else
  MISSING_PKGS+=("graphviz (Python)")
fi

# --- API key prompt ---
ENV_FILE="$PROJECT_ROOT/.env"
API_KEY_SET=false

if [[ -f "$ENV_FILE" ]] && grep -q '^ANTHROPIC_API_KEY=' "$ENV_FILE"; then
  info "ANTHROPIC_API_KEY already configured in .env"
  API_KEY_SET=true
else
  echo ""
  info "nfr-review can use an Anthropic API key for LLM-powered rules."
  info "Leave blank to skip (LLM rules will be disabled)."
  echo ""
  if [[ -t 0 ]]; then
    read -rp "ANTHROPIC_API_KEY (or Enter to skip): " api_key
  else
    api_key=""
  fi
  if [[ -n "$api_key" ]]; then
    echo "ANTHROPIC_API_KEY=$api_key" >> "$ENV_FILE"
    info "API key written to .env"
    API_KEY_SET=true
  else
    info "Skipped — LLM-powered rules will not run without an API key."
  fi
fi

# --- Inject .env loader into venv activate script ---
ACTIVATE_SCRIPT="$VENV_DIR/bin/activate"
MARKER="# nfr-review: auto-load .env"
if ! grep -q "$MARKER" "$ACTIVATE_SCRIPT" 2>/dev/null; then
  info "Adding .env loader to venv activate script"
  cat >> "$ACTIVATE_SCRIPT" << 'ENVLOADER'

# nfr-review: auto-load .env
if [ -f "${VIRTUAL_ENV}/../.env" ]; then
  _nfr_env_file="${VIRTUAL_ENV}/../.env"
elif [ -f "$(cd "${VIRTUAL_ENV}/.." && pwd -P)/.env" ]; then
  _nfr_env_file="$(cd "${VIRTUAL_ENV}/.." && pwd -P)/.env"
else
  _nfr_env_file=""
fi
if [ -n "$_nfr_env_file" ]; then
  while IFS= read -r _nfr_line || [ -n "$_nfr_line" ]; do
    case "$_nfr_line" in
      \#*|"") continue ;;
    esac
    export "$_nfr_line"
  done < "$_nfr_env_file"
fi
unset _nfr_env_file _nfr_line
ENVLOADER
fi

# --- Skills install ---
SKILLS_SCRIPT="$PROJECT_ROOT/scripts/install_skills.py"
if [[ -f "$SKILLS_SCRIPT" ]]; then
  info "Installing agent skills"
  python "$SKILLS_SCRIPT"
fi

# --- Final validation ---
info "Running final validation"
NFR_VERSION="$(nfr-review version 2>&1)" || true

# --- Summary ---
echo ""
success "Full setup complete!"
echo "  Venv:    $VENV_DIR"
echo "  Version: $NFR_VERSION"
if $API_KEY_SET; then
  echo "  API key: configured"
else
  echo "  API key: not set (LLM rules will be skipped)"
fi
echo ""
echo "  Extras installed: dev, scancode, diagrams"
echo ""

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
  warn "Failed to verify Python packages: ${MISSING_PKGS[*]}"
fi

if [[ ${#MISSING_BINS[@]} -gt 0 ]]; then
  warn "Missing external binaries (install manually): ${MISSING_BINS[*]}"
  warn "  helm:     https://helm.sh/docs/intro/install/"
  warn "  graphviz: https://graphviz.org/download/"
fi

if [[ ${#MISSING_PKGS[@]} -eq 0 ]] && [[ ${#MISSING_BINS[@]} -eq 0 ]]; then
  success "All optional dependencies installed — no scans will be skipped."
fi

echo ""
echo "For future sessions, activate the venv with:"
echo "  source $VENV_DIR/bin/activate"
