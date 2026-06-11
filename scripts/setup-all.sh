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
info "Installing nfr-review in editable mode with ALL extras (dev, scancode, diagrams, pdf)"
pip install -e "$PROJECT_ROOT[dev,scancode,diagrams,pdf]" --quiet

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

  if ! brew list libmagic &>/dev/null; then
    info "Installing libmagic via Homebrew (required by scancode-toolkit)"
    brew install libmagic
  else
    info "libmagic already installed"
  fi

  if ! command -v otelcol-contrib &>/dev/null; then
    info "Installing otelcol-contrib via Homebrew (required for --collector / dynamic analysis)"
    brew install open-telemetry/opentelemetry-collector/opentelemetry-collector-contrib || {
      warn "Failed to install otelcol-contrib — --collector flag will not work"
      MISSING_BINS+=("otelcol-contrib (brew install failed)")
    }
  else
    info "otelcol-contrib already installed: $(otelcol-contrib --version 2>&1 | head -1 || echo 'unknown')"
  fi

  # macOS ships a /usr/bin/java stub that passes `command -v` but doesn't work.
  # Test with `java -version` to detect a real JRE.
  if ! java -version &>/dev/null 2>&1; then
    info "Installing OpenJDK 21 via Homebrew (required by JDepend)"
    brew install openjdk@21
    # openjdk is keg-only — add to PATH for the rest of this script
    if [[ -d "$(brew --prefix openjdk@21)/bin" ]]; then
      export PATH="$(brew --prefix openjdk@21)/bin:$PATH"
    fi
  else
    info "java already installed: $(java -version 2>&1 | head -1)"
  fi
else
  if ! command -v helm &>/dev/null; then
    MISSING_BINS+=("helm")
  fi
  if ! command -v dot &>/dev/null; then
    MISSING_BINS+=("graphviz (dot)")
  fi
  if ! python -c "from typecode.magic2 import load_lib; load_lib()" 2>/dev/null; then
    MISSING_BINS+=("libmagic (required by scancode-toolkit)")
  fi
  if ! command -v otelcol-contrib &>/dev/null; then
    MISSING_BINS+=("otelcol-contrib (OpenTelemetry Collector Contrib — required for dynamic analysis)")
  fi
  if ! java -version &>/dev/null 2>&1; then
    MISSING_BINS+=("java (OpenJDK 21+ — required by JDepend)")
  fi
  if ! command -v otelcol-contrib &>/dev/null; then
    MISSING_BINS+=("otelcol-contrib (required for --collector / dynamic analysis)")
  fi
fi

# --- JDepend (Java structural analysis) ---
JDEPEND_VERSION="2.10"
JDEPEND_DIR="$PROJECT_ROOT/.tools/jdepend"

# Resolve a working java binary — prefer brew's keg-only openjdk over PATH.
# macOS ships /usr/bin/java which looks present but fails at runtime.
find_java_bin() {
  if command -v brew &>/dev/null; then
    local brew_java
    brew_java="$(brew --prefix openjdk@21 2>/dev/null)/bin/java"
    if [[ -x "$brew_java" ]] && "$brew_java" -version &>/dev/null 2>&1; then
      echo "$brew_java"
      return
    fi
  fi
  local sys_java
  sys_java="$(command -v java 2>/dev/null)"
  if [[ -n "$sys_java" ]] && "$sys_java" -version &>/dev/null 2>&1; then
    echo "$sys_java"
    return
  fi
  return 1
}

# Write (or rewrite) the jdepend wrapper with the given java path.
write_jdepend_wrapper() {
  local java_bin="$1"
  local jar="$2"
  local wrapper="$VENV_DIR/bin/jdepend"
  cat > "$wrapper" << JDWRAPPER
#!/usr/bin/env bash
exec "$java_bin" -cp "$jar" jdepend.xmlui.JDepend "\$@"
JDWRAPPER
  chmod +x "$wrapper"
  success "JDepend wrapper installed at $wrapper (java: $java_bin)"
}

JDEPEND_JAR="$(find "$JDEPEND_DIR" -name 'jdepend-*.jar' -print -quit 2>/dev/null)"
JDEPEND_NEEDS_INSTALL=true
JDEPEND_NEEDS_WRAPPER=false

# If wrapper exists, verify it actually works (java binary may have moved/vanished).
if command -v jdepend &>/dev/null && jdepend 2>&1 | grep -qi 'usage\|jdepend' &>/dev/null; then
  info "jdepend already installed and working"
  JDEPEND_NEEDS_INSTALL=false
elif [[ -n "$JDEPEND_JAR" ]]; then
  info "JDepend jar found but wrapper is missing or broken — regenerating"
  JDEPEND_NEEDS_INSTALL=false
  JDEPEND_NEEDS_WRAPPER=true
fi

