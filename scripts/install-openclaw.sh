#!/usr/bin/env bash
set -euo pipefail

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

ok()   { printf "${GREEN}[OK]${NC}    %s\n" "$*"; }
warn() { printf "${YELLOW}[WARN]${NC}  %s\n" "$*"; }
fail() { printf "${RED}[FAIL]${NC}  %s\n" "$*"; exit 1; }
info() { printf "${CYAN}[INFO]${NC}  %s\n" "$*"; }

# ─── Banner ───────────────────────────────────────────────────────────────────
printf "${BOLD}${CYAN}"
cat << 'BANNER'

   ██████╗██╗      █████╗ ██╗    ██╗████████╗███████╗ █████╗ ███╗   ███╗
  ██╔════╝██║     ██╔══██╗██║    ██║╚══██╔══╝██╔════╝██╔══██╗████╗ ████║
  ██║     ██║     ███████║██║ █╗ ██║   ██║   █████╗  ███████║██╔████╔██║
  ██║     ██║     ██╔══██║██║███╗██║   ██║   ██╔══╝  ██╔══██║██║╚██╔╝██║
  ╚██████╗███████╗██║  ██║╚███╔███╔╝   ██║   ███████╗██║  ██║██║ ╚═╝ ██║
   ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝    ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝

  OpenClaw Installer
BANNER
printf "${NC}\n"

# ─── 1. Check Python 3.10+ ───────────────────────────────────────────────────
info "Checking Python version..."
if ! command -v python3 &>/dev/null; then
    fail "python3 is not installed. Please install Python 3.10 or later."
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || { [[ "$PYTHON_MAJOR" -eq 3 ]] && [[ "$PYTHON_MINOR" -lt 10 ]]; }; then
    fail "Python 3.10+ is required (found $PYTHON_VERSION)."
fi
ok "Python $PYTHON_VERSION found."

# ─── 2. Check tmux ───────────────────────────────────────────────────────────
info "Checking tmux..."
if ! command -v tmux &>/dev/null; then
    fail "tmux is not installed. Install it with: brew install tmux (macOS) or apt install tmux (Linux)."
fi
ok "tmux found: $(tmux -V)"

# ─── 3. Check openclaw ───────────────────────────────────────────────────────
info "Checking openclaw..."
if ! command -v openclaw &>/dev/null; then
    if python3 -m openclaw --version &>/dev/null 2>&1; then
        ok "openclaw available via python3 -m openclaw."
    else
        fail "openclaw is not installed. Install it first: pip install openclaw"
    fi
else
    ok "openclaw found: $(openclaw --version 2>/dev/null || echo 'installed')"
fi

# ─── 4. Install clawteam ─────────────────────────────────────────────────────
info "Installing clawteam..."

# Determine the script's own directory and the repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

if [[ -f "$REPO_ROOT/pyproject.toml" ]] && grep -q 'name.*=.*"clawteam"' "$REPO_ROOT/pyproject.toml" 2>/dev/null; then
    info "Installing from local repo: $REPO_ROOT"
    pip install -e "$REPO_ROOT" --quiet 2>&1 | tail -3 || pip install "$REPO_ROOT" --quiet 2>&1 | tail -3
else
    info "Installing from PyPI..."
    pip install clawteam --quiet 2>&1 | tail -3
fi
ok "clawteam installed."

# ─── 5. Find clawteam binary location ────────────────────────────────────────
info "Locating clawteam binary..."
CLAWTEAM_BIN=""

# Method 1: command -v
if command -v clawteam &>/dev/null; then
    CLAWTEAM_BIN="$(command -v clawteam)"
fi

# Method 2: pip show + Scripts/bin dir
if [[ -z "$CLAWTEAM_BIN" ]]; then
    SITE_PKG="$(pip show clawteam 2>/dev/null | grep -i '^Location:' | awk '{print $2}')"
    if [[ -n "$SITE_PKG" ]]; then
        # Typical bin is one level up from site-packages, in a bin/ directory
        CANDIDATE="$(dirname "$(dirname "$SITE_PKG")")/bin/clawteam"
        if [[ -x "$CANDIDATE" ]]; then
            CLAWTEAM_BIN="$CANDIDATE"
        fi
    fi
fi

# Method 3: common paths
if [[ -z "$CLAWTEAM_BIN" ]]; then
    for p in \
        "$HOME/.local/bin/clawteam" \
        "/usr/local/bin/clawteam" \
        "/opt/homebrew/bin/clawteam" \
        "$HOME/Library/Python/3.*/bin/clawteam" \
        "/Library/Frameworks/Python.framework/Versions/3.*/bin/clawteam"; do
        # shellcheck disable=SC2086
        for expanded in $p; do
            if [[ -x "$expanded" ]]; then
                CLAWTEAM_BIN="$expanded"
                break 2
            fi
        done
    done
