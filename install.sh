#!/usr/bin/env bash
# vendor-guard installer — Linux + macOS (Path B, cloud standalone)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/RobinGase/Vendor_Guard/main/install.sh | bash
#   # or, after cloning:
#   bash install.sh
#
# Env overrides:
#   VENDOR_GUARD_REPO   — defaults to RobinGase/Vendor_Guard-public on GitHub
#   VENDOR_GUARD_HOME   — install dir (default: ~/.local/share/vendor-guard)
#   VENDOR_GUARD_BIN    — launcher dir (default: ~/.local/bin)
#   ANTHROPIC_API_KEY   — if set, skips the interactive prompt
#
# This installer covers Path B only. Path A (saaf-compliance-shell) needs
# Linux + KVM + Ollama + a Firecracker rootfs and is documented separately.

set -euo pipefail

REPO_URL="${VENDOR_GUARD_REPO:-https://github.com/RobinGase/Vendor_Guard-public.git}"
INSTALL_DIR="${VENDOR_GUARD_HOME:-$HOME/.local/share/vendor-guard}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/vendor-guard"
BIN_DIR="${VENDOR_GUARD_BIN:-$HOME/.local/bin}"

err()  { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$1"; }
info() { printf '%s\n' "$1"; }

# Re-attach stdin to the controlling terminal when piped through curl|bash,
# so the API-key prompt still works.
if [ ! -t 0 ] && [ -e /dev/tty ]; then
  exec < /dev/tty
fi

# 1. Prereqs --------------------------------------------------------------
command -v git >/dev/null \
  || err "git is required (Xcode CLI tools on macOS, or your distro's git package)."
command -v python3 >/dev/null \
  || err "python3 is required (Python 3.11 or 3.12)."

# Find a usable interpreter — prefer 3.12, fall back to 3.11. Reject 3.13+.
PY=""
for cand in python3.12 python3.11 python3; do
  command -v "$cand" >/dev/null || continue
  ver=$("$cand" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  case "$ver" in
    3.11|3.12) PY="$cand"; break ;;
  esac
done
[ -n "$PY" ] || err "Need Python 3.11 or 3.12 (3.13+ excluded — NeMo/LangChain compat). Install via your package manager, pyenv, or python.org."
ok "Using $($PY --version) at $(command -v "$PY")"

# 2. Clone or fast-forward ------------------------------------------------
if [ -d "$INSTALL_DIR/.git" ]; then
  info "Updating existing checkout at $INSTALL_DIR"
  git -C "$INSTALL_DIR" pull --ff-only
else
  info "Cloning into $INSTALL_DIR"
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi
ok "Source ready"

# 3. Isolated venv + pinned deps ------------------------------------------
info "Creating venv and installing dependencies"
"$PY" -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
ok "Dependencies installed"

# 4. API key --------------------------------------------------------------
mkdir -p "$CONFIG_DIR" && chmod 700 "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/env" ]; then
  KEY="${ANTHROPIC_API_KEY:-}"
  if [ -z "$KEY" ]; then
    if [ -t 0 ]; then
      printf 'Anthropic API key (sk-ant-...): '
      stty -echo 2>/dev/null || true
      read -r KEY
      stty echo 2>/dev/null || true
      echo
    else
      err "No ANTHROPIC_API_KEY in env and no TTY for prompting. Set it and re-run: ANTHROPIC_API_KEY=sk-ant-... bash install.sh"
    fi
  fi
  [ -n "$KEY" ] || err "Empty API key — aborting."
  ( umask 077; printf 'ANTHROPIC_API_KEY=%s\n' "$KEY" > "$CONFIG_DIR/env" )
  ok "API key written to $CONFIG_DIR/env (mode 0600)"
else
  ok "Existing API key in $CONFIG_DIR/env preserved"
fi

# 5. Launcher -------------------------------------------------------------
mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/vendor-guard"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set -a
. "$CONFIG_DIR/env"
set +a
exec "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/tui.py" "\$@"
EOF
chmod +x "$LAUNCHER"
ok "Launcher written to $LAUNCHER"

# 6. PATH hint ------------------------------------------------------------
echo
echo "Done. Run:  vendor-guard"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo
    echo "Note: $BIN_DIR is not on your PATH."
    echo "Add this to ~/.bashrc or ~/.zshrc:"
    echo "  export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac
