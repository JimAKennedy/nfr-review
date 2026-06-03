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

# --- Editable install with dev deps ---
info "Installing nfr-review in editable mode with dev dependencies"
pip install -e "$PROJECT_ROOT[dev]" --quiet

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

# --- LLM backend configuration ---
ENV_FILE="$PROJECT_ROOT/.env"
LLM_BACKEND=""
API_KEY_SET=false

if [[ -f "$ENV_FILE" ]]; then
  _existing_backend="$(grep -E '^NFR_LLM_(PROVIDER|BACKEND)=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2-)" || true
  _existing_key="$(grep '^ANTHROPIC_API_KEY=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2-)" || true
fi

if [[ -n "${_existing_backend:-}" ]] || [[ -n "${_existing_key:-}" ]]; then
  if [[ "${_existing_backend:-}" == "claude-cli" ]]; then
    info "LLM backend already configured: claude-cli (Claude Max)"
    LLM_BACKEND="claude-cli"
  elif [[ -n "${_existing_key:-}" ]]; then
    info "LLM backend already configured: api (Anthropic API key set)"
    LLM_BACKEND="api"
    API_KEY_SET=true
  fi
fi

if [[ -z "$LLM_BACKEND" ]] && [[ -t 0 ]]; then
  echo ""
  info "nfr-review can use an LLM for enhanced rules (ADR drift, PII logging, etc.)"
  echo ""
  echo "  1) Anthropic API key  — pay-per-call via ANTHROPIC_API_KEY"
  echo "  2) Claude CLI         — uses your Claude Max subscription (no API key needed)"
  echo "  3) None               — LLM-powered rules will be skipped"
  echo ""
  read -rp "Choose LLM backend [1/2/3]: " llm_choice
  case "${llm_choice:-3}" in
    1)
      read -rp "ANTHROPIC_API_KEY: " api_key
      if [[ -n "$api_key" ]]; then
        if [[ -f "$ENV_FILE" ]]; then
          sed -i.bak '/^NFR_LLM_PROVIDER=/d; /^NFR_LLM_BACKEND=/d; /^ANTHROPIC_API_KEY=/d' "$ENV_FILE" && rm -f "$ENV_FILE.bak"
        fi
        echo "NFR_LLM_PROVIDER=anthropic" >> "$ENV_FILE"
        echo "ANTHROPIC_API_KEY=$api_key" >> "$ENV_FILE"
        info "API key and backend written to .env"
        LLM_BACKEND="api"
        API_KEY_SET=true
      else
        warn "No API key entered — LLM rules will be skipped"
        LLM_BACKEND="none"
      fi
      ;;
    2)
      if ! command -v claude &>/dev/null; then
        warn "claude CLI not found on PATH — install Claude Code first"
        warn "LLM rules will be unavailable until 'claude' is on PATH"
      fi
      if [[ -f "$ENV_FILE" ]]; then
        sed -i.bak '/^NFR_LLM_BACKEND=/d; /^ANTHROPIC_API_KEY=/d' "$ENV_FILE" && rm -f "$ENV_FILE.bak"
      fi
      echo "NFR_LLM_PROVIDER=claude-cli" >> "$ENV_FILE"
      info "Claude CLI backend written to .env"
      LLM_BACKEND="claude-cli"
      ;;
    *)
      info "Skipped — LLM-powered rules will not run"
      LLM_BACKEND="none"
      ;;
  esac
elif [[ -z "$LLM_BACKEND" ]]; then
  LLM_BACKEND="none"
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
success "Setup complete!"
echo "  Venv:    $VENV_DIR"
echo "  Version: $NFR_VERSION"
case "$LLM_BACKEND" in
  api)       echo "  LLM:     Anthropic API (key configured)" ;;
  claude-cli) echo "  LLM:     Claude CLI (Claude Max)" ;;
  *)         echo "  LLM:     disabled (LLM rules will be skipped)" ;;
esac
echo ""
echo "For future sessions, activate the venv with:"
echo "  source $VENV_DIR/bin/activate"