if $JDEPEND_NEEDS_INSTALL; then
  if JAVA_BIN="$(find_java_bin)"; then
    info "Installing JDepend $JDEPEND_VERSION"
    mkdir -p "$JDEPEND_DIR"
    JDEPEND_URL="https://github.com/clarkware/jdepend/releases/download/$JDEPEND_VERSION/jdepend-$JDEPEND_VERSION.zip"
    if command -v curl &>/dev/null; then
      curl -fsSL "$JDEPEND_URL" -o "$JDEPEND_DIR/jdepend.zip" 2>/dev/null || {
        warn "Failed to download JDepend — JDepend analysis will be skipped"
        MISSING_BINS+=("jdepend (download failed)")
      }
    elif command -v wget &>/dev/null; then
      wget -q "$JDEPEND_URL" -O "$JDEPEND_DIR/jdepend.zip" 2>/dev/null || {
        warn "Failed to download JDepend — JDepend analysis will be skipped"
        MISSING_BINS+=("jdepend (download failed)")
      }
    else
      MISSING_BINS+=("jdepend (no curl or wget)")
    fi

    if [[ -f "$JDEPEND_DIR/jdepend.zip" ]]; then
      unzip -qo "$JDEPEND_DIR/jdepend.zip" -d "$JDEPEND_DIR" 2>/dev/null || {
        warn "Failed to extract JDepend archive"
        MISSING_BINS+=("jdepend (extraction failed)")
      }
      JDEPEND_JAR="$(find "$JDEPEND_DIR" -name 'jdepend-*.jar' -print -quit 2>/dev/null)"
      if [[ -n "$JDEPEND_JAR" ]]; then
        write_jdepend_wrapper "$JAVA_BIN" "$JDEPEND_JAR"
      else
        warn "JDepend jar not found after extraction"
        MISSING_BINS+=("jdepend (jar not found)")
      fi
      rm -f "$JDEPEND_DIR/jdepend.zip"
    fi
  else
    warn "Java not found — JDepend requires a JRE. Skipping JDepend install."
    MISSING_BINS+=("jdepend (requires java)")
  fi
fi

# Regenerate wrapper when jar exists but wrapper is broken (e.g. stale java path).
if $JDEPEND_NEEDS_WRAPPER && [[ -n "$JDEPEND_JAR" ]]; then
  if JAVA_BIN="$(find_java_bin)"; then
    write_jdepend_wrapper "$JAVA_BIN" "$JDEPEND_JAR"
  else
    warn "Java not found — cannot regenerate JDepend wrapper"
    MISSING_BINS+=("jdepend (requires java)")
  fi
fi

# --- Mermaid CLI (mmdc) ---
if command -v mmdc &>/dev/null; then
  info "mmdc already installed: $(mmdc --version 2>/dev/null || echo 'unknown')"
elif command -v npm &>/dev/null; then
  info "Installing @mermaid-js/mermaid-cli via npm"
  npm install -g @mermaid-js/mermaid-cli --quiet 2>/dev/null || {
    warn "npm install of @mermaid-js/mermaid-cli failed — Mermaid diagrams will not render"
  }
else
  MISSING_BINS+=("mmdc (@mermaid-js/mermaid-cli — requires npm)")
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

if python -c "import weasyprint" 2>/dev/null; then
  success "weasyprint: OK"
else
  MISSING_PKGS+=("weasyprint")
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
success "Full setup complete!"
echo "  Venv:    $VENV_DIR"
echo "  Version: $NFR_VERSION"
case "$LLM_BACKEND" in
  api)       echo "  LLM:     Anthropic API (key configured)" ;;
  claude-cli) echo "  LLM:     Claude CLI (Claude Max)" ;;
  *)         echo "  LLM:     disabled (LLM rules will be skipped)" ;;
esac
echo ""
echo "  Extras installed: dev, scancode, diagrams, pdf"
echo ""

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
  warn "Failed to verify Python packages: ${MISSING_PKGS[*]}"
fi

if [[ ${#MISSING_BINS[@]} -gt 0 ]]; then
  warn "Missing external binaries (install manually): ${MISSING_BINS[*]}"
  warn "  helm:     https://helm.sh/docs/intro/install/"
  warn "  graphviz: https://graphviz.org/download/"
  warn "  libmagic: brew install libmagic (macOS) or apt-get install libmagic1 (Debian/Ubuntu)"
  warn "  java:     brew install openjdk@21 (macOS) or apt-get install openjdk-21-jre (Debian/Ubuntu)"
  warn "  jdepend:  https://github.com/clarkware/jdepend (requires Java)"
  warn "  otelcol:  brew install open-telemetry/opentelemetry-collector/opentelemetry-collector-contrib"
fi

if [[ ${#MISSING_PKGS[@]} -eq 0 ]] && [[ ${#MISSING_BINS[@]} -eq 0 ]]; then
  success "All optional dependencies installed — no scans will be skipped."
fi

echo ""
echo "For future sessions, activate the venv with:"
echo "  source $VENV_DIR/bin/activate"