fi

if [[ -z "$CLAWTEAM_BIN" ]]; then
    fail "Could not locate the clawteam binary. Ensure pip's bin directory is in your PATH."
fi
ok "clawteam binary found at: $CLAWTEAM_BIN"

# ─── 6. Create symlink at ~/bin/clawteam ──────────────────────────────────────
info "Setting up ~/bin/clawteam symlink..."
mkdir -p "$HOME/bin"

if [[ -L "$HOME/bin/clawteam" ]]; then
    EXISTING_TARGET="$(readlink "$HOME/bin/clawteam")"
    if [[ "$EXISTING_TARGET" == "$CLAWTEAM_BIN" ]]; then
        ok "Symlink already correct: ~/bin/clawteam -> $CLAWTEAM_BIN"
    else
        ln -sf "$CLAWTEAM_BIN" "$HOME/bin/clawteam"
        ok "Symlink updated: ~/bin/clawteam -> $CLAWTEAM_BIN"
    fi
elif [[ -e "$HOME/bin/clawteam" ]]; then
    warn "~/bin/clawteam already exists and is not a symlink. Skipping."
else
    ln -s "$CLAWTEAM_BIN" "$HOME/bin/clawteam"
    ok "Symlink created: ~/bin/clawteam -> $CLAWTEAM_BIN"
fi

# ─── 7. Verify ~/bin is in PATH ──────────────────────────────────────────────
info "Checking PATH..."
if echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/bin"; then
    ok "~/bin is in PATH."
else
    warn "~/bin is NOT in your PATH."
    echo ""
    printf "${YELLOW}  Add one of these lines to your shell profile (~/.zshrc or ~/.bashrc):${NC}\n"
    echo ""
    echo "    export PATH=\"\$HOME/bin:\$PATH\""
    echo ""
fi

# ─── 8. Copy SKILL.md ────────────────────────────────────────────────────────
info "Installing OpenClaw skill file..."
SKILL_SRC="$REPO_ROOT/skills/openclaw/SKILL.md"
SKILL_DST="$HOME/.openclaw/workspace/skills/clawteam/SKILL.md"

if [[ ! -f "$SKILL_SRC" ]]; then
    warn "Source skill file not found at $SKILL_SRC — skipping skill copy."
else
    mkdir -p "$(dirname "$SKILL_DST")"
    cp "$SKILL_SRC" "$SKILL_DST"
    ok "Skill file installed to $SKILL_DST"
fi

# ─── 9. Configure exec approvals ─────────────────────────────────────────────
info "Configuring exec approvals for ClawTeam..."
APPROVALS_FILE="$HOME/.openclaw/exec-approvals.json"
if [[ -f "$APPROVALS_FILE" ]]; then
    # Ensure security is "allowlist" (not "full") so spawned agents don't get
    # stuck on interactive permission prompts when running clawteam commands.
    CURRENT_SECURITY=$(python3 -c "import json; d=json.load(open('$APPROVALS_FILE')); print(d.get('defaults',{}).get('security',''))" 2>/dev/null || echo "")
    if [[ "$CURRENT_SECURITY" == "full" ]]; then
        python3 -c "
import json
with open('$APPROVALS_FILE') as f:
    d = json.load(f)
d['defaults']['security'] = 'allowlist'
with open('$APPROVALS_FILE', 'w') as f:
    json.dump(d, f, indent=2)
" 2>/dev/null
        ok "Exec approvals security: full -> allowlist (prevents spawned agents from blocking on permission prompts)"
    else
        ok "Exec approvals security already: ${CURRENT_SECURITY:-default}"
    fi
    # Add clawteam to the allowlist for all agents
    if command -v openclaw &>/dev/null; then
        openclaw approvals allowlist add --agent "*" "*/clawteam" &>/dev/null 2>&1 && \
            ok "Added clawteam to exec approvals allowlist" || \
            warn "Could not add clawteam to allowlist (gateway may not be running)"
    fi
else
    warn "exec-approvals.json not found — run openclaw once first, then re-run this script"
fi

# ─── 10. Verify clawteam --version ───────────────────────────────────────────
info "Verifying installation..."
if "$CLAWTEAM_BIN" --version &>/dev/null; then
    CT_VERSION="$("$CLAWTEAM_BIN" --version 2>&1)"
    ok "clawteam --version: $CT_VERSION"
else
    warn "clawteam --version did not return cleanly, but the binary exists."
fi

# ─── 11. Success ─────────────────────────────────────────────────────────────
echo ""
printf "${BOLD}${GREEN}"
cat << 'MSG'
  ╔═══════════════════════════════════════════════════╗
  ║   Installation complete! ClawTeam is ready.       ║
  ╚═══════════════════════════════════════════════════╝
MSG
printf "${NC}\n"
info "Run 'clawteam --help' to get started."
